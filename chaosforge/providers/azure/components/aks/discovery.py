"""
Azure AKS Discovery
Discovers AKS clusters, namespaces, deployments and containers via the
Kubernetes Python client (services.k8s_client dispatcher) and the az CLI,
with real kubectl subprocess calls kept only as an automatic fallback for
anything the dispatcher doesn't recognise or that errors.
"""

import json
import subprocess

from chaosforge.common.azure_cli import azure_cli_command


def _kubectl(*args, context=None):
    """
    Run a kubectl-equivalent command. Tries the shared Python-client
    dispatcher (services.k8s_client.dispatch_kubectl) first — the same
    interception point used throughout actions/ — and falls back to the
    real kubectl subprocess for anything the dispatcher doesn't recognise
    or that errors.
    """
    from chaosforge.providers.azure.components.aks.kubernetes import (
        run_kubernetes_command,
    )

    return run_kubernetes_command(args, context)


def _kubectl_json(args, context=None):
    """Run a kubectl command (argv list, first element "kubectl") with -o json
    and return parsed JSON, or None on failure.

    context is passed through as a proper keyword argument to _kubectl()
    rather than embedded as a literal "--context X" pair inside args. This
    matters: an embedded "--context" is an unrecognised flag to the
    dispatcher's argument parser, which forces every call here to silently
    fall back to the real kubectl subprocess — while sibling call sites
    elsewhere in the platform pass context= properly and go through the
    Python-client dispatcher. Two different transports resolving the same
    context name is exactly the kind of asymmetry that can make ground-truth
    pod ownership queries (this module) disagree with label-selector queries
    (services/k8s_client.py) for reasons that have nothing to do with actual
    pod state. Passing context consistently here keeps both sides on the
    same transport.
    """
    r = _kubectl(*args[1:], "-o", "json", context=context)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None



class AzureAKSDiscovery:

    def __init__(self):
        self.last_error = None

    def list_contexts(self):
        # Get all kubectl contexts. Context listing is a pure local
        # kubeconfig-file read (no cluster API call), so it's served by the
        # Kubernetes Python client's list_kube_config_contexts(); real
        # kubectl subprocess is only a fallback if that path raises.
        try:
            from chaosforge.providers.azure.components.aks.kubernetes import (
                list_kube_contexts,
            )

            all_contexts = list_kube_contexts()
        except Exception:  # noqa: BLE001
            all_contexts = []

        # Filter to AKS only — exclude EKS (arn:aws:eks:...) and GKE (gke_...)
        # Also cross-reference with az aks list for accuracy
        aks_names = set()
        try:
            az = subprocess.run(
                azure_cli_command("aks", "list", "--query", "[].name", "-o", "tsv"),
                capture_output=True, text=True
            )
            if az.returncode == 0:
                aks_names = {n.strip() for n in az.stdout.strip().splitlines() if n.strip()}
        except Exception:
            pass

        result = []
        for ctx in all_contexts:
            # Exclude known non-Azure prefixes
            if ctx.startswith(("arn:aws:", "gke_")):
                continue
            # If we got AKS names from az, only include matching contexts
            if aks_names:
                if any(name in ctx for name in aks_names):
                    result.append(ctx)
            else:
                # az not available or not logged in — fall back to all non-AWS/GKE contexts
                result.append(ctx)

        return result

    def list_namespaces(self, context):
        self.last_error = None
        r = _kubectl(
            "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}",
            context=context
        )
        if r.returncode != 0:
            detail = (r.stderr or r.stdout or "Unknown Kubernetes API error").strip()
            self.last_error = (
                f"Could not list namespaces using Kubernetes context '{context}': "
                f"{detail}"
            )
            return []
        ns = r.stdout.strip().split()
        return [n for n in ns if n not in ("kube-node-lease", "kube-public", "chaos-testing", "kube-system")]

    def list_deployments(self, context, namespace):
        r = _kubectl(
            "get", "deployments", "-n", namespace, "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}", context=context)
        if r.returncode != 0:
            return []
        return [d.strip() for d in r.stdout.strip().splitlines() if d.strip()]

    def list_containers(self, context, namespace, deployment):
        r = _kubectl(
            "get", "deployment", deployment, "-n", namespace, "-o", "jsonpath={range .spec.template.spec.containers[*]}{.name}{\"\\n\"}{end}", context=context)
        if r.returncode != 0:
            return []
        return [c.strip() for c in r.stdout.strip().splitlines() if c.strip()]

    def list_pod_containers(self, context, namespace, pod_name):
        """List containers in a specific pod."""
        r = _kubectl(
            "get", "pod", pod_name, "-n", namespace, "-o", "jsonpath={range .spec.containers[*]}{.name}{\"\\n\"}{end}", context=context)
        if r.returncode != 0:
            return []
        return [c.strip() for c in r.stdout.strip().splitlines() if c.strip()]

    def get_label_selector(self, context, namespace, deployment):
        r = _kubectl(
            "get", "deployment", deployment, "-n", namespace, "-o", "json", context=context)
        if r.returncode != 0:
            return "app", deployment
        try:
            d = json.loads(r.stdout)
            labels = d.get("spec", {}).get("selector", {}).get("matchLabels", {})
            if labels:
                key, val = next(iter(labels.items()))
                return key, val
        except Exception:
            pass
        return "app", deployment

    def get_pod_count(self, context, namespace, label_key, label_val):
        r = _kubectl(
            "get", "pods", "-n", namespace, "-l", f"{label_key}={label_val}", "--no-headers", context=context)
        if r.returncode != 0:
            return 0
        return len([l for l in r.stdout.strip().splitlines() if l.strip()])

    def list_pods(self, context, namespace):
        """Return all running pod names in the namespace."""
        r = _kubectl(
            "get", "pods", "-n", namespace, "--field-selector=status.phase=Running", "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}", context=context)
        if r.returncode != 0:
            return []
        return [p.strip() for p in r.stdout.strip().splitlines() if p.strip()]

    def get_pod_label(self, context, namespace, pod_name):
        """Return (label_key, label_value) for a specific pod — falls back to pod name."""
        r = _kubectl(
            "get", "pod", pod_name, "-n", namespace, "-o", "json", context=context)
        if r.returncode == 0:
            try:
                d = json.loads(r.stdout)
                labels = d.get("metadata", {}).get("labels", {})
                # Prefer 'app' label, then first available
                if "app" in labels:
                    return "app", labels["app"]
                if labels:
                    key, val = next(iter(labels.items()))
                    return key, val
            except Exception:
                pass
        return "app", pod_name

    def list_nodes(self, context):
        """Return list of worker node names (excludes master/control-plane nodes)."""
        r = _kubectl(
            "get", "nodes", "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\t\"}{.spec.taints}{\"\\n\"}{end}", context=context)
        if r.returncode != 0:
            return []
        nodes = []
        for line in r.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            name = parts[0].strip()
            taints = parts[1].strip() if len(parts) > 1 else ""
            # Skip control-plane nodes
            if "node-role.kubernetes.io/control-plane" in taints or \
               "node-role.kubernetes.io/master" in taints:
                continue
            nodes.append(name)
        return nodes

    def list_zones(self, context):
        """Return sorted list of unique availability zones for nodes in the cluster."""
        r = _kubectl(
            "get", "nodes", "-o", "jsonpath={range .items[*]}{.metadata.labels.topology\\.kubernetes\\.io/zone}{\"\\n\"}{end}", context=context)
        if r.returncode != 0:
            return []
        zones = sorted({z.strip() for z in r.stdout.strip().splitlines() if z.strip()})
        return zones

    def list_nodes_in_zone(self, context, zone):
        """Return list of node names in a specific availability zone."""
        r = _kubectl(
            "get", "nodes", "-l", f"topology.kubernetes.io/zone={zone}", "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}", context=context)
        if r.returncode != 0:
            return []
        return [n.strip() for n in r.stdout.strip().splitlines() if n.strip()]

    def get_vmss_instance_for_node(self, context, node_name, subscription_id, resource_group):
        """
        Given a node name, return (vmss_name, instance_id) by cross-referencing
        the node's providerID with the VMSS instances in Azure.
        """
        # Get providerID from the node — format: azure:///subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Compute/virtualMachineScaleSets/<vmss>/virtualMachines/<id>
        r = _kubectl(
            "get", "node", node_name, "-o", "jsonpath={.spec.providerID}", context=context)
        if r.returncode != 0 or not r.stdout.strip():
            return None, None

        provider_id = r.stdout.strip()
        # Strip azure:// or azure:/// prefix safely
        import re as _re
        provider_id = _re.sub(r'^azure:/+', '', provider_id)
        # Extract vmss name and instance id from the path
        parts = provider_id.split("/")
        try:
            vmss_idx = parts.index("virtualMachineScaleSets")
            vmss_name = parts[vmss_idx + 1]
            instance_id = parts[parts.index("virtualMachines") + 1]
            return vmss_name, instance_id
        except (ValueError, IndexError):
            return None, None

    # ── Selector-scope validation helpers ────────────────────────────────────
    # These are additive read-only lookups used to verify that a label
    # selector actually scopes to the resource the operator picked, and not
    # to sibling Deployments that happen to share some of the same labels.
    # They never change existing selector behaviour on their own — callers
    # decide what to do with the results.

    def get_owned_pod_names(self, context, namespace, deployment):
        """
        Return the pod names actually owned by `deployment`, resolved via
        ownerReferences (Deployment -> ReplicaSet -> Pod) rather than by
        label matching. This is ground truth, immune to label collisions
        between sibling Deployments.
        """
        rs_json = _kubectl_json(
            ["kubectl", "get", "replicasets", "-n", namespace], context=context)
        if not rs_json:
            return []
        owned_rs_names = set()
        for rs in rs_json.get("items", []):
            for owner in rs.get("metadata", {}).get("ownerReferences", []) or []:
                if owner.get("kind") == "Deployment" and owner.get("name") == deployment:
                    owned_rs_names.add(rs["metadata"]["name"])

        if not owned_rs_names:
            return []

        pod_json = _kubectl_json(
            ["kubectl", "get", "pods", "-n", namespace], context=context)
        if not pod_json:
            return []
        owned_pods = []
        for pod in pod_json.get("items", []):
            for owner in pod.get("metadata", {}).get("ownerReferences", []) or []:
                if owner.get("kind") == "ReplicaSet" and owner.get("name") in owned_rs_names:
                    owned_pods.append(pod["metadata"]["name"])
        return owned_pods

    def get_deployment_for_pod(self, context, namespace, pod_name):
        """
        Walk pod -> ReplicaSet -> Deployment ownership to find the Deployment
        that owns a given pod. Returns None if the pod isn't Deployment-managed.
        """
        pod_json = _kubectl_json(
            ["kubectl", "get", "pod", pod_name, "-n", namespace], context=context)
        if not pod_json:
            return None
        rs_name = None
        for owner in pod_json.get("metadata", {}).get("ownerReferences", []) or []:
            if owner.get("kind") == "ReplicaSet":
                rs_name = owner.get("name")
                break
        if not rs_name:
            return None

        rs_json = _kubectl_json(
            ["kubectl", "get", "replicaset", rs_name, "-n", namespace], context=context)
        if not rs_json:
            return None
        for owner in rs_json.get("metadata", {}).get("ownerReferences", []) or []:
            if owner.get("kind") == "Deployment":
                return owner.get("name")
        return None

    def get_safe_label_selector(self, context, namespace, deployment):
        """
        Build a label selector that uniquely scopes to `deployment`'s own pods,
        even when its Deployment-level matchLabels are shared with sibling
        Deployments. Reads spec.template.metadata.labels directly — the full
        label set Kubernetes actually stamps onto every live pod for this
        Deployment — and layers any labels not already in matchLabels on top
        (e.g. Helm-added differentiators like app.kubernetes.io/role=helper
        vs role=gateway).

        Also layers in pod-template-hash from the Deployment's currently
        active ReplicaSet when resolvable. This is the strongest available
        differentiator: it's computed by the ReplicaSet controller from the
        exact pod template content, so it can't collide between two
        different Deployments even when every author-provided label
        (matchLabels AND spec.template.metadata.labels) is identical — e.g.
        a canary/duplicate Deployment copied from the same manifest with no
        distinguishing labels added. Best-effort: if it can't be resolved,
        the author-provided labels above are returned unchanged.

        Volatile config-checksum labels (checksum/...) are excluded since
        they can differ across pods mid-rollout and would make the selector
        match zero pods rather than over-match.

        Returns a dict of {label_key: label_val, ...}, or None if it can't
        be resolved.
        """
        dep_json = _kubectl_json(
            ["kubectl", "get", "deployment", deployment, "-n", namespace], context=context)
        if not dep_json:
            return None
        match_labels = dep_json.get("spec", {}).get("selector", {}).get("matchLabels", {}) or {}
        if not match_labels:
            return None

        template_labels = dep_json.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {}) or {}

        selector = dict(match_labels)
        for key, val in template_labels.items():
            if key in selector or key.startswith("checksum/"):
                continue
            selector[key] = val

        try:
            rs_json = _kubectl_json(
                ["kubectl", "get", "replicasets", "-n", namespace], context=context)
            if rs_json:
                candidates = []
                for rs in rs_json.get("items", []):
                    for owner in rs.get("metadata", {}).get("ownerReferences", []) or []:
                        if owner.get("kind") == "Deployment" and owner.get("name") == deployment:
                            candidates.append(rs)
                            break
                # There should be exactly one owned ReplicaSet outside of an
                # in-progress rollout. Prefer the currently scaled-up one
                # (spec.replicas > 0); if several qualify (mid-rollout), or
                # none report replicas > 0, fall back to the most recently
                # created candidate.
                active = [rs for rs in candidates if (rs.get("spec", {}).get("replicas") or 0) > 0]
                pool = active or candidates
                if pool:
                    newest = max(
                        pool,
                        key=lambda rs: rs.get("metadata", {}).get("creationTimestamp", ""),
                    )
                    pod_template_hash = newest.get("metadata", {}).get("labels", {}).get("pod-template-hash")
                    if pod_template_hash:
                        selector["pod-template-hash"] = pod_template_hash
        except Exception:
            pass  # best-effort — author-provided labels above still apply

        return selector
