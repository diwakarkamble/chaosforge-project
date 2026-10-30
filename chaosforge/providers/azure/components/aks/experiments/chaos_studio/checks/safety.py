"""
AKS Pre-flight Safety Checks

Called at the start of every AKS chaos action (setup_studio) before any fault
is injected. Every function raises RuntimeError with an operator-facing
message on failure, which aborts the ChaosToolkit run before it does damage.

Uses the Kubernetes Python client (via the shared services.k8s_client
dispatcher, routed through this file's own _kubectl() helper) as the
primary transport for every check, with real kubectl subprocess calls kept
only as an automatic fallback if the dispatcher doesn't recognise a call
shape or raises — never as the first attempt. This is the same pattern
used consistently across services/azure_discovery.py and
actions/azure_aks_actions.py for multi-context AKS support.
"""

import datetime as _dt
import json
import time

from rich.console import Console

from . import (
    _safety_basic,
    _safety_fault_network,
    _safety_post_network_corruption_duplication_partition,
    _safety_post_network_delay_loss_bandwidth,
    _safety_pre_network_corruption_duplication_partition,
    _safety_pre_network_delay_loss_bandwidth,
    _safety_runner,
    _safety_selector,
)

_console = Console()

PROTECTED_NAMESPACES = _safety_basic.PROTECTED_NAMESPACES


def _is_true(value):
    return _safety_basic.is_true(value)


def check_protected_namespace(namespace):
    return _safety_basic.check_protected_namespace(namespace)


def check_deployment_replica_floor(context, namespace, deployment, min_replicas=2, owning_deployment=""):
    """
    Refuse to run if the target has fewer ready replicas than min_replicas.
    A single-replica deployment has no redundancy — pod/container kill = outage.

    "deployment" may also be the name of a standalone Pod (the "By Pod" target
    mode reuses this field) — falls back to treating it as a single-instance
    target (desired=ready=1 when Running/Ready) rather than failing with a
    misleading "deployment not found" error.

    owning_deployment is an optional additional fallback: if the named pod is
    no longer found at all (e.g. after Pod Kill legitimately terminated it and
    Kubernetes rescheduled a differently-named replacement), retry against the
    pod's owning Deployment — resolved earlier, while the pod still existed —
    instead of reporting a false "not found" for a target that was *supposed*
    to disappear.
    """
    return _safety_basic.check_deployment_replica_floor(context, namespace, deployment, min_replicas, owning_deployment, _kubectl)


def check_pdb_allows_disruption(context, namespace, label_key, label_val):
    """
    Refuse to run if a PodDisruptionBudget covering the target labels currently
    allows zero disruptions. If no PDB matches, the check passes.
    """
    return _safety_basic.check_pdb_allows_disruption(context, namespace, label_key, label_val, _kubectl)


def check_chaos_mesh_running(context, chaos_mesh_namespace="chaos-testing"):
    """
    Verify the Chaos Mesh controller-manager pod is Running and Ready.
    Required for every experiment delivered through Chaos Mesh via Azure Chaos
    Studio — if Chaos Mesh is unhealthy, Azure reports "Succeeded" while no
    fault is actually injected.
    """

    return _safety_basic.check_chaos_mesh_running(context, chaos_mesh_namespace, _kubectl)


def check_nodes_ready(context, min_ready=1):
    """
    Verify at least min_ready worker nodes are in Ready state.
    Used as a cluster-level steady-state check for node/network experiments
    that have no specific deployment target.
    """
    return _safety_basic.check_nodes_ready(context, min_ready, _kubectl)


def check_system_pods_running(context):
    """
    Verify CoreDNS pods in kube-system are Running.  kube-proxy is checked but
    treated as a warning only — many AKS clusters do not expose kube-proxy as
    visible pods (e.g. when using Azure CNI overlay or kube-proxy-free mode).
    """
    return _safety_basic.check_system_pods_running(context, _kubectl)


def _get_pods_for_deployment(context, namespace, deployment, owning_deployment=""):
    """Return list of raw pod dicts for a deployment (via label selector) or a
    single pod.

    owning_deployment is an optional fallback for "By Pod" target mode: if
    `deployment` is actually a specific pod name that no longer exists (e.g.
    Pod Kill legitimately terminated it and Kubernetes rescheduled a
    differently-named replacement), retry against the pod's owning
    Deployment instead of reporting "not found" for a target that was
    *supposed* to disappear."""
    return _safety_basic.get_pods_for_deployment(context, namespace, deployment, owning_deployment, _kubectl)



def _snapshot_pod_health(pods):
    """Return {pod_name: {ready, phase, container_state, waiting_reason, restarts}} for each pod."""
    return _safety_basic.snapshot_pod_health(pods)


def check_app_stability(context, namespace, deployment, stability_secs=30, owning_deployment=""):
    """
    Steady-state health check that detects active instability, not historical restarts.

    owning_deployment is an optional fallback for "By Pod" target mode — see
    _get_pods_for_deployment().

    Returns (healthy: bool, detail: str).
    Prints a formatted PRE-CHAOS HEALTH CHECK block to the terminal.
    """
    return _safety_basic.check_app_stability(context, namespace, deployment, stability_secs, owning_deployment, _get_pods_for_deployment, _snapshot_pod_health, _console, time.sleep)


def probe_aks_target_healthy(aks_context, namespace="", deployment="", owning_deployment=""):
    """
    Steady-state probe: returns True/False, used by ChaosToolkit's
    steady-state-hypothesis before AND after the experiment runs.

    - Deployment/pod experiments: verify the target has at least one Ready replica,
      then run a stability-aware health check that detects active instability
      (not historical restarts).
    - Node/network/cluster experiments (no namespace+deployment): verify cluster
      infrastructure is healthy — at least one worker node Ready and CoreDNS/kube-proxy
      running.

    owning_deployment: for "By Pod" target mode, the pod's owning Deployment
    name (resolved during pre-checks, while the pod still existed). If the
    named pod itself is legitimately gone after the fault (e.g. Pod Kill
    terminated it and Kubernetes rescheduled a differently-named
    replacement), the checks below fall back to it instead of reporting a
    false "target not found" — this is the whole point of Pod Kill, not a
    steady-state deviation.
    """
    return _safety_basic.probe_aks_target_healthy(aks_context, namespace, deployment, owning_deployment, check_deployment_replica_floor, check_app_stability, check_nodes_ready, check_system_pods_running)


def verify_rollback_health(aks_context, namespace="", deployment="", dry_run="false", owning_deployment="", experiment_id=""):
    """
    Post-rollback verification: re-checks the target's health AFTER cleanup has
    run, so a rollback that completes "successfully" but leaves the target
    unhealthy is caught, instead of the experiment being reported as a clean
    success just because chaostoolkit's cleanup step didn't raise.
    """
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor import (
        _load_state,
    )

    if experiment_id and not _load_state(experiment_id):
        print("[verify-rollback] Setup did not complete; rollback health check skipped.")
        return True
    return _safety_basic.verify_rollback_health(aks_context, namespace, deployment, dry_run, owning_deployment, _is_true, check_app_stability, check_nodes_ready, check_system_pods_running)


# ── Parallel steady-state validation ────────────────────────────────────────

_KUBECTL_TIMEOUT = "15s"   # --request-timeout passed to every kubectl call
_PROC_TIMEOUT   = 20       # subprocess.run hard timeout (seconds)

# Tracks whether the in-fault DNS probe has ever observed chaos actually
# working during the current run. Once injection has been confirmed, a later
# poll that sees DNS resolving again means the fault RECOVERED (the duration
# elapsed and Chaos Mesh sent CancelDNSChaos) — not that injection failed.
# Without this the monitor emits a misleading "chaos NOT yet effective"
# WARNING on the trailing poll tick after every successful experiment.
_DNS_CHAOS_EVER_OBSERVED: "set[str]" = set()
# Last-seen DNSChaos uid per target, used to detect a new run and reset above.
_DNS_CHAOS_LAST_UID: "dict[str, str]" = {}


def _kubectl(*args, context=None, timeout=None):
    """
    Run a kubectl-equivalent command. Returns a CompletedProcess-compatible
    result (returncode/stdout/stderr).

    Every call first tries services.k8s_client.dispatch_kubectl(), which
    serves recognised get/exec/delete patterns via the Kubernetes Python
    client (an isolated ApiClient per context — see k8s_client.py's module
    docstring for the multi-context-safety rationale). Anything the
    dispatcher doesn't recognise (or that errors) falls straight back to the
    original kubectl subprocess call below, so no call site's behaviour can
    regress: it either gets served the identical way as before, or gets
    served by the Python client with equivalent output.
    """
    from chaosforge.providers.azure.components.aks.kubernetes import (
        run_kubernetes_command,
    )

    return run_kubernetes_command(
        args,
        context,
        timeout=timeout or _PROC_TIMEOUT,
        request_timeout=_KUBECTL_TIMEOUT,
        prefix_options=True,
    )


# Proof-of-concept scope: only these two experiment IDs are routed through the
# Kubernetes Python client (services/k8s_client.py). Every other experiment
# type keeps using the existing _kubectl() subprocess pattern untouched.
_PYTHON_CLIENT_EXPERIMENTS = frozenset({"aks-pod-kill", "aks-pod-failure"})


def _list_pods(namespace, selector, aks_context, experiment_id="", field_selector=""):
    """
    List pods, transparently using the Kubernetes Python client for
    _PYTHON_CLIENT_EXPERIMENTS and the existing kubectl subprocess path for
    everything else. Returns (pods: list | None, error: str | None) — pods
    are dicts shaped exactly like `kubectl get pods -o json` .items so
    existing camelCase parsing (status.phase, status.containerStatuses, ...)
    works unchanged either way.
    """
    if experiment_id in _PYTHON_CLIENT_EXPERIMENTS:
        from chaosforge.providers.azure.components.aks.kubernetes import get_pods
        return get_pods(
            aks_context, namespace,
            label_selector=selector if not field_selector else "",
            field_selector=field_selector,
        )

    args = ["get", "pods", "-n", namespace]
    args += ["--field-selector", field_selector] if field_selector else ["-l", selector]
    args += ["-o", "json"]
    r = _kubectl(*args, context=aks_context)
    if r.returncode != 0:
        return None, f"kubectl get pods failed: {r.stderr.strip()}"
    try:
        return json.loads(r.stdout).get("items", []), None
    except ValueError as exc:
        return None, f"Could not parse pods: {exc}"


def _find_svc_name(namespace, label_key, label_val, fallback, aks_context):
    """
    Find the Service whose spec.selector matches label_key=label_val.
    Returns (svc_name: str, found: bool).

    Strategy:
      1. List all services as JSON and match on spec.selector — most correct.
      2. Try label_val directly as a service name — common convention.
      3. Return (fallback, False) — caller should skip endpoint check gracefully.
    """
    r = _kubectl("get", "service", "-n", namespace, "-o", "json", context=aks_context)
    if r.returncode == 0 and label_key and label_val:
        try:
            for svc in json.loads(r.stdout).get("items", []):
                if (svc.get("spec", {}).get("selector") or {}).get(label_key) == label_val:
                    return svc.get("metadata", {}).get("name", ""), True
        except ValueError:
            pass
    # Try label_val as the service name (common naming convention)
    if label_val:
        r2 = _kubectl("get", "service", label_val, "-n", namespace, context=aks_context)
        if r2.returncode == 0:
            return label_val, True
    return fallback, False


def _label_selector_matches(selector: dict, labels: dict) -> bool:
    """Return whether Kubernetes matchLabels/matchExpressions select these labels."""
    if any(labels.get(key) != value for key, value in (selector.get("matchLabels") or {}).items()):
        return False
    for expression in selector.get("matchExpressions") or []:
        key = expression.get("key", "")
        operator = expression.get("operator", "")
        values = expression.get("values") or []
        present = key in labels
        if operator == "In" and (not present or labels[key] not in values):
            return False
        if operator == "NotIn" and (not present or labels[key] in values):
            return False
        if operator == "Exists" and not present:
            return False
        if operator == "DoesNotExist" and present:
            return False
    return True


def _np_partition_ping_target(aks_context: str) -> str:
    """
    Resolve a ping target that will actually answer ICMP inside the cluster,
    for use ONLY by the network-partition pre/post connectivity checks.

    The previous implementation pinged the kube-dns Service's ClusterIP.
    A ClusterIP is a virtual address realized purely as kube-proxy
    DNAT/iptables (or IPVS) rules scoped to the ports the Service declares
    (UDP/TCP 53 for kube-dns) — there is no rule for ICMP echo, so pinging
    it always reports 100% loss / no RTT on essentially any AKS cluster,
    regardless of real cluster health. That produced a permanent false
    failure, unrelated to the partition fault itself.

    Ping the CoreDNS pod's real IP instead — a real pod IP responds to
    ICMP normally. Falls back to the ClusterIP (old behavior) only if the
    pod IP can't be resolved, so the check still runs rather than erroring.
    """
    r_pod_ip = _kubectl(
        "get", "pods", "-n", "kube-system", "-l", "k8s-app=kube-dns",
        "-o", "jsonpath={.items[0].status.podIP}", context=aks_context,
    )
    pod_ip = r_pod_ip.stdout.strip() if r_pod_ip.returncode == 0 else ""
    if pod_ip:
        return pod_ip
    r_cluster_ip = _kubectl(
        "get", "service", "kube-dns", "-n", "kube-system",
        "-o", "jsonpath={.spec.clusterIP}", context=aks_context,
    )
    return r_cluster_ip.stdout.strip() if r_cluster_ip.returncode == 0 and r_cluster_ip.stdout.strip() else "10.0.0.10"


def build_steady_state_checks(
    aks_context: str,
    namespace: str = "",
    deployment: str = "",
    label_key: str = "",
    label_val: str = "",
    experiment_id: str = "",
    container_name: str = "",
    dns_pattern: str = "",
    time_offset: str = "+5m",
    http_port: str = "80",
    injected_delay: str = "5s",
    target_mode: str = "",
    exact_pod_name: str = "",
    volume_path: str = "/data",
) -> "dict[str, callable]":
    """
    Build the full dict of {label: fn} checks for a given target.

    Each fn returns (passed: bool, detail: str) where detail is a verbose
    human-readable description of exactly what was queried and what was found.

    Used by ValidationSession.run_checks() to run all checks in parallel and
    stream results as they arrive.
    """
    checks = {}

    # Function-scope selector used by all experiment-specific check closures below.
    # The POD_CHAOS block also sets this (same value) — that's harmless redundancy.
    selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"
    network_targeting = experiment_id in (
        _NETWORK_DELAY_IDS | _PACKET_LOSS_IDS | _BANDWIDTH_LIMIT_IDS
        | _PACKET_CORRUPTION_IDS | _PACKET_DUPLICATION_IDS | _PARTITION_IDS
    )
    target_selection_args = (
        ["--field-selector", f"metadata.name={exact_pod_name}"]
        if target_mode == "pod" and exact_pod_name
        else ["-l", selector]
    )
    target_selection_display = " ".join(target_selection_args)
    def _service_fqdn():
        service_name, found = _find_svc_name(
            namespace, label_key, label_val, deployment, aks_context
        )
        if not found:
            return "", (
                f"No Service found for selector {label_key}={label_val} "
                f"in '{namespace}'"
            )
        return f"{service_name}.{namespace}.svc.cluster.local", ""

    # Always verify nodes
    def _nodes_ready():
        r = _kubectl("get", "nodes", "-o", "json", context=aks_context)
        if r.returncode != 0:
            return False, f"kubectl get nodes failed: {r.stderr.strip()}"
        try:
            nodes = json.loads(r.stdout).get("items", [])
        except ValueError as exc:
            return False, f"Could not parse node list: {exc}"

        ready, not_ready, control_plane = [], [], []
        for node in nodes:
            name   = node.get("metadata", {}).get("name", "?")
            taints = {t.get("key", "") for t in (node.get("spec", {}).get("taints") or [])}
            if "node-role.kubernetes.io/control-plane" in taints or \
               "node-role.kubernetes.io/master" in taints:
                control_plane.append(name)
                continue
            conditions = node.get("status", {}).get("conditions", [])
            if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
                ready.append(name)
            else:
                not_ready.append(name)

        detail = (
            f"context={aks_context}  "
            f"worker nodes ready={len(ready)}  not-ready={len(not_ready)}  "
            f"control-plane={len(control_plane)}"
        )
        if ready:
            detail += f"\n  Ready: {', '.join(ready)}"
        if not_ready:
            detail += f"\n  NOT Ready: {', '.join(not_ready)}"
        if not ready:
            return False, detail
        return True, detail
    checks["Nodes Ready"] = _nodes_ready

    # Always verify system pods
    def _system_pods():
        # AKS uses component=kube-proxy; upstream clusters use k8s-app=kube-proxy.
        # Try the primary label first; fall back to the AKS label when 0 pods match.
        component_labels = [
            ("CoreDNS",     ["k8s-app=kube-dns"]),
            ("kube-proxy",  ["k8s-app=kube-proxy", "component=kube-proxy"]),
        ]

        def _query_pods(label):
            r = _kubectl("get", "pods", "-n", "kube-system", "-l", label, "-o", "json",
                         context=aks_context)
            if r.returncode != 0:
                return None, r.stderr.strip()
            try:
                return json.loads(r.stdout).get("items", []), None
            except ValueError:
                return [], None

        lines = []
        failed = []
        for component, labels in component_labels:
            pods, err = None, None
            matched_label = labels[0]
            for lbl in labels:
                pods, err = _query_pods(lbl)
                if pods is None:
                    continue          # kubectl error — try next label
                if pods:
                    matched_label = lbl
                    break             # found pods with this label
                matched_label = lbl   # keep track even if empty

            if pods is None:
                failed.append(component)
                lines.append(f"  {component}: kubectl query failed — {err}")
                continue

            running = [
                p.get("metadata", {}).get("name", "?") for p in pods
                if p.get("status", {}).get("phase") == "Running"
                and any(c.get("type") == "Ready" and c.get("status") == "True"
                        for c in p.get("status", {}).get("conditions", []))
            ]
            all_names = [p.get("metadata", {}).get("name", "?") for p in pods]
            status = "Ready" if running else "NOT Ready"
            lines.append(
                f"  {component} (kube-system, label={matched_label}): "
                f"{len(running)}/{len(all_names)} pods {status}"
                + (f"  [{', '.join(running)}]" if running else f"  [found: {all_names}]")
            )
            if not running:
                failed.append(component)

        detail = f"context={aks_context}\n" + "\n".join(lines)
        return (len(failed) == 0), detail
    checks["System Pods (CoreDNS, kube-proxy)"] = _system_pods

    # Deployment/pod target checks — only when a namespace+deployment is given
    if namespace and deployment:
        def _replica_floor():
            r = _kubectl("get", "deployment", deployment, "-n", namespace, "-o", "json",
                         context=aks_context)
            if r.returncode == 0:
                try:
                    dep     = json.loads(r.stdout)
                    desired = dep.get("spec", {}).get("replicas") or 0
                    ready   = dep.get("status", {}).get("readyReplicas") or 0
                    available = dep.get("status", {}).get("availableReplicas") or 0
                    detail  = (
                        f"kubectl get deployment {deployment} -n {namespace} "
                        f"--context {aks_context}\n"
                        f"  desired={desired}  ready={ready}  available={available}"
                    )
                    if ready < 1:
                        return False, detail + "\n  ✘ 0 ready replicas — unsafe to proceed"
                    return True, detail
                except ValueError as exc:
                    return False, f"Could not parse deployment JSON: {exc}"
            else:
                # Try as a pod
                rp = _kubectl("get", "pod", deployment, "-n", namespace, "-o", "json",
                              context=aks_context)
                if rp.returncode != 0:
                    return False, (
                        f"No Deployment or Pod named '{deployment}' in namespace '{namespace}' "
                        f"(context={aks_context})"
                    )
                try:
                    pod    = json.loads(rp.stdout)
                    phase  = pod.get("status", {}).get("phase", "Unknown")
                    conds  = pod.get("status", {}).get("conditions", [])
                    is_rdy = any(c.get("type") == "Ready" and c.get("status") == "True"
                                 for c in conds)
                    detail = (
                        f"kubectl get pod {deployment} -n {namespace} "
                        f"--context {aks_context}\n"
                        f"  phase={phase}  ready={is_rdy}"
                    )
                    return (phase == "Running" and is_rdy), detail
                except ValueError as exc:
                    return False, f"Could not parse pod JSON: {exc}"
        checks[f"Replica Floor ({deployment})"] = _replica_floor

        if label_key and label_val:
            def _pdb():
                target_pod_labels = []
                if network_targeting:
                    target_pods = _kubectl(
                        "get", "pods", "-n", namespace, *target_selection_args,
                        "-o", "json", context=aks_context,
                    )
                    if target_pods.returncode != 0:
                        return True, (
                            f"kubectl get pods -n {namespace} {target_selection_display} "
                            f"--context {aks_context}\n"
                            "  Could not determine target pod labels — skipping PDB check"
                        )
                    try:
                        target_pod_labels = [
                            pod.get("metadata", {}).get("labels") or {}
                            for pod in json.loads(target_pods.stdout).get("items", [])
                        ]
                    except ValueError:
                        return True, "Could not parse target pod labels — skipping PDB check"

                r = _kubectl("get", "pdb", "-n", namespace, "-o", "json",
                             context=aks_context)
                if r.returncode != 0:
                    return True, (
                        f"kubectl get pdb -n {namespace} --context {aks_context}\n"
                        f"  No PDB API available or no PDBs — proceeding"
                    )
                try:
                    pdbs = json.loads(r.stdout).get("items", [])
                except ValueError:
                    return True, "Could not parse PDB list — proceeding"

                matching = []
                for pdb in pdbs:
                    pdb_selector = pdb.get("spec", {}).get("selector") or {}
                    ml = pdb_selector.get("matchLabels") or {}
                    if not network_targeting and ml.get(label_key) != label_val:
                        continue
                    if network_targeting and not any(
                        _label_selector_matches(pdb_selector, labels)
                        for labels in target_pod_labels
                    ):
                        continue
                    st      = pdb.get("status", {})
                    allowed = st.get("disruptionsAllowed")
                    name    = pdb.get("metadata", {}).get("name", "?")
                    matching.append(
                        f"  PDB '{name}': disruptionsAllowed={allowed}  "
                        f"currentHealthy={st.get('currentHealthy')}  "
                        f"desiredHealthy={st.get('desiredHealthy')}"
                    )
                    if allowed is not None and allowed < 1:
                        detail = (
                            f"kubectl get pdb -n {namespace} --context {aks_context}  "
                            f"(selector {label_key}={label_val})\n"
                            + "\n".join(matching)
                        )
                        return False, detail

                if not matching:
                    detail = (
                        f"kubectl get pdb -n {namespace} --context {aks_context}  "
                        f"(selector {label_key}={label_val})\n"
                        f"  No matching PDB found — no disruption budget constraint"
                    )
                else:
                    detail = (
                        f"kubectl get pdb -n {namespace} --context {aks_context}  "
                        f"(selector {label_key}={label_val})\n"
                        + "\n".join(matching)
                    )
                return True, detail
            checks["PodDisruptionBudget"] = _pdb

    # ── Experiment-specific pre-checks ──────────────────────────────────────
    _POD_CHAOS    = {"aks-pod-kill", "aks-pod-failure", "aks-container-kill", "aks-crashloop"}
    _STRESS_CHAOS = {"aks-cpu-stress", "aks-memory-stress"}

    if experiment_id in (_POD_CHAOS | _STRESS_CHAOS) and namespace and (label_key and label_val):
        selector = f"{label_key}={label_val}"

        def _list_pods_desc():
            return (
                f"Kubernetes Python client: list_namespaced_pod(namespace={namespace}, label_selector={selector}, context={aks_context})"
                if experiment_id in _PYTHON_CLIENT_EXPERIMENTS
                else f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}"
            )

        def _pod_count():
            pods, err = _list_pods(namespace, selector, aks_context, experiment_id)
            if pods is None:
                return False, err
            running_ready = [
                p.get("metadata", {}).get("name", "?") for p in pods
                if p.get("status", {}).get("phase") == "Running"
                and any(c.get("type") == "Ready" and c.get("status") == "True"
                        for c in p.get("status", {}).get("conditions", []))
            ]
            all_names = [p.get("metadata", {}).get("name", "?") for p in pods]
            detail = (
                f"{_list_pods_desc()}\n"
                f"  total={len(all_names)}  running+ready={len(running_ready)}"
                + (f"  [{', '.join(running_ready)}]" if running_ready else "")
            )
            if not running_ready:
                return False, detail + "\n  ✘ No Running+Ready pods — nothing to inject into"
            return True, detail
        checks["Pod Count (pre-fault)"] = _pod_count

        if experiment_id in _POD_CHAOS:
            def _restart_stability():
                pods, _err = _list_pods(namespace, selector, aks_context, experiment_id)
                if pods is None:
                    return True, "Could not query pods — skipping restart check"

                # T0 snapshot: key = "pod/container", value = restart count
                snap0 = {}
                crashloop = []
                for pod in pods:
                    pname = pod.get("metadata", {}).get("name", "?")
                    for cs in pod.get("status", {}).get("containerStatuses", []):
                        key = f"{pname}/{cs.get('name', '?')}"
                        snap0[key] = cs.get("restartCount", 0)
                        if cs.get("state", {}).get("waiting", {}).get("reason") == "CrashLoopBackOff":
                            crashloop.append(key)

                if crashloop:
                    detail = (
                        f"{_list_pods_desc()}\n"
                        f"  CrashLoopBackOff: {crashloop}"
                    )
                    return False, detail + "\n  ✘ Pods in CrashLoopBackOff — unsafe to inject"

                has_restarts = any(v > 0 for v in snap0.values())
                if not has_restarts:
                    detail = (
                        f"{_list_pods_desc()}\n"
                        f"  containers with restarts > 0: none"
                    )
                    return True, detail

                # Restarts exist — check stability over 30s before deciding
                time.sleep(30)
                pods2, _err2 = _list_pods(namespace, selector, aks_context, experiment_id)
                snap1 = snap0
                if pods2 is not None:
                    snap1 = {}
                    for pod in pods2:
                        pname = pod.get("metadata", {}).get("name", "?")
                        for cs in pod.get("status", {}).get("containerStatuses", []):
                            key = f"{pname}/{cs.get('name', '?')}"
                            snap1[key] = cs.get("restartCount", 0)

                increasing = {k: (snap0[k], snap1.get(k, snap0[k]))
                              for k in snap0 if snap1.get(k, snap0[k]) > snap0[k]}
                t0_total = sum(snap0.values())
                t1_total = sum(snap1.get(k, v) for k, v in snap0.items())
                detail = (
                    f"{_list_pods_desc()}\n"
                    f"  containers with restarts > 0: {[k for k, v in snap0.items() if v > 0]}\n"
                    f"  restart counts: T0={t0_total}  T1={t1_total}  "
                    f"{'INCREASING' if increasing else 'STABLE'}"
                )
                if increasing:
                    inc_desc = [f"{k}({v[0]}→{v[1]})" for k, v in increasing.items()]
                    return False, detail + f"\n  ✘ Restarts increasing — actively crashing: {inc_desc}"
                return True, detail + "\n  ✔ Restarts stable (historical, not actively crashing)"
            checks["Restart Stability"] = _restart_stability

            if experiment_id in {"aks-container-kill", "aks-crashloop"} and container_name:
                _cname = container_name

                def _container_exists():
                    r = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                                 context=aks_context)
                    if r.returncode != 0:
                        return False, f"kubectl get pods failed: {r.stderr.strip()}"
                    try:
                        pods = json.loads(r.stdout).get("items", [])
                    except ValueError:
                        return False, "Could not parse pods"
                    found_in = []
                    for pod in pods:
                        containers = [c.get("name") for c in pod.get("spec", {}).get("containers", [])]
                        if _cname in containers:
                            found_in.append(pod.get("metadata", {}).get("name", "?"))
                    detail = (
                        f"container '{_cname}' in pods matching {selector} -n {namespace}\n"
                        f"  found in: {found_in if found_in else 'NONE'}"
                    )
                    if not found_in:
                        return False, detail + f"\n  ✘ Container '{_cname}' not found — check container_name param"
                    return True, detail
                checks[f"Container Exists ({_cname})"] = _container_exists

        if experiment_id in _STRESS_CHAOS:
            def _no_oomkilled():
                r = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                             context=aks_context)
                if r.returncode != 0:
                    return True, "Could not query pods — skipping OOMKilled check"
                try:
                    pods = json.loads(r.stdout).get("items", [])
                except ValueError:
                    return True, "Could not parse pods — skipping OOMKilled check"
                oom = []
                for pod in pods:
                    name = pod.get("metadata", {}).get("name", "?")
                    for cs in pod.get("status", {}).get("containerStatuses", []):
                        last = cs.get("lastState", {}).get("terminated", {})
                        if last.get("reason") == "OOMKilled":
                            oom.append(f"{name}/{cs.get('name','?')}")
                detail = (
                    f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
                    f"  OOMKilled containers: {oom if oom else 'none'}"
                )
                if oom:
                    return False, detail + "\n  ✘ Pods recently OOMKilled — unsafe to stress"
                return True, detail
            checks["No OOMKilled Containers"] = _no_oomkilled

        if experiment_id == "aks-cpu-stress":
            def _cpu_resources():
                r = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                             context=aks_context)
                if r.returncode != 0:
                    return True, "Could not query pods — skipping CPU resource check"
                try:
                    pods = json.loads(r.stdout).get("items", [])
                except ValueError:
                    return True, "Could not parse pods — skipping CPU resource check"

                lines = []
                for pod in pods:
                    pod_name = pod.get("metadata", {}).get("name", "?")
                    for c in pod.get("spec", {}).get("containers", []):
                        cname    = c.get("name", "?")
                        res      = c.get("resources", {})
                        req_cpu  = res.get("requests", {}).get("cpu", "not set")
                        lim_cpu  = res.get("limits", {}).get("cpu", "not set")
                        lines.append(
                            f"  {pod_name}/{cname}: "
                            f"requests.cpu={req_cpu}  limits.cpu={lim_cpu}"
                        )
                        if req_cpu == "not set":
                            lines[-1] += "  ⚠ no CPU request"
                        if lim_cpu == "not set":
                            lines[-1] += "  ⚠ no CPU limit (unbounded — stress may saturate node)"

                detail = (
                    f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
                    + ("\n".join(lines) if lines else "  no containers found")
                )
                # Warn but don't block — missing requests/limits is noteworthy, not fatal
                return True, detail
            checks["CPU Requests & Limits"] = _cpu_resources

            def _cpu_top():
                r = _kubectl("top", "pods", "-n", namespace, "-l", selector,
                             "--containers", "--no-headers", context=aks_context)
                if r.returncode != 0 or not r.stdout.strip():
                    return True, (
                        f"kubectl top pods -n {namespace} -l {selector} --containers "
                        f"--context {aks_context}\n  (metrics-server unavailable or no data — skipping)"
                    )
                lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
                detail = (
                    f"kubectl top pods -n {namespace} -l {selector} --containers "
                    f"--context {aks_context}  (CPU baseline)\n"
                    + "\n".join(f"  {l}" for l in lines)
                )
                return True, detail
            checks["CPU Baseline (current usage)"] = _cpu_top

            def _cpu_node_top():
                r_pods = _kubectl("get", "pods", "-n", namespace, "-l", selector,
                                  "-o", "jsonpath={.items[*].spec.nodeName}", context=aks_context)
                node_names = list({n for n in r_pods.stdout.strip().split() if n}) if r_pods.returncode == 0 else []
                if not node_names:
                    return True, "Could not determine node — skipping node CPU check"
                r = _kubectl("top", "nodes", "--no-headers", context=aks_context)
                if r.returncode != 0 or not r.stdout.strip():
                    return True, "kubectl top nodes unavailable — skipping node CPU headroom check"
                lines = []
                for line in r.stdout.strip().splitlines():
                    parts = line.split()
                    if parts and parts[0] in node_names:
                        lines.append(f"  {line.strip()}")
                detail = (
                    f"kubectl top nodes --context {aks_context}  (CPU headroom on target node(s))\n"
                    + ("\n".join(lines) if lines else "  (target node rows not found in output)")
                )
                return True, detail
            checks["CPU Headroom (node)"] = _cpu_node_top

        if experiment_id == "aks-memory-stress":
            def _mem_resources():
                r = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                             context=aks_context)
                if r.returncode != 0:
                    return True, "Could not query pods — skipping memory resource check"
                try:
                    pods = json.loads(r.stdout).get("items", [])
                except ValueError:
                    return True, "Could not parse pods — skipping memory resource check"

                lines = []
                for pod in pods:
                    pod_name = pod.get("metadata", {}).get("name", "?")
                    for c in pod.get("spec", {}).get("containers", []):
                        cname   = c.get("name", "?")
                        res     = c.get("resources", {})
                        req_mem = res.get("requests", {}).get("memory", "not set")
                        lim_mem = res.get("limits", {}).get("memory", "not set")
                        lines.append(
                            f"  {pod_name}/{cname}: "
                            f"requests.memory={req_mem}  limits.memory={lim_mem}"
                        )
                        if req_mem == "not set":
                            lines[-1] += "  ⚠ no memory request"
                        if lim_mem == "not set":
                            lines[-1] += "  ⚠ no memory limit — OOM kill risk is unbounded"

                detail = (
                    f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
                    + ("\n".join(lines) if lines else "  no containers found")
                )
                return True, detail
            checks["Memory Requests & Limits"] = _mem_resources

            def _mem_top():
                r = _kubectl("top", "pods", "-n", namespace, "-l", selector,
                             "--containers", "--no-headers", context=aks_context)
                if r.returncode != 0 or not r.stdout.strip():
                    return True, (
                        f"kubectl top pods -n {namespace} -l {selector} --containers "
                        f"--context {aks_context}\n  (metrics-server unavailable or no data — skipping)"
                    )
                lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
                detail = (
                    f"kubectl top pods -n {namespace} -l {selector} --containers "
                    f"--context {aks_context}  (memory baseline)\n"
                    + "\n".join(f"  {l}" for l in lines)
                )
                return True, detail
            checks["Memory Baseline (current usage)"] = _mem_top

            def _mem_node_top():
                r_pods = _kubectl("get", "pods", "-n", namespace, "-l", selector,
                                  "-o", "jsonpath={.items[*].spec.nodeName}", context=aks_context)
                node_names = list({n for n in r_pods.stdout.strip().split() if n}) if r_pods.returncode == 0 else []
                if not node_names:
                    return True, "Could not determine node — skipping node memory check"
                r = _kubectl("top", "nodes", "--no-headers", context=aks_context)
                if r.returncode != 0 or not r.stdout.strip():
                    return True, "kubectl top nodes unavailable — skipping node memory headroom check"
                lines = []
                for line in r.stdout.strip().splitlines():
                    parts = line.split()
                    if parts and parts[0] in node_names:
                        lines.append(f"  {line.strip()}")
                detail = (
                    f"kubectl top nodes --context {aks_context}  (memory headroom on target node(s))\n"
                    + ("\n".join(lines) if lines else "  (target node rows not found in output)")
                )
                return True, detail
            checks["Memory Headroom (node)"] = _mem_node_top

            def _oom_history():
                r = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                             context=aks_context)
                if r.returncode != 0:
                    return True, "Could not query pods — skipping OOM history check"
                try:
                    pods = json.loads(r.stdout).get("items", [])
                except ValueError:
                    return True, "Could not parse pods — skipping OOM history check"

                lines = []
                has_oom = False
                for pod in pods:
                    pod_name = pod.get("metadata", {}).get("name", "?")
                    for cs in pod.get("status", {}).get("containerStatuses", []):
                        cname = cs.get("name", "?")
                        # current state OOMKilled
                        cur_term = cs.get("state", {}).get("terminated", {})
                        if cur_term.get("reason") == "OOMKilled":
                            lines.append(f"  {pod_name}/{cname}: OOMKilled (current state)")
                            has_oom = True
                        # last state OOMKilled
                        last_term = cs.get("lastState", {}).get("terminated", {})
                        if last_term.get("reason") == "OOMKilled":
                            finished = last_term.get("finishedAt", "unknown time")
                            lines.append(f"  {pod_name}/{cname}: OOMKilled in last state (at {finished})")
                            has_oom = True

                detail = (
                    f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}  "
                    f"(OOM history)\n"
                    + ("\n".join(lines) if lines else "  no OOM history found")
                )
                if has_oom:
                    return False, detail + "\n  ✘ Container(s) have OOM history — memory stress is high risk"
                return True, detail
            checks["OOM History"] = _oom_history

    checks.update(_safety_pre_network_delay_loss_bandwidth.build_pre_network_checks(
        experiment_id, aks_context, namespace, deployment, label_key, label_val,
        target_selection_args, target_selection_display,
        kubectl=lambda: _kubectl, find_svc_name=lambda: _find_svc_name,
    ))
    checks.update(_safety_pre_network_corruption_duplication_partition.build_pre_network_checks(
        experiment_id, aks_context, namespace, deployment, label_key, label_val,
        target_selection_args, target_selection_display,
        kubectl=lambda: _kubectl, find_svc_name=lambda: _find_svc_name,
        partition_ping_target=lambda: _np_partition_ping_target,
    ))

    # ── Extended pre-checks: TimeChaos, HTTPChaos, DNSChaos ──────────────────
    # Delegated to aks_extended_checks.py — imported lazily to avoid circular deps.
    _TIME_CHAOS_IDS = {"aks-clock-skew-forward", "aks-clock-skew-backward"}
    _HTTP_CHAOS_IDS = {"aks-http-delay", "aks-http-abort"}
    _DNS_CHAOS_IDS  = {"aks-dns-failure"}

    if experiment_id in _TIME_CHAOS_IDS and namespace and deployment:
        try:
            from .extended import build_time_chaos_pre_checks
            # time_offset lives in the spec JSON (timeOffset field), not a runtime param.
            # Read it directly from the spec so the pre-check uses the actual configured value.
            _resolved_time_offset = time_offset
            try:
                import json as _json
                import os as _os

                from ..executor import EXPERIMENT_SPECS, SPEC_DIR
                _spec_file = EXPERIMENT_SPECS.get(experiment_id)
                if _spec_file:
                    _spec_path = _os.path.join(SPEC_DIR, _spec_file)
                    with open(_spec_path) as _f:
                        _spec = _json.load(_f)
                    if not time_offset and _spec.get("timeOffset"):
                        _resolved_time_offset = _spec["timeOffset"]
            except Exception:
                pass
            checks.update(build_time_chaos_pre_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
                experiment_id=experiment_id,
                time_offset=_resolved_time_offset,
            ))
        except ImportError:
            pass

    if experiment_id in _HTTP_CHAOS_IDS and namespace and deployment:
        try:
            from .extended import build_http_chaos_pre_checks
            checks.update(build_http_chaos_pre_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
                experiment_id=experiment_id,
                http_port=http_port,
                injected_delay=injected_delay,
            ))
        except ImportError:
            pass

    if experiment_id in _DNS_CHAOS_IDS and namespace and deployment:
        try:
            from .extended import build_dns_chaos_pre_checks
            checks.update(build_dns_chaos_pre_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
                dns_pattern=dns_pattern,
            ))
        except ImportError:
            pass

    # ── Extended pre-checks: IOChaos ──────────────────────────────────────────
    # Self-contained block for aks-io-latency / aks-io-errors only — delegated
    # to build_io_chaos_pre_checks() in aks_extended_checks.py, which is not
    # shared with, and does not call into, any other experiment's checks.
    _IO_CHAOS_IDS = {"aks-io-latency", "aks-io-errors"}
    if experiment_id in _IO_CHAOS_IDS and namespace and deployment:
        try:
            from .extended import build_io_chaos_pre_checks
            checks.update(build_io_chaos_pre_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
                experiment_id=experiment_id,
                volume_path=volume_path,
            ))
        except ImportError:
            pass

    # Cluster-plane experiments (CoreDNS/kube-proxy) target kube-system directly —
    # no app namespace/deployment to gate on, unlike Time/HTTP/DNS chaos above.
    _CLUSTER_PLANE_CHAOS_IDS = {"aks-coredns-kill", "aks-coredns-cpu", "aks-kube-proxy-kill"}
    if experiment_id in _CLUSTER_PLANE_CHAOS_IDS:
        try:
            from .extended import build_cluster_plane_chaos_pre_checks
            checks.update(build_cluster_plane_chaos_pre_checks(
                aks_context, experiment_id,
            ))
        except ImportError:
            pass

    return checks


def run_parallel_steady_state(
    aks_context: str,
    namespace: str = "",
    deployment: str = "",
    label_key: str = "",
    label_val: str = "",
    *,
    phase: str = "validation",
    session=None,
    experiment_id: str = "",
    container_name: str = "",
    dns_pattern: str = "",
    time_offset: str = "+5m",
    http_port: str = "80",
    injected_delay: str = "5s",
    target_mode: str = "",
    exact_pod_name: str = "",
    volume_path: str = "/data",
) -> bool:
    """Run steady-state checks while preserving safety.py monkeypatch seams."""
    from ..validation_logger import ValidationSession

    return _safety_runner.run_parallel_steady_state(
        aks_context, namespace, deployment, label_key, label_val,
        phase=phase, session=session, experiment_id=experiment_id,
        container_name=container_name, dns_pattern=dns_pattern,
        time_offset=time_offset, http_port=http_port,
        injected_delay=injected_delay, target_mode=target_mode,
        exact_pod_name=exact_pod_name, volume_path=volume_path,
        build_checks=build_steady_state_checks,
        validation_session=ValidationSession,
    )


# ── In-fault verification ────────────────────────────────────────────────────

_STRESS_CHAOS_IDS        = frozenset({"aks-cpu-stress", "aks-memory-stress", "aks-coredns-cpu"})
# CoreDNS CPU stress hardcodes its target to kube-system and has no
# app-level namespace/deployment/label context — resolve those from the
# cluster-plane target table below instead of short-circuiting on them being blank.
_CLUSTER_PLANE_STRESS_VISIBLE_IDS = frozenset({"aks-coredns-cpu"})
_NETWORK_DELAY_IDS       = frozenset({"aks-network-delay"})
_PACKET_LOSS_IDS         = frozenset({"aks-packet-loss"})
_BANDWIDTH_LIMIT_IDS     = frozenset({"aks-bandwidth-limit"})
_PACKET_CORRUPTION_IDS   = frozenset({"aks-packet-corruption"})
_PACKET_DUPLICATION_IDS  = frozenset({"aks-packet-duplication"})
_PARTITION_IDS           = frozenset({"aks-network-partition"})


def _annotate_network_result(result, pod_lines, target_pod_names, restart_baseline):
    """Add actual target/control health and truthful restart-delta details."""
    target_names = set(target_pod_names or [])
    pod_ready = {}
    for line in pod_lines:
        parts = line.split()
        if len(parts) < 2 or "/" not in parts[1]:
            continue
        ready, expected = parts[1].split("/", 1)
        pod_ready[parts[0]] = ready == expected

    if target_names:
        targeted = {name: pod_ready[name] for name in target_names if name in pod_ready}
        controls = {name: ready for name, ready in pod_ready.items() if name not in target_names}
        target_ready = sum(targeted.values())
        control_ready = sum(controls.values())
        missing = sorted(target_names - pod_ready.keys())
        result["net_rows"].append(
            ("Targeted pods ready", f"{target_ready} / {len(target_names)}",
             f"actual targets: {', '.join(sorted(target_names))}")
        )
        result["net_rows"].append(
            ("Control pods ready", f"{control_ready} / {len(controls)}",
             "matching pods not selected by Chaos Mesh")
        )
        result["message"] += (
            f" | targeted ready: {target_ready}/{len(target_names)}"
            f" | control ready: {control_ready}/{len(controls)}"
        )
        if missing:
            result["message"] += f" | targeted pod(s) absent: {', '.join(missing)}"

    for index, row in enumerate(result.get("net_rows", [])):
        if row[0] != "Container restarts":
            continue
        try:
            restart_total = int(row[1])
        except (TypeError, ValueError):
            break
        if restart_baseline is None:
            detail = "cumulative count; baseline unavailable"
        else:
            detail = (
                f"baseline={restart_baseline}; "
                f"new during fault={max(0, restart_total - restart_baseline)}"
            )
        result["net_rows"][index] = (row[0], row[1], detail)
        message_parts = [
            part for part in result["message"].split(" | ")
            if not part.startswith("container restarts:")
        ]
        message_parts.append(f"container restarts: {restart_total} ({detail})")
        result["message"] = " | ".join(message_parts)
        break

    return result


def _select_live_probe_pod(pod_lines, target_pod_names):
    available = {
        line.split()[0]
        for line in pod_lines
        if line.split()
    }
    for pod_name in target_pod_names or []:
        if pod_name in available:
            return pod_name
    return pod_lines[0].split()[0] if pod_lines else None


_network_live_probe = _safety_fault_network.build_network_live_probe(
    kubectl=lambda: _kubectl,
    find_svc_name=lambda: _find_svc_name,
    select_live_probe_pod=lambda: _select_live_probe_pod,
    annotate_network_result=lambda: _annotate_network_result,
)


def verify_fault_active(
    experiment_id: str,
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    session=None,
    _seen_killed: set | None = None,
    label_selectors_map: "dict | None" = None,
    target_pod_names: "list | None" = None,
    restart_baseline: "int | None" = None,
    exact_pod_name: str = "",
    volume_path: str = "/data",
):
    """
    Quick in-cluster probe called every poll_interval during the fault window.

    Returns one of:
      - "" (empty string) — no namespace, nothing to report
      - dict with keys {severity, message} — single event line
      - dict with keys {severity, message, pod_rows, node_rows} — stress metrics block

    Never raises — caller wraps in try/except.

    session: optional ValidationSession for disk-level audit logging.
    _seen_killed: caller-owned set used to deduplicate kill events across polls.
    label_selectors_map: optional multi-key selector (from the selector-scope
        validator) that takes priority over label_key/label_val when a naive
        single-label selector would also match sibling Deployments' pods.
    """
    from .event_log import (
        container_kill_status,
        pod_failure_status,
        pod_kill_status,
    )

    if not namespace and experiment_id in _CLUSTER_PLANE_STRESS_VISIBLE_IDS:
        from .extended import _cluster_plane
        namespace = "kube-system"
        label_selectors_map = None
        label_key = label_val = ""
        selector = _cluster_plane._CLUSTER_PLANE_TARGETS.get(experiment_id, {}).get("selector", "")
    elif not namespace:
        return ""
    elif label_selectors_map:
        selector = ",".join(f"{k}={v}" for k, v in label_selectors_map.items())
    else:
        selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"

    selection_args = (
        ["--field-selector", f"metadata.name={exact_pod_name}"]
        if exact_pod_name else ["-l", selector]
    )

    if experiment_id in _PYTHON_CLIENT_EXPERIMENTS:
        from chaosforge.providers.azure.components.aks.kubernetes import get_pods
        field_selector = f"metadata.name={exact_pod_name}" if exact_pod_name else ""
        pods, err = get_pods(
            aks_context, namespace,
            label_selector="" if field_selector else selector,
            field_selector=field_selector,
        )
        if pods is None:
            return {"severity": "WARNING", "message": f"pods: (no data — {err})"}
        total = len(pods)

        if experiment_id == "aks-pod-kill":
            terminating_pods = [
                p.get("metadata", {}).get("name", "?") for p in pods
                if p.get("metadata", {}).get("deletionTimestamp")
            ]
            terminating = len(terminating_pods)
            running = sum(
                1 for p in pods
                if p.get("status", {}).get("phase") == "Running"
                and not p.get("metadata", {}).get("deletionTimestamp")
            )
            if session and _seen_killed is not None:
                for pod_name in terminating_pods:
                    if pod_name not in _seen_killed:
                        _seen_killed.add(pod_name)
                        session.log_event("CHAOS", f"pod/{pod_name} terminated — rescheduling")
            return pod_kill_status(running, total, terminating)

        # aks-pod-failure
        not_ready = sum(
            1 for p in pods
            if sum(1 for cs in p.get("status", {}).get("containerStatuses", []) if cs.get("ready")) == 0
        )
        running = total - not_ready
        return pod_failure_status(running, total, not_ready)

    r = _kubectl("get", "pods", "-n", namespace, *selection_args,
                 "--no-headers", context=aks_context)
    if r.returncode != 0 or not r.stdout.strip():
        return {"severity": "WARNING", "message": "pods: (no data — kubectl unavailable)"}

    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    total = len(lines)

    if experiment_id in {"aks-container-kill", "aks-crashloop"}:
        restarts = []
        for l in lines:
            parts = l.split()
            if len(parts) >= 4:
                name = parts[0]
                rc   = parts[3]
                if rc != "0":
                    restarts.append(f"{name}={rc}")
        return container_kill_status(total, restarts)

    if experiment_id in _STRESS_CHAOS_IDS:
        running = sum(1 for l in lines if len(l.split()) >= 3 and l.split()[2] == "Running")

        # StressChaos CRD AllInjected condition — pod phase alone can't prove
        # stress-ng actually landed (chaos-daemon privilege/capability issues
        # fail silently while the pod stays Running with flat CPU/MEM).
        crd_injected = False
        rc = _kubectl("get", "stresschaos", "-n", "chaos-testing", "-o", "json",
                      context=aks_context)
        if rc.returncode == 0:
            try:
                items = json.loads(rc.stdout).get("items", [])
                for it in items:
                    conds = it.get("status", {}).get("conditions", [])
                    if any(c.get("type") == "AllInjected" and c.get("status") == "True"
                           for c in conds):
                        crd_injected = True
                        break
            except ValueError:
                pass

        summary = (
            f"pods: {running}/{total} Running "
            + ("(stress active)" if crd_injected
               else "(⚠ stress NOT injected — StressChaos AllInjected=False)")
        )
        severity = "INFO" if crd_injected else "WARNING"

        # kubectl top pods --containers → list of (pod, container, cpu, mem)
        pod_rows = []
        rt = _kubectl("top", "pods", "-n", namespace, "-l", selector,
                      "--containers", "--no-headers", context=aks_context)
        if rt.returncode == 0 and rt.stdout.strip():
            for row in rt.stdout.strip().splitlines():
                parts = row.split()
                if len(parts) >= 4:
                    pod_rows.append((parts[0], parts[1], parts[2], parts[3]))

        # kubectl top nodes — only for nodes hosting target pods
        node_rows = []
        rp = _kubectl("get", "pods", "-n", namespace, "-l", selector,
                      "-o", "jsonpath={.items[*].spec.nodeName}", context=aks_context)
        if rp.returncode == 0 and rp.stdout.strip():
            target_nodes = {n for n in rp.stdout.strip().split() if n}
            rn = _kubectl("top", "nodes", "--no-headers", context=aks_context)
            if rn.returncode == 0 and rn.stdout.strip():
                for row in rn.stdout.strip().splitlines():
                    parts = row.split()
                    if len(parts) >= 5 and parts[0] in target_nodes:
                        node_rows.append((parts[0], parts[1], parts[2], parts[3], parts[4]))

        return {"severity": severity, "message": summary, "pod_rows": pod_rows, "node_rows": node_rows}

    network_result = _network_live_probe(
        experiment_id, aks_context, namespace, deployment, label_key, label_val,
        session, selection_args, lines, total, target_pod_names, restart_baseline,
    )
    if network_result is not None:
        return network_result

    # ── IOChaos (aks-io-latency, aks-io-errors) live-fault probe ────────────
    # Self-contained: does not call any helper used by pod/network/stress/DNS
    # branches above or below — dedicated logic for IOChaos only.
    if experiment_id in {"aks-io-latency", "aks-io-errors"}:
        ready_pods = sum(
            1 for l in lines
            if len(l.split()) >= 2 and "/" in l.split()[1]
            and l.split()[1].split("/", 1)[0] == l.split()[1].split("/", 1)[1]
        )

        # IOChaos CRD AllInjected condition
        crd_injected = False
        rc = _kubectl("get", "iochaos", "-n", "chaos-testing", "-o", "json",
                      context=aks_context)
        if rc.returncode == 0:
            try:
                items = json.loads(rc.stdout).get("items", [])
                for it in items:
                    conds = it.get("status", {}).get("conditions", [])
                    if any(c.get("type") == "AllInjected" and c.get("status") == "True"
                           for c in conds):
                        crd_injected = True
                        break
            except ValueError:
                pass

        # Container restart count on target pod(s) — surfaced as informational
        # context (a crash/evict during the fault window is worth noting),
        # not a severity signal. chaos-daemon enters the target container's
        # own namespaces directly (EnterNS=true) to run `toda`, so
        # AllInjected=True on the CRD is the sole real indicator of fault
        # activity — there is no separate sidecar/init-container to verify.
        selector_io = (
            f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"
        )
        rp = _kubectl("get", "pods", "-n", namespace, "-l", selector_io, "-o", "json",
                      context=aks_context)
        restart_total = 0
        pods_io = []
        if rp.returncode == 0:
            try:
                pods_io = json.loads(rp.stdout).get("items", [])
                restart_total = sum(
                    cs.get("restartCount", 0)
                    for p in pods_io
                    for cs in p.get("status", {}).get("containerStatuses", [])
                )
            except ValueError:
                pass

        # Live file I/O round-trip probe — re-run the same write+read+delete
        # probe used pre-fault, every poll, so the operator sees the fault's
        # real-time effect (compare against "Baseline File I/O Timing" in the
        # pre-check logs for the before/after delta).
        io_ms = None
        io_error = None
        _vpath_live = (volume_path or "/data").rstrip("/") or "/"
        pod_name_io = next(
            (p.get("metadata", {}).get("name") for p in pods_io
             if p.get("status", {}).get("phase") == "Running"),
            None,
        )
        if pod_name_io:
            from ._extended_common import _find_writable_probe_location
            _cname, _ppath = _find_writable_probe_location(aks_context, namespace, pod_name_io, _vpath_live)
            _ppath = _ppath or _vpath_live
            _c_args = ("-c", _cname) if _cname else ()
            _probe_file = f"{_ppath}/.chaosforge_io_probe_live"
            import time as _time
            t0 = _time.monotonic()
            rprobe = _kubectl(
                "exec", pod_name_io, "-n", namespace, *_c_args, "--", "sh", "-c",
                f"date +%s%3N > '{_probe_file}' && cat '{_probe_file}' >/dev/null && rm -f '{_probe_file}'",
                context=aks_context,
            )
            io_ms = int((_time.monotonic() - t0) * 1000)
            if rprobe.returncode != 0:
                io_error = (rprobe.stderr or rprobe.stdout or "").strip()[:80]

        status_parts = [
            f"pods: {ready_pods}/{total} Ready",
            "IOChaos AllInjected=True" if crd_injected else "IOChaos: injection pending",
        ]
        if io_error:
            status_parts.append(f"I/O probe FAILED: {io_error}")
        elif io_ms is not None:
            status_parts.append(f"I/O round-trip: {io_ms}ms")
        if restart_total > 0:
            status_parts.append(f"container restarts: {restart_total}")

        severity = "CHAOS" if crd_injected else "WARNING"
        if session:
            session.log_event(severity, " | ".join(status_parts))
        return {
            "severity": severity,
            "message": " | ".join(status_parts),
            "io_ms": io_ms,
            "crd_injected": crd_injected,
        }

    if experiment_id == "aks-dns-failure":
        # In-fault DNS probe: verify the DNSChaos CRD is injected and confirm,
        # from inside an actually-injected pod, whether resolution is failing.

        # ── 1. DNSChaos CRD AllInjected ──────────────────────────────────────
        crd_injected = False
        _chaos_uid = ""
        rd = _kubectl("get", "dnschaos", "-n", "chaos-testing", "-o", "json",
                      context=aks_context)
        if rd.returncode == 0:
            try:
                for item in json.loads(rd.stdout).get("items", []):
                    _chaos_uid = item.get("metadata", {}).get("uid", "") or _chaos_uid
                    for cond in (item.get("status", {}).get("conditions") or []):
                        if cond.get("type") == "AllInjected" and cond.get("status") == "True":
                            crd_injected = True
            except ValueError:
                pass

        # ── 2. Pod readiness ─────────────────────────────────────────────────
        ready_pods = sum(
            1 for l in lines
            if len(l.split()) >= 2 and "/" in l.split()[1]
            and l.split()[1].split("/")[0] == l.split()[1].split("/")[-1]
        )
        not_ready = total - ready_pods

        # ── 3. In-fault resolution probe ─────────────────────────────────────
        # Single resolution per poll tick to stay within the 2s cadence.
        _dns_pattern = ""
        try:
            _dns_pattern_r = _kubectl("get", "dnschaos", "-n", "chaos-testing",
                                     "-o", "jsonpath={.items[0].spec.patterns[0]}",
                                     context=aks_context, timeout=5)
            if _dns_pattern_r.returncode == 0:
                _dns_pattern = _dns_pattern_r.stdout.strip()
        except Exception:
            pass

        # NOTE: we deliberately do NOT report a latency number here. Timing a
        # `kubectl exec` from outside the cluster measures exec/API-server
        # startup (~2500 ms), not DNS resolution (~10 ms), so comparing it to a
        # baseline was pure noise. The only thing that matters in-fault is the
        # binary question: did resolution succeed or fail?
        _resolved = None  # True = still resolving, False = failing (chaos live)

        # A wildcard pattern cannot be resolved literally ('nslookup *' is
        # meaningless), but under a wildcard every name fails — so probe a
        # concrete canary domain instead of skipping the probe entirely.
        # Without this the only in-fault evidence would be the CRD status,
        # which reports AllInjected=True even when nothing is being answered.
        _probe_name = _dns_pattern
        _is_wildcard = "*" in _dns_pattern
        if _is_wildcard:
            _probe_name = "kubernetes.default.svc.cluster.local"

        _chaos_observed = False
        _pod = None
        if _dns_pattern and lines:
            # Probe a pod that Chaos Mesh ACTUALLY injected, not just the first
            # pod in the list. Under mode=one/fixed/percent only a subset of
            # pods are faulted; probing lines[0] would frequently land on a
            # healthy pod, resolve fine, and wrongly report "chaos NOT
            # effective" while the faulted pod next door was blacked out.
            # containerRecords[].id has the form "<ns>/<pod>/<container>".
            _pod = None
            try:
                _rec = _kubectl("get", "dnschaos", "-n", "chaos-testing",
                               "-o", "jsonpath={.items[0].status.experiment.containerRecords[*].id}",
                               context=aks_context, timeout=5)
                if _rec.returncode == 0:
                    _ready = {ln.split()[0] for ln in lines if ln.split()}
                    for _id in _rec.stdout.split():
                        _parts = _id.split("/")
                        if len(_parts) >= 2 and _parts[1] in _ready:
                            _pod = _parts[1]
                            break
            except Exception:
                pass
            # Fall back to the first pod only if the CRD gave us nothing usable
            # (e.g. records not yet populated in the first seconds of the run).
            if _pod is None:
                _pod = lines[0].split()[0] if lines else None
            if _pod:
                _r = _kubectl("exec", _pod, "-n", namespace, "--",
                              "sh", "-c", f"nslookup {_probe_name} 2>&1",
                              context=aks_context)
                _out = (_r.stdout or "") + (_r.stderr or "")
                # A failed `kubectl exec` is NOT evidence of DNS chaos. Distroless
                # images have no `sh`/`nslookup`, so exec never starts and returns
                # non-zero — which would otherwise be misread as "resolution
                # failed", producing a false "chaos injecting" on a pod we never
                # actually probed. Treat these as probe-unavailable instead.
                _probe_unavailable = any(
                    m in _out for m in (
                        "executable file not found",
                        "OCI runtime exec failed",
                        "unable to start container process",
                        "command terminated with exit code 127",
                        "cannot exec in a stopped",
                        "container not found",
                    )
                )
                if _probe_unavailable:
                    _resolved = None  # no signal either way
                elif _r.returncode != 0 or "NXDOMAIN" in _out or "SERVFAIL" in _out:
                    _resolved = False  # resolution failed — chaos is live
                    _chaos_observed = True
                else:
                    _resolved = True

        _run_key = f"{aks_context}/{namespace}/{deployment}"
        # A new DNSChaos uid means a new experiment on the same target — clear
        # any observation carried over from the previous run. The uid is only
        # readable while the CRD exists (it is deleted at teardown), so the
        # target key is what we actually track against.
        if _chaos_uid and _DNS_CHAOS_LAST_UID.get(_run_key) != _chaos_uid:
            _DNS_CHAOS_LAST_UID[_run_key] = _chaos_uid
            _DNS_CHAOS_EVER_OBSERVED.discard(_run_key)
        if _chaos_observed:
            _DNS_CHAOS_EVER_OBSERVED.add(_run_key)
        _was_observed = _run_key in _DNS_CHAOS_EVER_OBSERVED

        # "recovered" only makes sense once chaos has been seen AND is no longer
        # active this tick — otherwise the line contradicts itself, e.g.
        # "DNSChaos: recovered ... chaos injecting ✔".
        _recovered = _was_observed and not _chaos_observed
        status_parts = [
            f"pods: {ready_pods}/{total} Ready",
            "DNSChaos AllInjected=True" if crd_injected
            else ("DNSChaos: recovered" if _recovered else "DNSChaos: injection pending"),
        ]
        if not_ready > 0:
            status_parts.append(f"⚠ {not_ready} pod(s) NotReady — DNS-dependent probes likely failing")
        if _resolved is None and _pod:
            # Probe could not run at all (e.g. distroless image with no shell).
            # Report honestly rather than inferring anything from the failure.
            status_parts.append(
                f"in-pod DNS probe unavailable in {_pod} (no shell/nslookup in image) — "
                "relying on CRD status; verify via chaos-dns-server logs"
            )
        elif _resolved is True:
            _via = f" via canary '{_probe_name}'" if _is_wildcard else ""
            if _was_observed:
                # Chaos ran, then the duration elapsed and the fault was removed.
                # This is the expected end-of-experiment state, not a failure.
                status_parts.append(
                    f"DNS resolving again in pod {_pod}{_via} — fault recovered ✔"
                )
            else:
                status_parts.append(
                    f"DNS still resolving in pod {_pod}{_via} — chaos NOT yet effective"
                )
        elif _chaos_observed:
            _via = f" (canary '{_probe_name}' under wildcard '{_dns_pattern}')" if _is_wildcard else ""
            status_parts.append(
                f"DNS lookup FAILED for {_probe_name}{_via} in pod {_pod} — chaos injecting ✔"
            )

        # Only warn when something is genuinely wrong: pods unhealthy, or chaos
        # is not injected and we have never seen it work. A clean recovery after
        # confirmed injection is CHAOS-level, not WARNING.
        if not_ready > 0:
            severity = "WARNING"
        elif crd_injected or _was_observed:
            severity = "CHAOS"
        else:
            severity = "WARNING"
        if session:
            session.log_event(severity, " | ".join(status_parts))
        return {"severity": severity, "message": " | ".join(status_parts)}

    return {"severity": "INFO", "message": f"pods: {total} found"}


# ── Selector-scope validation ─────────────────────────────────────────────────
# Verifies that the label selector resolved for the operator's chosen target
# (Deployment or Pod) doesn't also match sibling Deployments that happen to
# share some of the same labels — this is what caused container-kill to hit
# 11 pods across two Deployments (gw + hlpr) instead of the 1 the operator
# picked. Additive/read-only: when there's no collision (the common case),
# this changes nothing and the existing single-label selector is used as-is.

def validate_and_resolve_selector(
    aks_context: str,
    namespace: str,
    deployment: str,
    target_mode: str,
    label_key: str = "",
    label_val: str = "",
    *,
    ui=None,
    session=None,
    exact_pod_targeting=False,
):
    """Validate selector scope while preserving safety.py monkeypatch seams."""
    from chaosforge.providers.azure.components.aks.discovery import AzureAKSDiscovery

    return _safety_selector.validate_and_resolve_selector(
        aks_context, namespace, deployment, target_mode, label_key, label_val,
        ui=ui, session=session, exact_pod_targeting=exact_pod_targeting,
        kubectl=_kubectl, discovery_factory=AzureAKSDiscovery, sleep=time.sleep,
    )


# ── Post-experiment checks ───────────────────────────────────────────────────

def build_post_experiment_checks(
    experiment_id: str,
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    dns_pattern: str = "",
    target_mode: str = "",
    exact_pod_name: str = "",
    volume_path: str = "/data",
    recovery_wait_seconds: int = 0,
    recovery_retry_count: int = 0,
    recovery_retry_interval_seconds: int = 50,
) -> "dict[str, callable]":
    """
    Build experiment-specific post-check dict for pod/stress chaos experiments.
    Returns {label: fn} consumed by ValidationSession.run_checks().
    """
    checks: dict[str, callable] = {}
    selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"
    use_exact_pod_scope = (
        target_mode == "pod"
        and exact_pod_name
    )
    selection_args = (
        ["--field-selector", f"metadata.name={exact_pod_name}"]
        if use_exact_pod_scope else ["-l", selector]
    )
    selection_display = " ".join(selection_args)

    def _service_fqdn():
        service_name, found = _find_svc_name(
            namespace, label_key, label_val, deployment, aks_context
        )
        if not found:
            return "", (
                f"No Service found for selector {label_key}={label_val} "
                f"in '{namespace}'"
            )
        return f"{service_name}.{namespace}.svc.cluster.local", ""

    # ── shared helpers ───────────────────────────────────────────────────────

    def _get_pods():
        if experiment_id in _PYTHON_CLIENT_EXPERIMENTS:
            from chaosforge.providers.azure.components.aks.kubernetes import get_pods
            return get_pods(
                aks_context, namespace,
                label_selector="" if use_exact_pod_scope else selector,
                field_selector=f"metadata.name={exact_pod_name}" if use_exact_pod_scope else "",
            )
        r = _kubectl("get", "pods", "-n", namespace, *selection_args, "-o", "json",
                     context=aks_context)
        if r.returncode != 0:
            return None, f"kubectl get pods failed: {r.stderr.strip()}"
        try:
            return json.loads(r.stdout).get("items", []), None
        except ValueError as exc:
            return None, f"Could not parse pods: {exc}"

    def _get_deployment():
        if experiment_id in _PYTHON_CLIENT_EXPERIMENTS:
            from chaosforge.providers.azure.components.aks.kubernetes import (
                get_deployment,
            )
            return get_deployment(aks_context, namespace, deployment)
        r = _kubectl("get", "deployment", deployment, "-n", namespace, "-o", "json",
                     context=aks_context)
        if r.returncode != 0:
            return None, f"kubectl get deployment failed: {r.stderr.strip()}"
        try:
            return json.loads(r.stdout), None
        except ValueError as exc:
            return None, f"Could not parse deployment: {exc}"

    def _get_pods_desc():
        return (
            f"Kubernetes Python client: list_namespaced_pod(namespace={namespace}, context={aks_context})"
            if experiment_id in _PYTHON_CLIENT_EXPERIMENTS
            else f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}"
        )

    def _get_deployment_desc():
        return (
            f"Kubernetes Python client: read_namespaced_deployment(name={deployment}, namespace={namespace}, context={aks_context})"
            if experiment_id in _PYTHON_CLIENT_EXPERIMENTS
            else f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}"
        )

    # ── Pod Recovery ─────────────────────────────────────────────────────────
    def _pod_recovery():
        if recovery_wait_seconds:
            time.sleep(recovery_wait_seconds)
        for attempt in range(recovery_retry_count + 1):
            if use_exact_pod_scope and experiment_id == "aks-pod-kill":
                from chaosforge.providers.azure.components.aks.kubernetes import get_pods

                pods, err = get_pods(
                    aks_context,
                    namespace,
                    label_selector=selector,
                )
                description = (
                    f"Kubernetes Python client: list_namespaced_pod(namespace={namespace}, "
                    f"label_selector={selector}, context={aks_context})"
                )
            else:
                pods, err = _get_pods()
                description = _get_pods_desc()
            if pods is None:
                return False, err
            running = [
                pod.get("metadata", {}).get("name", "?") for pod in pods
                if pod.get("status", {}).get("phase") == "Running"
            ]
            all_names = [pod.get("metadata", {}).get("name", "?") for pod in pods]
            detail = (
                f"{description}\n"
                f"  total={len(all_names)}  running={len(running)}"
                + (f"  [{', '.join(running)}]" if running else "")
            )
            if running and len(running) == len(all_names):
                return True, detail + f"\n  ✔ Replacement workload healthy on attempt {attempt + 1}"
            if attempt < recovery_retry_count:
                time.sleep(recovery_retry_interval_seconds)
        if not running:
            return False, detail + "\n  ✘ No pods found; no replacement pods became Running"
        not_running = [name for name in all_names if name not in running]
        return False, detail + f"\n  ✘ Not Running after {recovery_retry_count + 1} attempts: {not_running}"
    checks["Pod Recovery"] = _pod_recovery

    # ── Replica Count Restored ───────────────────────────────────────────────
    def _replica_restored():
        dep, _err = _get_deployment()
        if dep is None:
            # deployment field may be a pod name (By Pod target mode) — check if
            # a pod with that name exists and is Running; if so, treat as restored.
            rp = _kubectl("get", "pod", deployment, "-n", namespace,
                          "-o", "jsonpath={.status.phase}", context=aks_context)
            if rp.returncode == 0 and rp.stdout.strip() == "Running":
                return True, f"Target '{deployment}' is a standalone pod — Running ✔"
            if rp.returncode == 0:
                phase = rp.stdout.strip() or "Unknown"
                return False, f"Target '{deployment}' is a standalone pod — phase={phase} (expected Running)"
            # Neither a deployment nor a pod — skip gracefully
            return True, f"Target '{deployment}' not found as Deployment or Pod — skipping replica check"
        desired   = dep.get("spec", {}).get("replicas") or 0
        ready     = dep.get("status", {}).get("readyReplicas") or 0
        available = dep.get("status", {}).get("availableReplicas") or 0
        detail = (
            f"{_get_deployment_desc()}\n"
            f"  desired={desired}  ready={ready}  available={available}"
        )
        if ready < desired or available < desired:
            return False, detail + f"\n  ✘ Not fully restored (expected {desired})"
        return True, detail
    checks["Replica Count Restored"] = _replica_restored

    # ── Containers Ready ─────────────────────────────────────────────────────
    def _containers_ready():
        pods, err = _get_pods()
        if pods is None:
            return False, err
        not_ready = []
        for pod in pods:
            name = pod.get("metadata", {}).get("name", "?")
            for cs in pod.get("status", {}).get("containerStatuses", []):
                if not cs.get("ready", False):
                    not_ready.append(f"{name}/{cs.get('name','?')}")
        detail = (
            f"{_get_pods_desc()}\n"
            f"  containers not ready: {not_ready if not_ready else 'none'}"
        )
        if not_ready:
            return False, detail + "\n  ✘ Some containers not yet Ready"
        return True, detail
    checks["Containers Ready"] = _containers_ready

    # ── No CrashLoop ────────────────────────────────────────────────────────
    def _no_crashloop():
        pods, err = _get_pods()
        if pods is None:
            return False, err
        crashing = []
        for pod in pods:
            name = pod.get("metadata", {}).get("name", "?")
            for cs in pod.get("status", {}).get("containerStatuses", []):
                reason = cs.get("state", {}).get("waiting", {}).get("reason", "")
                if reason == "CrashLoopBackOff":
                    crashing.append(f"{name}/{cs.get('name','?')}")
        detail = (
            f"{_get_pods_desc()}\n"
            f"  CrashLoopBackOff containers: {crashing if crashing else 'none'}"
        )
        if crashing:
            return False, detail + "\n  ✘ CrashLoopBackOff detected after rollback"
        return True, detail
    checks["No CrashLoop"] = _no_crashloop

    # ── Pod Events (last 5m) ─────────────────────────────────────────────────

    def _pod_events():
        r = _kubectl("get", "events", "-n", namespace,
                     "--field-selector", "involvedObject.kind=Pod",
                     "-o", "json", context=aks_context)
        if r.returncode != 0:
            return True, f"Could not query events (non-fatal): {r.stderr.strip()}"
        try:
            events = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, "Could not parse events — skipping"

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
        bad_reasons = {"BackOff", "OOMKilling", "OOMKilled", "Failed", "CrashLoopBackOff"}
        warning_events = []
        for ev in events:
            if ev.get("type") != "Warning":
                continue
            ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
            try:
                ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except ValueError:
                pass
            reason  = ev.get("reason", "")
            message = ev.get("message", "")[:80]
            obj     = ev.get("involvedObject", {}).get("name", "?")
            if reason in bad_reasons or any(b.lower() in message.lower() for b in bad_reasons):
                warning_events.append(f"  {obj}: {reason} — {message}")

        detail = (
            f"kubectl get events -n {namespace} --field-selector involvedObject.kind=Pod "
            f"--context {aks_context}  (last 5m)\n"
            + ("\n".join(warning_events) if warning_events else "  no Warning events")
        )
        if warning_events:
            return False, detail + "\n  ✘ Warning events detected after rollback"
        return True, detail
    _NETWORK_CHAOS_ALL = (_NETWORK_DELAY_IDS | _PACKET_LOSS_IDS | _BANDWIDTH_LIMIT_IDS |
                          _PACKET_CORRUPTION_IDS | _PACKET_DUPLICATION_IDS | _PARTITION_IDS)
    if experiment_id not in _NETWORK_CHAOS_ALL:
        checks["Pod Events (last 5m)"] = _pod_events

    checks.update(_safety_post_network_delay_loss_bandwidth.build_post_network_checks(
        experiment_id, aks_context, namespace, deployment, label_key, label_val,
        selection_args, selection_display,
        kubectl=lambda: _kubectl, find_svc_name=lambda: _find_svc_name,
    ))

    checks.update(_safety_post_network_corruption_duplication_partition.build_post_network_checks(
        experiment_id, aks_context, namespace, deployment, label_key, label_val,
        selection_args, selection_display,
        kubectl=lambda: _kubectl, find_svc_name=lambda: _find_svc_name,
        partition_ping_target=lambda: _np_partition_ping_target,
    ))

    if experiment_id in _STRESS_CHAOS_IDS:
        def _no_oom_post():
            pods, err = _get_pods()
            if pods is None:
                return False, err
            oom = []
            for pod in pods:
                name = pod.get("metadata", {}).get("name", "?")
                for cs in pod.get("status", {}).get("containerStatuses", []):
                    last = cs.get("lastState", {}).get("terminated", {})
                    if last.get("reason") == "OOMKilled":
                        oom.append(f"{name}/{cs.get('name','?')}")
            detail = (
                f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
                f"  OOMKilled containers (post-stress): {oom if oom else 'none'}"
            )
            if oom:
                return False, detail + "\n  ✘ OOMKilled detected — memory stress may have caused eviction"
            return True, detail
        checks["No OOMKilled (post)"] = _no_oom_post

    # ── Extended post-checks: TimeChaos, HTTPChaos, DNSChaos ─────────────────
    _TIME_POST_IDS = {"aks-clock-skew-forward", "aks-clock-skew-backward"}
    _HTTP_POST_IDS = {"aks-http-delay", "aks-http-abort"}
    _DNS_POST_IDS  = {"aks-dns-failure"}

    if experiment_id in _TIME_POST_IDS:
        try:
            from .extended import build_time_chaos_post_checks
            checks.update(build_time_chaos_post_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
            ))
        except ImportError:
            pass

    if experiment_id in _HTTP_POST_IDS:
        try:
            from .extended import build_http_chaos_post_checks
            checks.update(build_http_chaos_post_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
            ))
        except ImportError:
            pass

    if experiment_id in _DNS_POST_IDS:
        try:
            from .extended import build_dns_chaos_post_checks
            checks.update(build_dns_chaos_post_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
                dns_pattern=dns_pattern,
            ))
        except ImportError:
            pass

    # ── Extended post-checks: IOChaos ─────────────────────────────────────────
    # Self-contained for aks-io-latency / aks-io-errors only — delegated to
    # build_io_chaos_post_checks() in aks_extended_checks.py.
    _IO_POST_IDS = {"aks-io-latency", "aks-io-errors"}
    if experiment_id in _IO_POST_IDS:
        try:
            from .extended import build_io_chaos_post_checks
            checks.update(build_io_chaos_post_checks(
                aks_context, namespace, deployment,
                label_key=label_key, label_val=label_val,
                volume_path=volume_path,
            ))
        except ImportError:
            pass

    # Cluster-plane experiments (CoreDNS/kube-proxy) target kube-system directly —
    # no app namespace/deployment involved, unlike Time/HTTP/DNS chaos above.
    _CLUSTER_PLANE_POST_IDS = {"aks-coredns-kill", "aks-coredns-cpu", "aks-kube-proxy-kill"}
    if experiment_id in _CLUSTER_PLANE_POST_IDS:
        try:
            from .extended import build_cluster_plane_chaos_post_checks
            checks.update(build_cluster_plane_chaos_post_checks(
                aks_context, experiment_id,
            ))
        except ImportError:
            pass
        # Generic deployment/pod checks below are meaningless for cluster-plane
        # experiments — no user namespace/deployment target. Stop here.
        return checks

    if not deployment and not label_key:
        return checks

    if use_exact_pod_scope:
        def _exact_pod_endpoint_restored():
            pods, err = _get_pods()
            if pods is None:
                return False, err
            if len(pods) != 1:
                return False, (
                    f"Expected exact pod '{exact_pod_name}', found {len(pods)} matching pods"
                )
            pod_ip = pods[0].get("status", {}).get("podIP", "")
            svc_name, svc_found = _find_svc_name(
                namespace, label_key, label_val, deployment, aks_context
            )
            if not svc_found:
                return True, (
                    f"Exact pod '{exact_pod_name}' is Ready; no matching Service exists, "
                    "so endpoint validation is not applicable."
                )
            result = _kubectl(
                "get", "endpoints", svc_name, "-n", namespace, "-o", "json",
                context=aks_context,
            )
            if result.returncode != 0:
                return False, f"Could not query Service endpoints: {result.stderr.strip()}"
            try:
                endpoint = json.loads(result.stdout)
            except ValueError as exc:
                return False, f"Could not parse Service endpoints: {exc}"
            ready_ips = {
                address.get("ip", "")
                for subset in (endpoint.get("subsets") or [])
                for address in (subset.get("addresses") or [])
            }
            detail = (
                f"Exact target pod: {exact_pod_name}  podIP={pod_ip or 'unknown'}\n"
                f"Service/{svc_name} ready endpoint IPs: {sorted(ready_ips)}"
            )
            if not pod_ip or pod_ip not in ready_ips:
                return False, detail + "\n  ✘ Exact target pod is not a ready Service endpoint"
            return True, detail + "\n  ✔ Exact target pod is restored in Service endpoints"

        def _exact_pod_probe_failures_stopped():
            result = _kubectl(
                "get", "events", "-n", namespace,
                "--field-selector", "reason=Unhealthy", "-o", "json",
                context=aks_context,
            )
            if result.returncode != 0:
                return True, "Could not query probe events — advisory skipped"
            try:
                events = json.loads(result.stdout).get("items", [])
            except ValueError:
                return True, "Could not parse probe events — advisory skipped"
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=2)
            recent = []
            for event in events:
                if event.get("involvedObject", {}).get("name") != exact_pod_name:
                    continue
                timestamp = event.get("lastTimestamp") or event.get("eventTime") or ""
                try:
                    if _dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")) < cutoff:
                        continue
                except ValueError:
                    pass
                recent.append(event.get("message", "")[:100])
            detail = f"Probe events for exact pod '{exact_pod_name}' in the last 2m"
            if recent:
                return False, detail + "\n  " + "\n  ".join(recent)
            return True, detail + "\n  ✔ No recent probe failures"

        if "Service Endpoints Restored" in checks:
            checks["Service Endpoints Restored"] = _exact_pod_endpoint_restored
        if "Probe Failures Stopped (post)" in checks:
            checks["Probe Failures Stopped (post)"] = _exact_pod_probe_failures_stopped

    return checks
