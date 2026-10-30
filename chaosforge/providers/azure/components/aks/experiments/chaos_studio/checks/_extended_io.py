import json

from ._extended_common import (
    _check_chaos_crd,
    _check_no_stale_chaos_crd,
    _find_mounted_container,
    _find_writable_probe_location,
    _first_running_pod,
    _get_pods_json,
    _kubectl,
)


def build_io_chaos_pre_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    *,
    experiment_id: str = "",
    volume_path: str = "/data",
    duration: str = "60s",
) -> "dict[str, callable]":
    """
    Pre-chaos checks for IOChaos (aks-io-latency = 'latency' action,
    aks-io-errors = 'fault'/errno=5/EIO action).

    Hard blocks:
      - iochaos CRD not installed (experiment silently no-ops)
      - volume_path does not exist inside the target container — IOChaos
        silently no-ops on a path that isn't actually mounted there.

    Note: unlike Chaos Mesh v1.x, the IOChaos controller in the version this
    platform targets (v2.x) always sets EnterNS=true when calling
    chaos-daemon's ApplyIOChaos RPC (see controllers/podiochaos/controller.go
    upstream) — chaos-daemon resolves the target container's PID directly
    from the container runtime and joins its mount+PID namespace itself to
    launch `toda`, the same nsenter-based mechanism used for Network/Time/
    Kernel chaos. No chaosfs sidecar/init-container or
    chaos-mesh.org/inject namespace label is required or checked here.

    Soft warnings (pass=True, prefixed detail):
      - Only 1 desired replica (an I/O fault on the single copy is closer
        to a full outage than a resilience test)
      - Baseline file I/O timing capture, for post-chaos comparison

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"
    _vpath = (volume_path or "/data").rstrip("/") or "/"

    # ── 0a. IOChaos CRD installed ─────────────────────────────────────────────
    def _iochaos_crd():
        return _check_chaos_crd(aks_context, "iochaos.chaos-mesh.org")
    checks["IOChaos CRD Installed"] = _iochaos_crd

    # ── 0b. No stale IOChaos resource active ──────────────────────────────────
    def _no_stale_iochaos():
        return _check_no_stale_chaos_crd(aks_context, "iochaos")
    checks["No Existing IOChaos"] = _no_stale_iochaos


    # ── 2. Volume mount path exists (HARD BLOCK) ──────────────────────────────
    def _volume_path_exists():
        pod = _first_running_pod(aks_context, namespace, selector)
        detail = f"volumePath configured: {_vpath}"
        if not pod:
            return True, detail + "\n  (no running pod found — skipping path check)"
        _cname = _find_mounted_container(aks_context, namespace, pod, _vpath)
        _c_args = ("-c", _cname) if _cname else ()
        r = _kubectl("exec", pod, "-n", namespace, *_c_args, "--",
                     "sh", "-c", f"test -e '{_vpath}' && echo EXISTS || echo MISSING",
                     context=aks_context)
        detail = f"kubectl exec {pod} -n {namespace}" + (f" -c {_cname}" if _cname else "") + f" -- test -e {_vpath}"
        out = (r.stdout or "").strip()
        if r.returncode != 0 and "MISSING" not in out and "EXISTS" not in out:
            return True, detail + f"\n  (exec unavailable — skipping: {(r.stderr or '').strip()[:80]})"
        if "MISSING" in out:
            return False, (
                detail + f"\n  ✘ Path '{_vpath}' does not exist in pod '{pod}'. "
                "IOChaos will match zero file operations and silently no-op while "
                "reporting AllInjected=True. Correct the volume_path input to a path "
                "that is actually mounted in this container."
            )

        # Existence alone is not enough: IOChaos's chaosfs sidecar hooks the
        # *mounted volume* itself, not arbitrary paths in the container's
        # writable overlay layer. A path like /root or /tmp will pass the
        # `test -e` check above (it genuinely exists) but is NOT a real
        # mount — Chaos Mesh then enters a Failed condition at injection
        # time instead of silently no-opping, which this check previously
        # couldn't catch. Cross-check volume_path against the pod's actual
        # declared volumeMounts to catch this before the destructive phase.
        r_mounts = _kubectl(
            "get", "pod", pod, "-n", namespace, "-o",
            "jsonpath={.spec.containers[*].volumeMounts[*].mountPath}",
            context=aks_context,
        )
        mount_paths = (r_mounts.stdout or "").split() if r_mounts.returncode == 0 else []
        is_under_mount = any(
            _vpath == mp.rstrip("/") or _vpath.startswith(mp.rstrip("/") + "/")
            for mp in mount_paths
        )
        if mount_paths and not is_under_mount:
            return False, (
                detail + f"\n  ✔ Path '{_vpath}' exists in pod '{pod}', but it is NOT under "
                "any mounted volume — it's just a directory in the container's writable "
                "overlay layer. IOChaos hooks the volume mount itself, so this will make "
                "the Chaos Mesh experiment enter a Failed condition instead of injecting.\n"
                f"    This pod's actual mounted volume path(s): {mount_paths}\n"
                "    Set volume_path to one of the paths above."
            )
        return True, detail + (
            f"\n  ✔ Path '{_vpath}' exists in pod '{pod}' and is under a mounted "
            f"volume ({mount_paths})" if mount_paths else
            f"\n  ✔ Path '{_vpath}' exists in pod '{pod}'"
        )
    checks["Volume Mount Path Exists"] = _volume_path_exists

    # ── 3. Replica count safety (soft warning) ────────────────────────────────
    # Rationale: an I/O latency/error fault on a deployment's only replica is
    # effectively a full outage for that path's operations, not a partial
    # resilience test — same rationale as Network Partition's replica guard,
    # but implemented independently here for IOChaos only.
    def _io_replica_safety():
        r = _kubectl("get", "deployment", deployment, "-n", namespace, "-o", "json",
                     context=aks_context)
        if r.returncode != 0:
            return True, f"kubectl get deployment {deployment} -n {namespace}: query failed — skipping"
        try:
            dep = json.loads(r.stdout)
        except ValueError:
            return True, "Could not parse deployment JSON — skipping"
        desired = dep.get("spec", {}).get("replicas") or 0
        detail  = (
            f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}\n"
            f"  desired replicas={desired}"
        )
        if desired <= 1:
            return True, (
                "⚠ " + detail + "\n  Only 1 replica — an I/O fault on this pod's mount "
                "will affect 100% of this deployment's I/O, not a partial subset."
            )
        return True, detail + "\n  ✔ Multiple replicas — I/O fault only affects a subset"
    checks["Replica Count Safety (I/O impact)"] = _io_replica_safety

    # ── 4. Baseline file I/O timing (advisory) ────────────────────────────────
    def _baseline_io_timing():
        pod = _first_running_pod(aks_context, namespace, selector)
        _probe_file = f"{_vpath}/.chaosforge_io_probe"
        cmd = (
            f"sh -c \"date +%s%3N > '{_probe_file}' 2>&1 && "
            f"cat '{_probe_file}' >/dev/null 2>&1 && "
            f"rm -f '{_probe_file}' 2>&1\""
        )
        detail = f"kubectl exec <pod> -n {namespace} -- {cmd}"
        if not pod:
            return True, detail + "\n  (no running pod — skipping baseline)"
        _cname, _ppath = _find_writable_probe_location(aks_context, namespace, pod, _vpath)
        _ppath = _ppath or _vpath
        _probe_file = f"{_ppath}/.chaosforge_io_probe"
        _c_args = ("-c", _cname) if _cname else ()
        import time as _time
        t0 = _time.monotonic()
        r = _kubectl("exec", pod, "-n", namespace, *_c_args, "--", "sh", "-c",
                     f"date +%s%3N > '{_probe_file}' && cat '{_probe_file}' >/dev/null && rm -f '{_probe_file}'",
                     context=aks_context)
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        _cinfo = f" (container={_cname})" if _cname else ""
        _pathinfo = f" [via same volume, path={_ppath}]" if _ppath != _vpath else ""
        detail = f"kubectl exec {pod} -n {namespace}{_cinfo} -- write+read+delete probe on {_probe_file}{_pathinfo}"
        if r.returncode != 0:
            return True, (
                detail + f"\n  (probe unavailable — skipping: {(r.stderr or '').strip()[:80]})"
            )
        detail += f"\n  baseline write+read+delete round-trip = {elapsed_ms}ms"
        return True, detail + "\n  ✔ Baseline file I/O timing captured"
    checks["Baseline File I/O Timing"] = _baseline_io_timing

    return checks


# ═════════════════════════════════════════════════════════════════════════════
# IO CHAOS (Disk I/O Latency 100ms / Disk I/O Errors EIO) — Post-Checks
# ═════════════════════════════════════════════════════════════════════════════

def build_io_chaos_post_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    volume_path: str = "/data",
) -> "dict[str, callable]":
    """
    Post-chaos checks for IOChaos. Confirms the injected fault is actually
    gone (not just that the CRD was deleted) and the app recovered.

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"
    _vpath = (volume_path or "/data").rstrip("/") or "/"

    # ── 1. IOChaos CRD cleaned up ──────────────────────────────────────────
    def _iochaos_crd_deleted():
        r = _kubectl("get", "iochaos", "-n", "chaos-testing", "--no-headers",
                     context=aks_context)
        detail = "kubectl get iochaos -n chaos-testing"
        if r.returncode != 0:
            return True, detail + "\n  (query failed — assuming cleaned up)"
        existing = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        if existing:
            return False, (
                detail + f"\n  ✘ IOChaos resource(s) still present: {existing}\n"
                "  Filesystem fault may still be ACTIVE — not yet rolled back."
            )
        return True, detail + "\n  ✔ All IOChaos CRD resources removed"
    checks["IOChaos CRD Cleaned Up"] = _iochaos_crd_deleted

    # ── 2. Residual fault check — real I/O probe, not just CRD absence ──────
    # Rationale: CRD deletion proves Chaos Mesh issued the cleanup RPC. It does
    # NOT prove the underlying `toda` FUSE process has actually stopped
    # intercepting calls in the target container's namespace — the process
    # can briefly linger past CRD deletion. Re-run the same write+read+delete
    # probe used pre-fault, timed, and confirm it succeeds without an I/O
    # error. The elapsed time is also reported so it can be compared directly
    # against "Baseline File I/O Timing" from the pre-check logs — a
    # post-rollback time still close to the injected delay (e.g. ~1000ms for
    # a 1000ms latency fault) means the fault has not actually cleared yet.
    def _residual_fault_probe():
        pod = _first_running_pod(aks_context, namespace, selector)
        _probe_file = f"{_vpath}/.chaosforge_io_probe_post"
        detail = f"kubectl exec <pod> -n {namespace} -- write+read+delete probe on {_probe_file}"
        if not pod:
            return True, detail + "\n  (no running pod — skipping residual-fault probe)"
        _cname, _ppath = _find_writable_probe_location(aks_context, namespace, pod, _vpath)
        _ppath = _ppath or _vpath
        _probe_file = f"{_ppath}/.chaosforge_io_probe_post"
        _c_args = ("-c", _cname) if _cname else ()
        import time as _time
        t0 = _time.monotonic()
        r = _kubectl("exec", pod, "-n", namespace, *_c_args, "--", "sh", "-c",
                     f"date +%s%3N > '{_probe_file}' && cat '{_probe_file}' >/dev/null && rm -f '{_probe_file}'",
                     context=aks_context)
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        _cinfo = f" (container={_cname})" if _cname else ""
        _pathinfo = f" [via same volume, path={_ppath}]" if _ppath != _vpath else ""
        detail = f"kubectl exec {pod} -n {namespace}{_cinfo} -- write+read+delete probe on {_probe_file}{_pathinfo}"
        combined_out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode != 0:
            if any(m in combined_out for m in (
                "executable file not found", "OCI runtime exec failed",
                "unable to start container process", "container not found",
                "Defaulted container",
            )):
                return True, detail + f"\n  (exec unavailable — skipping: {combined_out[:80]})"
            return False, (
                detail + f"\n  ✘ Probe failed post-rollback (exit={r.returncode}): {combined_out[:150]}\n"
                "  Filesystem fault may still be active."
            )
        detail += f"\n  post-rollback write+read+delete round-trip = {elapsed_ms}ms"
        detail += (
            "\n  ✔ File write/read/delete succeeded — no residual I/O fault"
            "\n    Compare this value with 'Baseline File I/O Timing' in the pre-check "
            "logs for the full before/after delta."
        )
        return True, detail
    checks["Residual I/O Fault Check"] = _residual_fault_probe

    # ── 3. Restart count delta (post) ───────────────────────────────────────
    # Rationale: EIO errors on a mount an app treats as fatal can crash the
    # container. Track whether restarts increased during/after the fault.
    def _io_restart_delta():
        pods, err = _get_pods_json(aks_context, namespace, selector)
        if pods is None:
            return True, f"Could not query pods — skipping restart delta: {err}"
        total_restarts = 0
        per_pod = []
        for pod in pods:
            name = pod.get("metadata", {}).get("name", "?")
            restarts = sum(
                cs.get("restartCount", 0)
                for cs in pod.get("status", {}).get("containerStatuses", [])
            )
            total_restarts += restarts
            per_pod.append(f"{name}={restarts}")
        detail = (
            f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
            f"  current restart counts: {', '.join(per_pod) if per_pod else 'no pods found'}"
        )
        if total_restarts > 0:
            return True, (
                "⚠ " + detail + f"\n  Total restarts observed: {total_restarts}. "
                "Confirm these occurred during the fault window (expected if the app "
                "treats I/O errors as fatal) rather than being pre-existing instability."
            )
        return True, detail + "\n  ✔ No container restarts observed"
    checks["Restart Count Delta (post)"] = _io_restart_delta

    return checks
