# Per-experiment target metadata. workload_kind drives which kubectl resource
# type we read the desired/ready replica count from (Deployment for CoreDNS,
# DaemonSet for kube-proxy since it's one pod per node, not a replica set).
import datetime as _dt
import json

from ._extended_common import (
    _canary_pod,
    _get_pods_json,
    _get_ready_node_count,
    _get_workload_by_selector,
    _kubectl,
)

# Many app-namespace canary pods (the whole point of picking one outside
# kube-system) ship minimal images with neither curl/wget nor nslookup/getent
# installed. Probe with whatever tool is present and emit this marker when
# none is, so callers can distinguish "couldn't even try" from "tried and failed".
_NOPROBE_MARKER = "__NOPROBE__"


def _canary_probe_cmd(component: str) -> str:
    if component == "CoreDNS":
        return (
            "if command -v nslookup >/dev/null 2>&1; then "
            "nslookup kubernetes.default.svc.cluster.local; "
            "elif command -v getent >/dev/null 2>&1; then "
            "getent hosts kubernetes.default.svc.cluster.local; "
            f"else echo {_NOPROBE_MARKER}; fi"
        )
    return (
        "if command -v curl >/dev/null 2>&1; then "
        "curl -sk -o /dev/null -w '%{http_code}' -m 5 https://kubernetes.default.svc.cluster.local:443; "
        "elif command -v wget >/dev/null 2>&1; then "
        "wget -q -O /dev/null --no-check-certificate -T 5 https://kubernetes.default.svc.cluster.local:443 && echo 200; "
        f"else echo {_NOPROBE_MARKER}; fi"
    )


_CLUSTER_PLANE_TARGETS = {
    "aks-coredns-kill": {
        "component": "CoreDNS", "selector": "k8s-app=kube-dns", "workload_kind": "deployment",
        "selector_fallbacks": [],
    },
    "aks-coredns-cpu": {
        "component": "CoreDNS", "selector": "k8s-app=kube-dns", "workload_kind": "deployment",
        "selector_fallbacks": [],
    },
    # kube-proxy label varies by CNI/AKS version:
    #   AKS default:  component=kube-proxy
    #   upstream k8s: k8s-app=kube-proxy
    # Try primary selector first; fall back to the alternate so a different-
    # label cluster doesn't hard-block with "no pods found" when pods exist.
    "aks-kube-proxy-kill": {
        "component": "kube-proxy", "selector": "component=kube-proxy", "workload_kind": "daemonset",
        "selector_fallbacks": ["k8s-app=kube-proxy"],
    },
}


def build_cluster_plane_chaos_pre_checks(
    aks_context: str,
    experiment_id: str,
    *,
    mode: str = "one",
    duration: str = "60s",
    chaos_value: str = "",
) -> "dict[str, callable]":
    """
    Pre-chaos checks for cluster-plane experiments: CoreDNS Pod Kill,
    CoreDNS CPU Starvation (90%), kube-proxy Pod Kill.

    Hard blocks:
      - target component not present/visible via kubectl (dataplane mode
        mismatch between clusters, or component already down)
      - fewer than 2 Ready instances of the component (killing/stressing one
        would leave zero healthy instances — total cluster-wide outage)
      - a matching PodDisruptionBudget currently allows zero disruptions
      - chaos_mode resolves to "all" (or a fixed count/percent covering every
        instance) instead of a single instance — this is meant to be a
        single-instance fault-tolerance test, not a full outage drill
      - another PodChaos/StressChaos resource already targets this component
        (double-injection risk)

    Soft warnings:
      - shared cluster-plane infrastructure reminder (always shown, for audit trail)
      - node topology note when the running cluster looks like the small/single-node
        test cluster shape rather than a multi-node non-prod cluster
      - CoreDNS CPU stress without CPU limits set on the container (harder to
        reason about actual saturation achieved)

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    target             = _CLUSTER_PLANE_TARGETS.get(experiment_id, {})
    component          = target.get("component", "?")
    _primary_selector  = target.get("selector", "")
    _selector_fallbacks = target.get("selector_fallbacks", [])
    target.get("workload_kind", "deployment")
    _mode              = (mode or "one").strip().lower()

    # Resolve effective selector: try primary first, fall back if no pods found.
    # Fixes kube-proxy label mismatch between AKS (component=kube-proxy) and
    # upstream clusters (k8s-app=kube-proxy) — without this, the pre-check
    # hard-blocks with "no pods found" when pods exist under a different label.
    selector = _primary_selector
    for _candidate in [_primary_selector] + _selector_fallbacks:
        _r = _kubectl("get", "pods", "-n", "kube-system", "-l", _candidate,
                      "--no-headers", context=aks_context)
        if _r.returncode == 0 and _r.stdout.strip():
            selector = _candidate
            break

    # ── 1. Shared cluster-plane infrastructure notice (always logged) ────────
    # Rationale: this is not a per-team check that can be waived silently — it
    # exists so the audit trail always records that a shared-infra experiment
    # ran, independent of whether every other check passes.
    def _shared_infra_notice():
        return True, (
            f"⚠ Target: {component} in kube-system — SHARED cluster-plane infrastructure "
            "operated by the SCP team. Every namespace/team on this cluster depends on it. "
            "Treat blast radius as cluster-wide, not namespace-scoped, regardless of which "
            "team requested this experiment."
        )
    checks[f"{component} Shared Cluster-Plane Notice"] = _shared_infra_notice

    # ── 1b. Chaos Mesh daemon runtime = containerd (HARD BLOCK for pod-kill) ──
    # Rationale: AKS uses containerd as the container runtime. chaos-daemon must
    # be installed with --runtime=containerd. If installed with the Docker default,
    # pod-kill calls `docker kill` which does not exist on AKS nodes — the
    # experiment reports success while injecting nothing.
    if experiment_id in ("aks-coredns-kill", "aks-kube-proxy-kill"):
        def _chaos_daemon_runtime():
            r = _kubectl("get", "daemonset", "chaos-daemon", "-n", "chaos-testing",
                         "-o", "jsonpath={.spec.template.spec.containers[0].command}",
                         context=aks_context)
            detail = "kubectl get daemonset chaos-daemon -n chaos-testing -o jsonpath=...command"
            if r.returncode != 0:
                return True, detail + f"\n  (could not query chaos-daemon — skipping: {r.stderr.strip()[:80]})"
            cmd_str = r.stdout.strip()
            if "containerd" in cmd_str:
                return True, detail + f"\n  command={cmd_str[:200]}\n  ✔ --runtime=containerd confirmed"
            return False, (
                detail + f"\n  command={cmd_str[:200]}"
                "\n  ✘ '--runtime=containerd' not found in chaos-daemon command. "
                "AKS nodes use containerd — pod-kill will silently fail (calls 'docker kill' "
                "which does not exist). Re-install Chaos Mesh with: "
                "--set chaosDaemon.runtime=containerd "
                "--set chaosDaemon.socketPath=/run/containerd/containerd.sock"
            )
        checks["Chaos Daemon Runtime (containerd)"] = _chaos_daemon_runtime

    # ── 1c. Chaos daemon present on target node(s) (HARD BLOCK, StressChaos) ─
    # Rationale: StressChaos needs chaos-daemon on the SAME node as the target
    # pod to nsenter into its cgroup and run stress-ng. Unlike pod-kill (which
    # just calls the k8s delete API), a missing chaos-daemon here means the
    # controller logs "cannot find daemonIP on node ..." and retries for the
    # entire experiment duration while injecting nothing — CPU/MEM metrics
    # stay flat and the run reports "stress active" with no evidence why not.
    # AKS system nodepools taint themselves `CriticalAddonsOnly:NoSchedule`;
    # if the chaos-daemon DaemonSet has no matching toleration it will never
    # be scheduled there, even though `kubectl get daemonset` reports healthy.
    if experiment_id == "aks-coredns-cpu":
        def _chaos_daemon_on_target_nodes():
            rn = _kubectl("get", "pods", "-n", "kube-system", "-l", selector,
                         "-o", "jsonpath={.items[*].spec.nodeName}", context=aks_context)
            detail = f"kubectl get pods -n kube-system -l {selector} -o jsonpath=...nodeName"
            if rn.returncode != 0 or not rn.stdout.strip():
                return True, detail + "\n  (could not resolve target node(s) — skipping)"
            target_nodes = {n for n in rn.stdout.strip().split() if n}

            rd = _kubectl("get", "pods", "-n", "chaos-testing",
                         "-l", "app.kubernetes.io/component=chaos-daemon",
                         "-o", "jsonpath={range .items[*]}{.spec.nodeName}{'='}{.status.phase}{'\\n'}{end}",
                         context=aks_context)
            daemon_nodes = set()
            if rd.returncode == 0:
                for line in rd.stdout.strip().splitlines():
                    if "=Running" in line:
                        daemon_nodes.add(line.split("=", 1)[0])

            detail2 = (
                f"{detail}\n  Target node(s): {sorted(target_nodes)}\n"
                f"  chaos-daemon Running on: {sorted(daemon_nodes) or '(none found)'}"
            )
            missing = sorted(target_nodes - daemon_nodes)
            if missing:
                return False, (
                    detail2 + f"\n  ✘ chaos-daemon NOT present/Running on node(s) {missing} — "
                    "StressChaos cannot nsenter into the target container's cgroup there and "
                    "will fail with 'cannot find daemonIP on node ...' for the entire run. "
                    "This is almost always a node taint (e.g. CriticalAddonsOnly on AKS system "
                    "nodepools) the chaos-daemon DaemonSet lacks a matching toleration for — "
                    "add one and re-deploy chaos-daemon before retrying."
                )
            return True, detail2 + "\n  ✔ chaos-daemon present and Running on all target node(s)"
        checks["Chaos Daemon Present On Target Node(s)"] = _chaos_daemon_on_target_nodes

    # ── 2. Component present & visible via kubectl (HARD BLOCK) ──────────────
    # Rationale: some AKS dataplane configurations (Azure CNI Overlay / Cilium
    # eBPF "kube-proxy-free" clusters) do not run visible kube-proxy pods at
    # all. The East US test cluster and the Central US non-prod cluster are
    # not guaranteed to run the same CNI/dataplane mode — an experiment
    # validated in test could silently find nothing to target in non-prod,
    # which would report a false "pass" without ever having exercised anything.
    def _component_present():
        pods, err = _get_pods_json(aks_context, "kube-system", selector)
        detail = f"kubectl get pods -n kube-system -l {selector} --context {aks_context}"
        if pods is None:
            return False, detail + f"\n  ✘ Could not query {component} pods: {err}"
        if not pods:
            return False, (
                detail + f"\n  ✘ No {component} pods found with selector '{selector}'. "
                f"This cluster may run a dataplane mode without visible {component} pods "
                "(e.g. Cilium/eBPF, kube-proxy-free mode). Confirm the CNI/dataplane mode "
                "here matches what was validated in the test cluster — do not assume this "
                "experiment applies unchanged."
            )
        ready = [
            p for p in pods
            if p.get("status", {}).get("phase") == "Running"
            and any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in p.get("status", {}).get("conditions", []))
        ]
        detail += f"\n  {component} pods found: {len(pods)}  ready: {len(ready)}"
        if not ready:
            return False, (
                detail + f"\n  ✘ No {component} pods Ready. Component is already degraded — "
                "injecting additional chaos would compound an existing incident, not test one."
            )
        return True, detail + f"\n  ✔ {component} present and Ready ({len(ready)} instance(s))"
    checks[f"{component} Present & Ready"] = _component_present

    # ── 3. High-availability floor (HARD BLOCK) ──────────────────────────────
    # Rationale: CoreDNS is a Deployment (N replicas, autoscaled by AKS's
    # coredns-autoscaler off node/core count); kube-proxy is a DaemonSet (one
    # pod per node). Either way, if there are fewer than 2 Ready instances,
    # killing/stressing "one" removes the LAST healthy instance — this is a
    # cluster-wide DNS or service-routing outage, not a fault-tolerance test.
    # This is intentionally a hard block (not a warning) because the blast
    # radius here is every namespace, not just the team that requested it.
    def _ha_floor():
        pods, err = _get_pods_json(aks_context, "kube-system", selector)
        if pods is None:
            return False, f"Could not query {component} pods to assess HA floor: {err}"
        ready = [
            p for p in pods
            if p.get("status", {}).get("phase") == "Running"
            and any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in p.get("status", {}).get("conditions", []))
        ]
        detail = (
            f"kubectl get pods -n kube-system -l {selector} --context {aks_context}\n"
            f"  Ready {component} instances: {len(ready)}"
        )
        if len(ready) < 2:
            return False, (
                detail + f"\n  ✘ Only {len(ready)} Ready {component} instance(s) cluster-wide. "
                f"Removing/stressing it leaves ZERO healthy {component} instances — this is a "
                "total outage for every namespace on the cluster, not a single-instance "
                "fault-tolerance test. Scale the component to >=2 Ready instances (or wait for "
                "AKS's autoscaler to do so) before running this experiment."
            )
        return True, detail + f"\n  ✔ HA floor satisfied — {len(ready)} Ready instances, safe to remove one"
    checks[f"{component} HA Floor (>=2 Ready)"] = _ha_floor

    # ── 4. PodDisruptionBudget safety (HARD BLOCK) ───────────────────────────
    # Rationale: AKS-managed CoreDNS ships with a PDB by default; a custom one
    # may also exist for kube-proxy. If disruptionsAllowed is already 0, the
    # cluster itself considers a further disruption unsafe — chaos experiments
    # should respect that signal exactly like the app-namespace checks do.
    def _pdb_safety():
        r = _kubectl("get", "pdb", "-n", "kube-system", "-o", "json", context=aks_context)
        detail = f"kubectl get pdb -n kube-system --context {aks_context}"
        if r.returncode != 0:
            return True, detail + "\n  (no PDB API response — nothing to guard against)"
        try:
            pdbs = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, detail + "\n  (could not parse PDB list — skipping)"

        matched = []
        for pdb in pdbs:
            match_labels = pdb.get("spec", {}).get("selector", {}).get("matchLabels") or {}
            sel_key, sel_val = (selector.split("=", 1) + [""])[:2]
            if match_labels.get(sel_key) != sel_val:
                continue
            name    = pdb.get("metadata", {}).get("name", "unknown")
            status  = pdb.get("status", {})
            allowed = status.get("disruptionsAllowed")
            matched.append((name, allowed, status.get("currentHealthy"), status.get("desiredHealthy")))

        if not matched:
            return True, detail + f"\n  No PDB matches selector '{selector}' — nothing to guard against"

        blocking = [m for m in matched if m[1] is not None and m[1] < 1]
        detail += "\n  " + "\n  ".join(
            f"PDB '{n}': disruptionsAllowed={a} currentHealthy={ch} desiredHealthy={dh}"
            for n, a, ch, dh in matched
        )
        if blocking:
            name = blocking[0][0]
            return False, (
                detail + f"\n  ✘ PodDisruptionBudget '{name}' currently allows 0 disruptions. "
                f"The cluster itself has flagged {component} as unsafe to disrupt right now — "
                "wait for it to have enough healthy replicas before running chaos."
            )
        return True, detail + "\n  ✔ PDB(s) allow disruption — safe to proceed"
    checks[f"{component} PodDisruptionBudget Safety"] = _pdb_safety

    # ── 5. Blast-radius mode check (HARD BLOCK) ──────────────────────────────
    # Rationale: these experiments are shipped with mode="one" (single-instance
    # fault-tolerance test). If an operator overrides chaos_mode to "all" (or a
    # fixed count/percent that covers every instance), the experiment silently
    # becomes a full cluster-wide DNS/routing outage drill instead — that needs
    # to be an explicit, separately-approved decision, not an accidental one.
    def _blast_radius_mode():
        detail = f"Resolved chaos mode: '{_mode}'"
        if _mode in ("all",):
            return False, (
                detail + f"\n  ✘ mode='all' would disrupt EVERY {component} instance "
                "simultaneously — a total cluster-wide outage, not a single-instance "
                "fault-tolerance test. If a full-outage drill is genuinely intended, run it "
                "as its own explicitly-approved experiment, not via an overridden mode."
            )
        if _mode not in ("one", "fixed", "fixed-percent"):
            return True, (
                "⚠ " + detail + "\n  Unrecognized mode for a cluster-plane experiment — "
                "verify it targets a single instance before proceeding."
            )
        return True, detail + "\n  ✔ Mode is scoped to a bounded subset, not the full component"
    checks["Blast-Radius Mode Check"] = _blast_radius_mode

    # ── 6. Node topology note — test cluster vs non-prod shape (SOFT WARNING) ─
    # Rationale: the East US test cluster and the Central US non-prod cluster
    # are not guaranteed to have the same node count. A single-node (or very
    # small) cluster makes kube-proxy-kill and CoreDNS HA behave very
    # differently than a properly-sized non-prod/prod cluster — a clean result
    # here does not necessarily generalize. This is advisory, not a hard block,
    # since a small non-prod cluster is a legitimate (if risky) configuration.
    def _node_topology_note():
        ready, total, err = _get_ready_node_count(aks_context)
        if ready is None:
            return True, f"Could not determine node count: {err} — skipping topology note"
        detail = f"kubectl get nodes --context {aks_context}\n  Ready nodes: {ready}/{total}"
        if total < 2:
            return True, (
                "⚠ " + detail + "\n  Single-node (or fewer) cluster detected. If this differs "
                "from the target non-prod cluster's node count, results here may not predict "
                "the actual blast radius in non-prod — re-validate node topology assumptions "
                "before treating a test-cluster pass as sufficient sign-off."
            )
        return True, detail + "\n  ✔ Multi-node cluster — recorded for blast-radius context"
    checks["Node Topology Note (test vs non-prod)"] = _node_topology_note

    # ── 7. No existing chaos CRD already targeting this component (HARD BLOCK) ─
    # Rationale: avoid double-injection — if a PodChaos/StressChaos resource
    # from a prior/concurrent run is still active against the same selector,
    # stacking another fault on top makes the actual blast radius unpredictable
    # for shared infrastructure everyone else also depends on.
    def _no_existing_chaos_crd():
        found = []
        for kind in ("podchaos", "stresschaos"):
            r = _kubectl("get", kind, "-n", "chaos-testing", "-o", "json", context=aks_context)
            if r.returncode != 0:
                continue
            try:
                items = json.loads(r.stdout).get("items", [])
            except ValueError:
                continue
            for item in items:
                labels = item.get("spec", {}).get("selector", {}).get("labelSelectors", {}) or {}
                sel_key, sel_val = (selector.split("=", 1) + [""])[:2]
                if labels.get(sel_key) == sel_val:
                    found.append(f"{kind}/{item.get('metadata', {}).get('name', '?')}")
        detail = f"kubectl get podchaos,stresschaos -n chaos-testing --context {aks_context}"
        if found:
            return False, (
                detail + f"\n  ✘ Existing chaos resource(s) already target {component}: {found}. "
                "Clean these up before starting a new run — stacked faults on shared "
                "cluster-plane infrastructure have unpredictable combined blast radius."
            )
        return True, detail + f"\n  ✔ No existing chaos resources targeting {component}"
    checks["No Existing Chaos CRD For Target"] = _no_existing_chaos_crd

    # ── 8. Cluster-wide canary baseline (outside kube-system) ────────────────
    # Rationale: validating from a pod inside kube-system proves nothing about
    # impact to the app teams who actually depend on this component. A canary
    # pod picked from an unrelated namespace gives a ground-truth "before"
    # baseline for the teams who never opted into this experiment but will
    # feel it if something goes wrong.
    def _canary_baseline():
        pod, ns = _canary_pod(aks_context)
        if not pod:
            return True, (
                "⚠ No canary pod found outside kube-system/chaos-testing — "
                "cannot capture a cluster-wide baseline unrelated to the experiment's own "
                "namespace. Proceeding without an independent blast-radius witness."
            )
        cmd_str = _canary_probe_cmd(component)
        r = _kubectl("exec", pod, "-n", ns, "--", "sh", "-c", cmd_str, context=aks_context)
        detail = (
            f"Canary pod: {pod} (namespace={ns}, unrelated to {component}'s own namespace)\n"
            f"kubectl exec {pod} -n {ns} -- sh -c '{cmd_str}'\n"
            f"  exit={r.returncode}  output={r.stdout.strip()[:120]}"
        )
        if r.returncode != 0 or _NOPROBE_MARKER in r.stdout:
            return True, (
                "⚠ " + detail + "\n  Baseline probe failed or tool unavailable in canary pod — "
                "cannot confirm pre-chaos cluster-wide health from an independent namespace. "
                "Post-chaos recovery check will still run."
            )
        return True, detail + "\n  ✔ Cluster-wide baseline captured from an unrelated namespace"
    checks["Cluster-Wide Canary Baseline"] = _canary_baseline

    # ── 9. CoreDNS CPU limits set (SOFT WARNING, CPU-stress experiment only) ──
    # Rationale: a 90%-load StressChaos run is only meaningful relative to a
    # known CPU limit. Without one, "90% load" is unbounded and can consume
    # far more node CPU than intended, starving other kube-system/DaemonSet
    # pods co-located on the same node.
    if experiment_id == "aks-coredns-cpu":
        def _coredns_cpu_limits():
            dep, err = _get_workload_by_selector(aks_context, "kube-system", "deployment", selector)
            detail = f"kubectl get deployment -n kube-system -l {selector} --context {aks_context}"
            if dep is None:
                return True, detail + f"\n  ({err or 'not found'} — skipping CPU-limit check)"
            containers = dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            unlimited = [
                c.get("name", "?") for c in containers
                if not c.get("resources", {}).get("limits", {}).get("cpu")
            ]
            if unlimited:
                return True, (
                    "⚠ " + detail + f"\n  Container(s) without a CPU limit: {unlimited}. "
                    "A 90% CPU StressChaos run against an unbounded container can consume "
                    "more node CPU than expected and throttle co-located kube-system/DaemonSet "
                    "pods on the same node."
                )
            return True, detail + "\n  ✔ CPU limits set on all CoreDNS containers"
        checks["CoreDNS CPU Limits Set (Advisory)"] = _coredns_cpu_limits

    return checks


# ═════════════════════════════════════════════════════════════════════════════
# CLUSTER-PLANE CHAOS (CoreDNS / kube-proxy) — Post-Checks
# ═════════════════════════════════════════════════════════════════════════════

def build_cluster_plane_chaos_post_checks(
    aks_context: str,
    experiment_id: str,
) -> "dict[str, callable]":
    """
    Post-chaos checks for cluster-plane experiments: CoreDNS Pod Kill,
    CoreDNS CPU Starvation (90%), kube-proxy Pod Kill.

    Confirms the component recovered to its desired Ready count, no
    crash-looping resulted, the Chaos Mesh CRD was cleaned up, and — critically
    — that a pod OUTSIDE kube-system (a stand-in for every other team on the
    cluster) can resolve DNS / reach cluster Services again. That last check
    is the ground-truth signal for cluster-plane experiments: the CRD being
    deleted only proves Chaos Mesh thinks it's done, not that every other
    namespace's workloads have actually recovered.

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    target        = _CLUSTER_PLANE_TARGETS.get(experiment_id, {})
    component     = target.get("component", "?")
    selector      = target.get("selector", "")
    workload_kind = target.get("workload_kind", "deployment")

    # ── 1. Component restored to desired Ready count (HARD BLOCK) ────────────
    # Rationale: Deployment (CoreDNS) or DaemonSet (kube-proxy) reconciliation
    # should have replaced the killed pod / recovered from stress well within
    # the post-chaos check window. If desired != ready, the cluster-plane
    # component is still degraded for every namespace on the cluster.
    def _component_restored():
        wl, err = _get_workload_by_selector(aks_context, "kube-system", workload_kind, selector)
        detail = f"kubectl get {workload_kind} -n kube-system -l {selector} --context {aks_context}"
        if wl is None:
            return False, detail + f"\n  ✘ Could not query {component} {workload_kind}: {err or 'not found'}"
        status = wl.get("status", {})
        if workload_kind == "daemonset":
            desired, ready = status.get("desiredNumberScheduled", 0), status.get("numberReady", 0)
        else:
            desired, ready = status.get("replicas", 0), status.get("readyReplicas", 0)
        detail += f"\n  desired={desired}  ready={ready}"
        if ready < desired or desired == 0:
            return False, (
                detail + f"\n  ✘ {component} has not fully recovered ({ready}/{desired} Ready). "
                "Cluster DNS/service routing may still be degraded for other namespaces."
            )
        return True, detail + f"\n  ✔ {component} fully recovered ({ready}/{desired} Ready)"
    checks[f"{component} Restored to Desired Ready Count"] = _component_restored

    # ── 2. No CrashLoopBackOff on component pods (HARD BLOCK) ────────────────
    # Rationale: a pod-kill or CPU-stress fault that leaves the component
    # crash-looping after the chaos window means the fault outlived its
    # intended duration — an unbounded incident for every namespace, not a
    # bounded experiment.
    def _no_crashloop():
        pods, err = _get_pods_json(aks_context, "kube-system", selector)
        if pods is None:
            return False, f"Could not query {component} pods: {err}"
        crashlooping = []
        for pod in pods:
            name = pod.get("metadata", {}).get("name", "?")
            for cs in pod.get("status", {}).get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                if waiting.get("reason") == "CrashLoopBackOff":
                    crashlooping.append(name)
        detail = (
            f"kubectl get pods -n kube-system -l {selector} --context {aks_context}\n"
            f"  CrashLoopBackOff pods: {crashlooping if crashlooping else 'none'}"
        )
        if crashlooping:
            return False, (
                detail + f"\n  ✘ {component} pod(s) stuck in CrashLoopBackOff after chaos revert: "
                f"{crashlooping}. This is now an ongoing incident, not a bounded experiment — "
                "escalate immediately."
            )
        return True, detail + f"\n  ✔ No {component} pods in CrashLoopBackOff"
    checks[f"No {component} CrashLoopBackOff"] = _no_crashloop

    # ── 3. Chaos Mesh CRD cleaned up (HARD BLOCK) ────────────────────────────
    # Rationale: the CRD lingering past the experiment duration means the fault
    # (or Chaos Mesh's controller reconciliation) may still be active.
    def _chaos_crd_cleaned_up():
        found = []
        for kind in ("podchaos", "stresschaos"):
            r = _kubectl("get", kind, "-n", "chaos-testing", "-o", "json", context=aks_context)
            if r.returncode != 0:
                continue
            try:
                items = json.loads(r.stdout).get("items", [])
            except ValueError:
                continue
            for item in items:
                labels = item.get("spec", {}).get("selector", {}).get("labelSelectors", {}) or {}
                sel_key, sel_val = (selector.split("=", 1) + [""])[:2]
                if labels.get(sel_key) == sel_val:
                    found.append(f"{kind}/{item.get('metadata', {}).get('name', '?')}")
        detail = f"kubectl get podchaos,stresschaos -n chaos-testing --context {aks_context}"
        if found:
            return False, (
                detail + f"\n  ✘ Chaos resource(s) targeting {component} still present: {found}. "
                "The fault may still be active."
            )
        return True, detail + f"\n  ✔ No lingering chaos resources targeting {component}"
    checks[f"{component} Chaos CRD Cleaned Up"] = _chaos_crd_cleaned_up

    # ── 4. No Warning events referencing the component in last 5m (HARD BLOCK) ─
    def _no_warning_events():
        r = _kubectl("get", "events", "-n", "kube-system", "-o", "json", context=aks_context)
        if r.returncode != 0:
            return True, f"Could not query kube-system events: {r.stderr.strip()} — skipping"
        try:
            events = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, "Could not parse events — skipping"

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
        needle = "coredns" if component == "CoreDNS" else "kube-proxy"
        found = []
        for ev in events:
            if ev.get("type") != "Warning":
                continue
            obj_name = ev.get("involvedObject", {}).get("name", "")
            if needle not in obj_name.lower():
                continue
            ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
            try:
                ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except ValueError:
                pass
            found.append(f"  {obj_name}: {ev.get('reason','')} — {ev.get('message','')[:100]}")

        detail = (
            f"kubectl get events -n kube-system --context {aks_context}  (last 5m)\n"
            f"  {component}-related Warning events: " + ("\n" + "\n".join(found) if found else "none")
        )
        if found:
            return False, (
                detail + f"\n  ✘ {component}-related Warning events still occurring post-chaos. "
                "Component may not have fully stabilized yet."
            )
        return True, detail + f"\n  ✔ No {component}-related Warning events in last 5m"
    checks[f"No {component} Warning Events Post-Chaos"] = _no_warning_events

    # ── 5. Cluster-wide canary recovery (HARD BLOCK) ─────────────────────────
    # Rationale: this is the ground-truth check for cluster-plane experiments.
    # The Chaos Mesh CRD being deleted only proves the controller thinks it's
    # done — it does not prove DNS/service routing actually recovered for the
    # teams who never opted into this experiment. Re-run the same probe used
    # in the pre-check, from a pod outside kube-system.
    def _canary_recovery():
        pod, ns = _canary_pod(aks_context)
        if not pod:
            return True, (
                "⚠ No canary pod found outside kube-system/chaos-testing — "
                "cannot confirm cluster-wide recovery from an independent namespace."
            )
        cmd_str = _canary_probe_cmd(component)

        # kube-proxy is a DaemonSet: after pod-kill, its replacement must be
        # rescheduled AND reprogram this node's iptables/IPVS rules before
        # Service routing works again. If the canary pod happens to land on
        # the same node as the killed kube-proxy pod, a probe fired the
        # instant the CRD is deleted can race that reprogramming window and
        # fail even though the component is genuinely recovering. Retry a
        # few times with backoff before treating it as a real regression.
        _attempts = [0, 2, 3] if component != "CoreDNS" else [0]
        r = None
        for _wait in _attempts:
            if _wait:
                import time as _time
                _time.sleep(_wait)
            r = _kubectl("exec", pod, "-n", ns, "--", "sh", "-c", cmd_str, context=aks_context)
            if r.returncode == 0 and r.stdout.strip():
                break

        detail = (
            f"Canary pod: {pod} (namespace={ns}, unrelated to {component}'s own namespace)\n"
            f"kubectl exec {pod} -n {ns} -- sh -c '{cmd_str}'\n"
            f"  exit={r.returncode}  output={r.stdout.strip()[:120]}"
        )
        if _NOPROBE_MARKER in r.stdout:
            return True, (
                "⚠ " + detail + "\n  Canary pod has neither curl/wget (nor nslookup/getent for DNS) — "
                "cannot verify cluster-wide recovery from this namespace. This is a tooling gap in the "
                f"canary pod's image, not evidence that {component} failed to recover."
            )
        if r.returncode != 0 or not r.stdout.strip():
            return False, (
                detail + "\n  ✘ Canary probe failed post-chaos. An unrelated namespace's workload "
                f"still cannot reach cluster DNS/Services — {component} has not fully recovered "
                "cluster-wide, even if the target namespace looks healthy."
            )
        return True, detail + "\n  ✔ Cluster-wide recovery confirmed from an unrelated namespace"
    checks["Cluster-Wide Canary Recovery"] = _canary_recovery

    # ── 6. Node Ready count unchanged (SOFT WARNING) ─────────────────────────
    # Rationale: kube-proxy issues can indirectly affect node health checks.
    # A drop in Ready node count after the experiment is worth flagging even
    # though it isn't conclusive proof the experiment caused it.
    def _node_ready_consistent():
        ready, total, err = _get_ready_node_count(aks_context)
        if ready is None:
            return True, f"Could not determine node count: {err} — skipping"
        detail = f"kubectl get nodes --context {aks_context}\n  Ready nodes: {ready}/{total}"
        if ready < total:
            return True, (
                "⚠ " + detail + f"\n  {total - ready} node(s) not Ready post-chaos. "
                "Confirm this is unrelated to the experiment before closing it out."
            )
        return True, detail + "\n  ✔ All nodes Ready post-chaos"
    checks["Node Ready Count Consistent"] = _node_ready_consistent

    return checks
