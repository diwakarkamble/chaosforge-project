"""
AKS Extended Pre/Post Chaos Validation Checks
==============================================

Provides experiment-specific pre- and post-chaos safety checks for:
  - TimeChaos     (aks-clock-skew-forward, aks-clock-skew-backward)
  - HTTPChaos     (aks-http-delay, aks-http-abort)
  - DNSChaos      (aks-dns-failure)
  - Cluster-Plane (aks-coredns-kill, aks-coredns-cpu, aks-kube-proxy-kill)

Each public function returns a {label: callable} dict consumed by
ValidationSession.run_checks() — identical contract to aks_safety_checks.py.

Every callable returns (passed: bool, detail: str).

Hard blocks raise nothing — they return passed=False and a clear operator-facing
message. Soft warnings return passed=True with a ⚠ prefixed detail string so
they appear in the audit log without blocking the run.

Uses the Kubernetes Python client (via the shared services.k8s_client
dispatcher, routed through this file's own _kubectl() helper) as the
primary transport for every check, with real kubectl subprocess calls kept
only as an automatic fallback if the dispatcher doesn't recognise a call
shape or raises — matching the rest of the platform's multi-context AKS
pattern.
"""

import json
import re

# ── Experiment ID sets (mirrors aks_safety_checks.py naming convention) ───────
TIME_CHAOS_IDS = frozenset({"aks-clock-skew-forward", "aks-clock-skew-backward"})
HTTP_CHAOS_IDS = frozenset({"aks-http-delay", "aks-http-abort"})
DNS_CHAOS_IDS  = frozenset({"aks-dns-failure"})
IO_CHAOS_IDS   = frozenset({"aks-io-latency", "aks-io-errors"})

# Cluster-plane experiments — target shared kube-system components (CoreDNS,
# kube-proxy) that every namespace/team on the cluster depends on. These are
# owned/operated by the SCP team, not an individual application team, so the
# checks below treat blast radius as cluster-wide by default, not namespace-scoped.
CLUSTER_PLANE_CHAOS_IDS = frozenset({
    "aks-coredns-kill", "aks-coredns-cpu", "aks-kube-proxy-kill",
})

# Timing-sensitive system names — these must never be targeted with clock skew.
# A process in this list present in the target namespace is a hard block.
_TIMING_SENSITIVE_APPS = frozenset({
    "etcd", "vault", "kafka", "zookeeper", "kerberos",
    "chronyd", "ntpd", "keycloak", "dex", "oidc",
    "cert-manager", "spire", "spiffe",
})

# Domain fragment patterns that indicate shared auth/secrets infrastructure.
# Any dns_pattern matching one of these is a hard block for DNSChaos.
_AUTH_DOMAIN_FRAGMENTS = (
    "sts.", "vault.", "oidc.", "oauth.", "auth.",
    "token.", "kerberos.", "ldap.", "ad.", "keycloak.",
    "cert-manager.", "accounts.google.", "login.microsoftonline.",
    "sts.amazonaws.", "cognito.",
)

# Maximum safe clock-skew offset before we hard-block (seconds).
# Beyond 5 minutes: TLS cert validity windows, JWT/OIDC token lifetimes,
# and Kerberos ticket windows all start failing silently or catastrophically.
_MAX_SAFE_SKEW_SECS = 300   # 5 minutes

# kubectl hard timeout (matches aks_safety_checks._KUBECTL_TIMEOUT)
_KUBECTL_TIMEOUT = "10s"
_PROC_TIMEOUT    = 30

# In-process DNS latency baseline: written by build_dns_chaos_pre_checks,
# read by build_dns_chaos_post_checks and verify_fault_active.
# Key: (aks_context, namespace, dns_pattern)
_DNS_LATENCY_CACHE: "dict[tuple, dict]" = {}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_chaos_crd(aks_context, crd_name):
    """
    Verify a Chaos Mesh CRD is installed. Returns (passed, detail).
    If missing, experiment will silently report success while injecting nothing.
    """
    r = _kubectl("get", "crd", crd_name, context=aks_context)
    detail = f"kubectl get crd {crd_name}"
    if r.returncode != 0:
        return False, (
            detail + f"\n  ✘ CRD '{crd_name}' not installed. "
            "Chaos Mesh will report the experiment succeeded while injecting nothing. "
            "Re-install Chaos Mesh with this CRD enabled before running this experiment."
        )
    return True, detail + f"\n  ✔ CRD '{crd_name}' present"


def _check_no_stale_chaos_crd(aks_context, kind):
    """
    Check for stale Chaos Mesh resources of `kind` in chaos-testing.
    If found, delete them automatically and pass — avoids double-injection
    risk without requiring manual cleanup between runs.
    """
    r = _kubectl("get", kind, "-n", "chaos-testing", "--no-headers", context=aks_context)
    detail = f"kubectl get {kind} -n chaos-testing"
    if r.returncode != 0:
        return True, detail + "\n  (query failed — assuming clean)"
    existing = [l.strip().split()[0] for l in r.stdout.strip().splitlines() if l.strip()]
    if not existing:
        return True, detail + f"\n  ✔ No stale {kind} resources"

    # Auto-delete with --wait=false so finalizer processing doesn't block the
    # pre-check timeout. Re-verify after a short wait to confirm deletion landed.
    import time as _time
    _kubectl("delete", kind, "--all", "-n", "chaos-testing", "--wait=false", context=aks_context)

    # Wait up to 10s for deletion to propagate, re-check every 2s
    _remaining = []
    for _ in range(5):
        _time.sleep(2)
        _r2 = _kubectl("get", kind, "-n", "chaos-testing", "--no-headers", context=aks_context)
        _remaining = [l.strip().split()[0] for l in _r2.stdout.strip().splitlines() if l.strip()] \
            if _r2.returncode == 0 else []
        if not _remaining:
            break

    if not _remaining:
        return True, (
            detail + f"\n  ⚠ Found stale {kind} resource(s): {existing}\n"
            f"  ✔ Auto-deleted — clean slate for new injection"
        )

    # Resources still present — stuck finalizers (deletionTimestamp set but
    # chaos-mesh/records finalizer blocking because AllRecovered=False).
    # Force-remove finalizers so Kubernetes can complete the deletion.
    _force_cleaned = []
    for _name in _remaining:
        _pr = _kubectl(
            "patch", kind, _name, "-n", "chaos-testing",
            "--type=json", '-p=[{"op":"remove","path":"/metadata/finalizers"}]',
            context=aks_context,
        )
        if _pr.returncode == 0:
            _force_cleaned.append(_name)

    # Final verify
    _time.sleep(1)
    _r3 = _kubectl("get", kind, "-n", "chaos-testing", "--no-headers", context=aks_context)
    _still_left = [l.strip().split()[0] for l in _r3.stdout.strip().splitlines() if l.strip()] \
        if _r3.returncode == 0 else []

    if not _still_left:
        return True, (
            detail + f"\n  ⚠ Found stale {kind} resource(s): {existing}\n"
            f"  ⚠ Stuck finalizers force-removed on: {_force_cleaned}\n"
            f"  ✔ All cleared — clean slate for new injection"
        )
    return False, (
        detail + f"\n  ✘ Stale {kind} resource(s) could not be cleared: {_still_left}\n"
        "  Manual cleanup required:\n"
        f"    kubectl patch {kind} <name> -n chaos-testing --type=json "
        "'-p=[{{\"op\":\"remove\",\"path\":\"/metadata/finalizers\"}}]'"
    )


def _kubectl(*args, context=None):
    """
    Run a kubectl-equivalent command. Tries the shared Python-client
    dispatcher (services.k8s_client.dispatch_kubectl) first — the same
    interception point used by actions/aks_safety_checks.py and
    actions/azure_aks_actions.py — and falls back to the real kubectl
    subprocess for anything the dispatcher doesn't recognise or that errors.
    """
    from chaosforge.providers.azure.components.aks.kubernetes import (
        run_kubernetes_command,
    )

    return run_kubernetes_command(
        args,
        context,
        timeout=_PROC_TIMEOUT,
        request_timeout=_KUBECTL_TIMEOUT,
    )


def _get_pods_json(aks_context, namespace, selector):
    """Return (pods_list, error_str). pods_list is None on failure."""
    r = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                 context=aks_context)
    if r.returncode != 0:
        return None, f"kubectl get pods failed: {r.stderr.strip()}"
    try:
        return json.loads(r.stdout).get("items", []), None
    except ValueError as exc:
        return None, f"Could not parse pods: {exc}"


def _get_deployment_json(aks_context, namespace, deployment):
    """Return (deployment_dict, error_str). deployment_dict is None on failure."""
    r = _kubectl("get", "deployment", deployment, "-n", namespace, "-o", "json",
                 context=aks_context)
    if r.returncode != 0:
        return None, f"kubectl get deployment failed: {r.stderr.strip()}"
    try:
        return json.loads(r.stdout), None
    except ValueError as exc:
        return None, f"Could not parse deployment: {exc}"


def _first_running_pod(aks_context, namespace, selector):
    """Return name of first Running pod matching selector, or None."""
    r = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                 context=aks_context)
    if r.returncode != 0:
        return None
    try:
        for pod in json.loads(r.stdout).get("items", []):
            if pod.get("status", {}).get("phase") == "Running":
                return pod.get("metadata", {}).get("name")
    except ValueError:
        pass
    return None


def _find_mounted_container(aks_context, namespace, pod, volume_path):
    """
    Return the name of the container in `pod` that actually has
    `volume_path` mounted (matching exactly or as a subpath), or "" if it
    can't be determined. Used so `kubectl exec` targets that container
    explicitly (via -c) on multi-container pods, instead of letting kubectl
    silently "Default" to an arbitrary container (often a logging/sidecar
    container with no shell) — the root cause of IOChaos probes failing with
    "Defaulted container ... out of: ..." on any pod with more than one
    container. Does not consider read-only vs read-write — for that, see
    _find_writable_probe_location().
    """
    r = _kubectl("get", "pod", pod, "-n", namespace, "-o", "json", context=aks_context)
    if r.returncode != 0:
        return ""
    try:
        containers = json.loads(r.stdout).get("spec", {}).get("containers", [])
    except ValueError:
        return ""
    _vpath = (volume_path or "/data").rstrip("/") or "/"
    for c in containers:
        mount_paths = [vm.get("mountPath", "") for vm in c.get("volumeMounts", [])]
        if any(
            _vpath == mp.rstrip("/") or _vpath.startswith(mp.rstrip("/") + "/")
            for mp in mount_paths if mp
        ):
            return c.get("name", "")
    return ""


def _find_writable_probe_location(aks_context, namespace, pod, volume_path):
    """
    Return (container_name, probe_path) for a writable location backed by
    the same underlying volume as `volume_path`, or ("", "") if it can't be
    determined. Used by the write+read+delete timing probes (baseline,
    live in-fault, residual post-check) — unlike _find_mounted_container,
    this one actively looks for a location the probe can WRITE to.

    Some pods mount the SAME underlying volume in more than one container at
    DIFFERENT paths with DIFFERENT access modes — e.g. an app container
    writing logs read-write, and a log-shipping sidecar mounting the same
    volume read-only to tail it. If the container whose path literally
    matches volume_path only has it mounted read-only, fall back to any
    OTHER container sharing the same underlying volume (matched by the
    pod's declared volume name, not by path) that has it mounted
    read-write, and probe there instead — IOChaos affects the whole
    underlying volume either way, but only a writable mount can prove real
    I/O with a self-contained write+read+delete probe.
    """
    r = _kubectl("get", "pod", pod, "-n", namespace, "-o", "json", context=aks_context)
    if r.returncode != 0:
        return "", ""
    try:
        containers = json.loads(r.stdout).get("spec", {}).get("containers", [])
    except ValueError:
        return "", ""
    _vpath = (volume_path or "/data").rstrip("/") or "/"

    def _matches(mp):
        return _vpath == mp.rstrip("/") or _vpath.startswith(mp.rstrip("/") + "/")

    matched_volume_name = None
    readonly_match = ("", "")
    for c in containers:
        for vm in c.get("volumeMounts", []):
            mp = vm.get("mountPath", "")
            if mp and _matches(mp):
                if not vm.get("readOnly", False):
                    return c.get("name", ""), _vpath
                matched_volume_name = vm.get("name")
                readonly_match = (c.get("name", ""), _vpath)

    # No container had volume_path itself mounted read-write — check whether
    # any OTHER container mounts the SAME underlying volume, read-write, at
    # a different path.
    if matched_volume_name:
        for c in containers:
            for vm in c.get("volumeMounts", []):
                if vm.get("name") == matched_volume_name and not vm.get("readOnly", False):
                    return c.get("name", ""), (vm.get("mountPath", "").rstrip("/") or "/")

    return readonly_match  # last resort: read-only match, or ("", "") if none found


def _measure_dns_latency(aks_context, namespace, selector, dns_pattern, n=10):
    """
    Exec into a running pod and resolve dns_pattern n times, recording wall-clock
    latency per attempt via `time` + nslookup/dig.  Returns a dict:
        {
            "n": <attempts>, "success": <count>, "latencies_ms": [...],
            "p50_ms": <int>, "p95_ms": <int>,
            "pod": <pod_name>, "tool": <"nslookup"|"dig"|None>
        }
    Returns None when no pod is available or no DNS tool exists in the container.
    """
    import time as _time
    pod = _first_running_pod(aks_context, namespace, selector)
    if not pod:
        return None

    # Detect available DNS tool by attempting a real lookup (one shot).
    # Avoids `command -v` which fails in busybox/minimal shells.
    tool = None
    for candidate, test_cmd, ok_fn in [
        ("nslookup", f"nslookup {dns_pattern} 2>&1",
         lambda r: "Address" in r.stdout or "answer" in r.stdout.lower()),
        ("dig",      f"dig +short +time=2 +tries=1 {dns_pattern} 2>&1",
         lambda r: bool(r.stdout.strip()) and r.returncode == 0),
        ("getent",   f"getent hosts {dns_pattern} 2>&1",
         lambda r: bool(r.stdout.strip()) and r.returncode == 0),
    ]:
        probe = _kubectl("exec", pod, "-n", namespace, "--",
                         "sh", "-c", test_cmd, context=aks_context)
        # An exec that never started (distroless image: no shell) is not
        # evidence that the tool exists — bail out entirely rather than
        # picking a tool that cannot run.
        _out = (probe.stdout or "") + (probe.stderr or "")
        if any(m in _out for m in (
            "executable file not found", "OCI runtime exec failed",
            "unable to start container process", "cannot exec in a stopped",
            "container not found",
        )):
            return None
        # returncode 127 = command not found; anything else means tool exists
        if probe.returncode != 127:
            tool = candidate
            break
    if tool is None:
        return None

    latencies = []
    success   = 0
    for _ in range(n):
        t0 = _time.monotonic()
        if tool == "nslookup":
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "sh", "-c", f"nslookup {dns_pattern} 2>&1", context=aks_context)
            resolved = r.returncode == 0 and (
                "Address" in r.stdout or "answer" in r.stdout.lower()
            )
        elif tool == "dig":
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "sh", "-c", f"dig +short +time=2 +tries=1 {dns_pattern} 2>&1",
                         context=aks_context)
            resolved = r.returncode == 0 and bool(r.stdout.strip())
        else:  # getent
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "sh", "-c", f"getent hosts {dns_pattern} 2>&1",
                         context=aks_context)
            resolved = r.returncode == 0 and bool(r.stdout.strip())
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        latencies.append(elapsed_ms)
        if resolved:
            success += 1

    if not latencies:
        return None

    sorted_lat = sorted(latencies)
    p50 = sorted_lat[int(len(sorted_lat) * 0.50)]
    p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
    return {
        "n": n, "success": success, "latencies_ms": latencies,
        "p50_ms": p50, "p95_ms": p95,
        "pod": pod, "tool": tool,
    }


def _get_workload_by_selector(aks_context, namespace, kind, selector):
    """
    Return (workload_dict, error_str) for the first `kind` (e.g. 'deployment',
    'daemonset') matching `selector` in `namespace`. workload_dict is None on
    failure or if nothing matches.
    """
    r = _kubectl("get", kind, "-n", namespace, "-l", selector, "-o", "json",
                 context=aks_context)
    if r.returncode != 0:
        return None, f"kubectl get {kind} failed: {r.stderr.strip()}"
    try:
        items = json.loads(r.stdout).get("items", [])
    except ValueError as exc:
        return None, f"Could not parse {kind} list: {exc}"
    return (items[0] if items else None), None


def _get_ready_node_count(aks_context):
    """Return (ready_count, total_count, error_str) for cluster nodes."""
    r = _kubectl("get", "nodes", "-o", "json", context=aks_context)
    if r.returncode != 0:
        return None, None, f"kubectl get nodes failed: {r.stderr.strip()}"
    try:
        nodes = json.loads(r.stdout).get("items", [])
    except ValueError as exc:
        return None, None, f"Could not parse node list: {exc}"
    ready = [
        n for n in nodes
        if any(c.get("type") == "Ready" and c.get("status") == "True"
               for c in n.get("status", {}).get("conditions", []))
    ]
    return len(ready), len(nodes), None


def _canary_pod(aks_context, exclude_namespaces=("kube-system", "chaos-testing")):
    """
    Return (pod_name, namespace) of a Running pod OUTSIDE the excluded
    namespaces, or (None, None) if none found.

    Rationale: cluster-plane experiments (CoreDNS/kube-proxy) have no natural
    blast-radius boundary — every namespace on the cluster depends on them.
    Validating from a pod in the *target's own* namespace (kube-system) proves
    nothing about impact to the app teams who actually depend on the service.
    A canary pod picked from an unrelated namespace gives a ground-truth signal
    for "did this affect workloads that never opted into this experiment".
    """
    r = _kubectl("get", "pods", "--all-namespaces", "-o", "json", context=aks_context)
    if r.returncode != 0:
        return None, None
    try:
        pods = json.loads(r.stdout).get("items", [])
    except ValueError:
        return None, None
    for pod in pods:
        ns = pod.get("metadata", {}).get("namespace", "")
        if ns in exclude_namespaces:
            continue
        if pod.get("status", {}).get("phase") != "Running":
            continue
        ready = any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in pod.get("status", {}).get("conditions", []))
        if ready:
            return pod.get("metadata", {}).get("name"), ns
    return None, None


def _parse_duration_to_secs(duration_str: str) -> float:
    """
    Parse a Chaos Mesh duration string (e.g. '5s', '100ms', '2m', '1h') to seconds.
    Returns 0.0 on parse failure.
    """
    s = (duration_str or "").strip().lower()
    m = re.match(r"^(\d+(?:\.\d+)?)(ms|s|m|h)$", s)
    if not m:
        return 0.0
    val, unit = float(m.group(1)), m.group(2)
    return {"ms": val / 1000, "s": val, "m": val * 60, "h": val * 3600}[unit]


def _parse_skew_offset_to_secs(offset_str: str) -> float:
    """
    Parse a Chaos Mesh timeOffset string (e.g. '+1h', '-30m', '+300s') to
    absolute seconds. Returns 0.0 on parse failure.
    """
    s = (offset_str or "").strip().lstrip("+-")
    return _parse_duration_to_secs(s)


# ═════════════════════════════════════════════════════════════════════════════
# TIME CHAOS (Clock Skew) — Pre-Checks
# ═════════════════════════════════════════════════════════════════════════════
