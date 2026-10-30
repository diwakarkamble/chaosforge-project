"""Stress and crashloop execution for AKS Chaos Studio experiments."""

from typing import Any

from .execution_support import executor_compatible

_get_node_conditions: Any = None
_get_node_io_wait: Any = None
_get_node_stress_workload_status: Any = None
_get_node_top: Any = None
_kubectl: Any = None
_probe_node_stress_canary: Any = None
_record_node_stress_impact: Any = None
_state_file: Any = None
_stress_pod_name: Any = None
CHAOS_NAMESPACE: Any = None
console: Any = None
json: Any = None
os: Any = None
tempfile: Any = None
time: Any = None

def _deploy_stress_pod(pod_name, manifest):
    """Write manifest to temp file, delete any old pod, apply, wait for Running."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     prefix="chaos-stress-", delete=False) as f:
        json.dump(manifest, f)
        tmppath = f.name
    try:
        _kubectl("delete", "pod", pod_name, "-n", CHAOS_NAMESPACE, "--ignore-not-found")
        time.sleep(2)
        r = _kubectl("apply", "-f", tmppath)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to deploy stress pod: {r.stderr.strip()}")
    finally:
        os.unlink(tmppath)

    print("[AKS Chaos] Waiting for stress pod to start...")
    for _ in range(30):
        r = _kubectl(
            "get", "pod", pod_name, "-n", CHAOS_NAMESPACE, "-o", "jsonpath={.status.phase}")
        phase = r.stdout.strip()
        if phase in ("Running", "Succeeded", "Completed"):
            return
        if phase in ("Failed", "Unknown"):
            raise RuntimeError(f"Stress pod failed to start: phase={phase}")
        time.sleep(2)
    raise RuntimeError("Stress pod did not reach Running state within 60s")


def _run_node_cpu_stress(node, ctx, *, ui=None):
    """Deploy a privileged stress-ng pod on the node to exhaust CPU."""
    from rich.live import Live
    from rich.text import Text

    duration_secs = int(ctx.get("duration", 60))
    pod_name      = _stress_pod_name("aks-node-cpu-stress", node)

    cpu_workers = 2
    try:
        r = _kubectl(
            "get", "node", node, "-o", "jsonpath={.status.allocatable.cpu}")
        raw_cpu = r.stdout.strip()
        if raw_cpu.endswith("m"):
            cpu_cores = max(1, int(raw_cpu[:-1]) // 1000)
        elif raw_cpu:
            cpu_cores = max(1, int(float(raw_cpu)))
        else:
            cpu_cores = 1
        cpu_workers = max(1, cpu_cores * 2)
    except Exception:
        cpu_workers = 2

    # Snapshot was captured in setup_studio pre-check phase; read it back from state.
    snapshot = ctx.get("_node_precheck_snapshot", {})
    ctx["_stress_snapshot"] = snapshot
    ctx["_stress_kind"]     = "cpu"
    state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
    with open(state_path, "w") as f:
        json.dump(ctx, f)

    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": CHAOS_NAMESPACE,
            "labels": {"app": "chaosforge-stress", "chaos-type": "node-cpu-stress"}
        },
        "spec": {
            "nodeName": node,
            "hostPID": True,
            "tolerations": [
                {"key": "CriticalAddonsOnly", "operator": "Exists"},
                {"key": "node-role.kubernetes.io/control-plane", "operator": "Exists"},
                {"key": "node-role.kubernetes.io/master", "operator": "Exists"},
            ],
            "containers": [{
                "name": "stress",
                "image": "alexeiled/stress-ng:latest-ubuntu",
                "command": ["stress-ng", "--cpu", str(cpu_workers), "--cpu-load", "100",
                            "--io", "2",
                            "--timeout", f"{duration_secs}s"],
                "securityContext": {"privileged": True},
            }],
            "restartPolicy": "Never",
        }
    }

    if ui:
        ui.step(f"Deploying CPU stress pod on node: {node}", live=True)
    _deploy_stress_pod(pod_name, manifest)

    peak_cpu      = None
    elapsed       = 0
    poll_interval = 15
    impact_probe_interval = 30
    TICK          = 0.5
    pod_status    = ""
    canary        = snapshot.get("canary")
    last_canary_probe_at = None

    def _render(remaining_secs):
        mins, secs = divmod(int(max(0, remaining_secs)), 60)
        timer      = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        bar_width  = 25
        filled     = int(bar_width * max(0, duration_secs - remaining_secs) / duration_secs) \
                     if duration_secs else bar_width
        bar        = "[green]" + "█" * filled + "[/green][dim]" + "░" * (bar_width - filled) + "[/dim]"
        extra      = f"  [dim]│[/dim]  [dim]{pod_status}[/dim]" if pod_status else ""
        return Text.from_markup(
            f"  [bold yellow]⚡[/bold yellow]  {bar}  [bold]{timer} remaining[/bold]{extra}"
        )

    max_iters = max(120, duration_secs // poll_interval + 40)

    with Live(_render(duration_secs), console=console,
              refresh_per_second=4, transient=True) as live:
        for _ in range(max_iters):
            remaining = max(0, duration_secs - elapsed)

            ticks = int(poll_interval / TICK)
            for tick in range(ticks, 0, -1):
                remaining = max(0, duration_secs - elapsed - (poll_interval - tick * TICK))
                live.update(_render(remaining))
                time.sleep(TICK)

            top = _get_node_top(node)
            r   = _kubectl(
                "get", "pod", pod_name, "-n", CHAOS_NAMESPACE, "-o", "jsonpath={.status.phase}")
            pod_phase = r.stdout.strip() or "Unknown"
            workload_status = _get_node_stress_workload_status(node)
            node_conds_during = _get_node_conditions(node)
            iowait_during = _get_node_io_wait(node, stress_pod_name=pod_name)
            canary_probe = None
            if canary and (last_canary_probe_at is None or elapsed - last_canary_probe_at >= impact_probe_interval):
                canary_probe = _probe_node_stress_canary(canary)
                last_canary_probe_at = elapsed
            _record_node_stress_impact(snapshot, workload_status, canary_probe,
                                       node_conditions=node_conds_during, iowait_pct=iowait_during)

            if top:
                cpu_pct = top["cpu_pct"]
                if peak_cpu is None or cpu_pct > peak_cpu:
                    peak_cpu = cpu_pct
                    snapshot["peak_cpu_pct"] = peak_cpu
                iowait_str = f"  iowait:{iowait_during}%" if iowait_during is not None else ""
                pod_status = (f"CPU: {top['cpu_pct']}% ({top['cpu_cores']})  "
                              f"MEM: {top['mem_pct']}%{iowait_str}  pod: {pod_phase}")
            else:
                pod_status = f"metrics unavailable  pod: {pod_phase}"

            if workload_status:
                pod_status += (f"  ready: {workload_status['ready_pods']}/{workload_status['total_pods']}"
                               f"  restarts:+{snapshot.get('max_restart_delta_during', 0)}")
            if canary_probe:
                pod_status += f"  {canary_probe['summary']}"
            elif snapshot.get("last_canary_summary"):
                pod_status += f"  {snapshot['last_canary_summary']}"

            if pod_phase in ("Failed", "Unknown") and elapsed > 10:
                live.console.print(
                    f"  [bold red]✘[/bold red]  [dim]Stress pod phase={pod_phase} — may have ended early[/dim]"
                )
                break

            elapsed += poll_interval
            if elapsed >= duration_secs or pod_phase in ("Succeeded", "Completed"):
                break

    if peak_cpu is not None:
        if ui:
            ui.step(f"Peak CPU during experiment: {peak_cpu}%", live=True)
        ctx["_stress_snapshot"]["peak_cpu_pct"] = peak_cpu
        state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
        with open(state_path, "w") as f:
            json.dump(ctx, f)

    if ui:
        ui.step("CPU stress complete — cleaning up stress pod", live=True)
    _kubectl("delete", "pod", pod_name, "-n", CHAOS_NAMESPACE, "--ignore-not-found")


def _run_node_memory_pressure(node, ctx, *, ui=None):
    """Deploy a privileged stress-ng pod on the node to exhaust memory."""
    from rich.live import Live
    from rich.text import Text

    duration_secs = int(ctx.get("duration", 60))
    pod_name      = _stress_pod_name("aks-node-memory-pressure", node)

    # Snapshot was captured in setup_studio pre-check phase; read it back from state.
    snapshot = ctx.get("_node_precheck_snapshot", {})
    ctx["_stress_snapshot"] = snapshot
    ctx["_stress_kind"]     = "memory"
    state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
    with open(state_path, "w") as f:
        json.dump(ctx, f)

    # Calculate target memory bytes dynamically based on node's actual free memory.
    # Goal: bring total node memory usage close to saturation regardless of what's already in use.
    # Formula: target = (node_total * 0.85) - current_used_bytes
    # This avoids OOM-kill on heavily loaded nodes by never requesting more than is free.
    TARGET_PCT = 1.00
    SAFETY_MARGIN_MB = 0
    top = snapshot.get("baseline_top") or _get_node_top(node)
    if top and top.get("mem_bytes"):
        try:
            # mem_bytes is like "3761Mi" — parse to bytes
            mem_used_str = top["mem_bytes"]
            mem_used_mb = int(mem_used_str.replace("Mi", "").replace("Gi", "000").strip())
            # Get node total allocatable memory in Mi
            r = _kubectl(
                "get", "node", node, "-o", "jsonpath={.status.allocatable.memory}")
            total_raw = r.stdout.strip()  # e.g. "31076180Ki"
            total_mb = int(total_raw.replace("Ki", "").strip()) // 1024
            target_mb = int(total_mb * TARGET_PCT) - mem_used_mb - SAFETY_MARGIN_MB
            target_mb = max(512, target_mb)  # never go below 512Mi
            vm_bytes_arg = f"{target_mb}M"
            limit_mb = target_mb + mem_used_mb  # container limit = target + current (no extra buffer)
        except Exception:
            vm_bytes_arg = "100%"
            limit_mb = None
    else:
        vm_bytes_arg = "100%"
        limit_mb = None

    resources = {"requests": {"memory": "100Mi"}}
    if limit_mb:
        resources["limits"] = {"memory": f"{limit_mb}Mi"}

    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": CHAOS_NAMESPACE,
            "labels": {"app": "chaosforge-stress", "chaos-type": "node-memory-stress"}
        },
        "spec": {
            "nodeName": node,
            "hostPID": True,
            "tolerations": [
                {"key": "CriticalAddonsOnly", "operator": "Exists"},
                {"key": "node-role.kubernetes.io/control-plane", "operator": "Exists"},
                {"key": "node-role.kubernetes.io/master", "operator": "Exists"},
            ],
            "containers": [{
                "name": "stress",
                "image": "alexeiled/stress-ng:latest-ubuntu",
                "command": ["stress-ng", "--vm", "1", "--vm-bytes", vm_bytes_arg,
                            "--vm-hang", "0", "--vm-keep",
                            "--io", "2",
                            "--timeout", f"{duration_secs}s"],
                "securityContext": {"privileged": True},
                "resources": resources,
            }],
            "restartPolicy": "Never",
        }
    }

    if ui:
        ui.step(f"Deploying memory stress pod on node: {node}", live=True)
    _deploy_stress_pod(pod_name, manifest)

    peak_mem      = None
    elapsed       = 0
    poll_interval = 15
    impact_probe_interval = 30
    TICK          = 0.5
    pod_status    = ""
    canary        = snapshot.get("canary")
    last_canary_probe_at = None

    def _render(remaining_secs):
        mins, secs = divmod(int(max(0, remaining_secs)), 60)
        timer      = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        bar_width  = 25
        filled     = int(bar_width * max(0, duration_secs - remaining_secs) / duration_secs) \
                     if duration_secs else bar_width
        bar        = "[green]" + "█" * filled + "[/green][dim]" + "░" * (bar_width - filled) + "[/dim]"
        extra      = f"  [dim]│[/dim]  [dim]{pod_status}[/dim]" if pod_status else ""
        return Text.from_markup(
            f"  [bold yellow]⚡[/bold yellow]  {bar}  [bold]{timer} remaining[/bold]{extra}"
        )

    max_iters = max(120, duration_secs // poll_interval + 40)

    with Live(_render(duration_secs), console=console,
              refresh_per_second=4, transient=True) as live:
        for _ in range(max_iters):
            remaining = max(0, duration_secs - elapsed)

            ticks = int(poll_interval / TICK)
            for tick in range(ticks, 0, -1):
                remaining = max(0, duration_secs - elapsed - (poll_interval - tick * TICK))
                live.update(_render(remaining))
                time.sleep(TICK)

            top = _get_node_top(node)
            r   = _kubectl(
                "get", "pod", pod_name, "-n", CHAOS_NAMESPACE, "-o", "jsonpath={.status.phase}")
            pod_phase = r.stdout.strip() or "Unknown"
            workload_status = _get_node_stress_workload_status(node)
            node_conds_during = _get_node_conditions(node)
            iowait_during = _get_node_io_wait(node, stress_pod_name=pod_name)
            canary_probe = None
            if canary and (last_canary_probe_at is None or elapsed - last_canary_probe_at >= impact_probe_interval):
                canary_probe = _probe_node_stress_canary(canary)
                last_canary_probe_at = elapsed
            _record_node_stress_impact(snapshot, workload_status, canary_probe,
                                       node_conditions=node_conds_during, iowait_pct=iowait_during)

            if top:
                mem_pct = top["mem_pct"]
                if peak_mem is None or mem_pct > peak_mem:
                    peak_mem = mem_pct
                    snapshot["peak_mem_pct"] = peak_mem
                iowait_str = f"  iowait:{iowait_during}%" if iowait_during is not None else ""
                pod_status = (f"MEM: {top['mem_pct']}% ({top['mem_bytes']})  "
                              f"CPU: {top['cpu_pct']}%{iowait_str}  pod: {pod_phase}")
            else:
                pod_status = f"metrics unavailable  pod: {pod_phase}"

            if workload_status:
                pod_status += (f"  ready: {workload_status['ready_pods']}/{workload_status['total_pods']}"
                               f"  restarts:+{snapshot.get('max_restart_delta_during', 0)}")
            if canary_probe:
                pod_status += f"  {canary_probe['summary']}"
            elif snapshot.get("last_canary_summary"):
                pod_status += f"  {snapshot['last_canary_summary']}"

            if pod_phase in ("Failed", "Unknown") and elapsed > 10:
                live.console.print(
                    f"  [bold red]✘[/bold red]  [dim]Stress pod phase={pod_phase} — may have ended early[/dim]"
                )
                break

            elapsed += poll_interval
            if elapsed >= duration_secs or pod_phase in ("Succeeded", "Completed"):
                break

    if peak_mem is not None:
        if ui:
            ui.step(f"Peak MEM during experiment: {peak_mem}%", live=True)
        ctx["_stress_snapshot"]["peak_mem_pct"] = peak_mem
        state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
        with open(state_path, "w") as f:
            json.dump(ctx, f)

    if ui:
        ui.step("Memory stress complete — cleaning up stress pod", live=True)
    _kubectl("delete", "pod", pod_name, "-n", CHAOS_NAMESPACE, "--ignore-not-found")


def _cleanup_stress_pod(experiment_id, node):
    """Force-delete the stress pod (called by rollback/cleanup)."""
    if not node:
        return
    pod_name = _stress_pod_name(experiment_id, node)
    print(f"[AKS Chaos] Cleaning up stress pod: {pod_name}")
    _kubectl("delete", "pod", pod_name, "-n", CHAOS_NAMESPACE, "--ignore-not-found", "--grace-period=0", "--force")


def _crashloop_podchaos_name(namespace, label_val):
    short = (label_val or "app")[:30]
    return f"chaosforge-crashloop-{namespace[:20]}-{short}"


def _resolve_target_pod(namespace, label_key, label_val, deployment, label_selectors_map=None):
    """
    Pick one pod to target — use deployment name directly if it looks like a
    pod name, else pick first matching pod. When label_selectors_map is
    provided (by the selector-scope validator), it's used in place of the
    single label_key=label_val pair to avoid matching sibling Deployments
    that share the same base labels.
    """
    # If deployment looks like a pod name (has 2+ dashes with hash segments), use it directly
    parts = deployment.split("-")
    if len(parts) >= 3 and len(parts[-1]) == 5 and len(parts[-2]) == 10:
        return deployment
    # Otherwise query pods matching the label selector and pick the first
    selector = (
        ",".join(f"{k}={v}" for k, v in label_selectors_map.items())
        if label_selectors_map else f"{label_key}={label_val}"
    )
    r = _kubectl(
        "get", "pods", "-n", namespace, "-l", selector, "-o", "jsonpath={.items[0].metadata.name}")
    return r.stdout.strip() or None


def _run_crashloop(ctx, *, ui=None):
    """Repeatedly apply/delete PodChaos container-kill to trigger CrashLoopBackOff.
    Respects chaos_mode — all modes resolve the exact target pods once at the start
    and pin every kill cycle to those specific pods, so the same set is hit every time."""
    namespace     = ctx.get("namespace") or "default"
    label_key     = ctx.get("label_key") or "app"
    label_val     = ctx.get("label_val") or ctx.get("deployment") or ""
    ctx.get("deployment") or ""
    container     = ctx.get("container_name") or ""
    duration_secs = int(ctx.get("duration") or 120)
    chaos_mode    = ctx.get("chaos_mode") or "one"
    chaos_value   = str(ctx.get("chaos_value") or "").strip()
    podchaos_name = _crashloop_podchaos_name(namespace, label_val)

    from chaosforge.interfaces.cli.interactive.ui.console import console as _console
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log import (
        crashloop_kill_event,
        crashloop_restart_detected,
        log_crashloop_event,
    )

    label_selectors_map = ctx.get("label_selectors_map")

    # ── Resolve the exact set of target pods upfront ─────────────────────────
    # Query all running pods matching the selector, then apply mode/value to
    # pick the exact subset. Every kill cycle targets this same set — no random
    # rotation across cycles that would hit more pods than the operator selected.
    if label_selectors_map:
        sel_str = ",".join(f"{k}={v}" for k, v in label_selectors_map.items())
    else:
        sel_str = f"{label_key}={label_val}"

    rp = _kubectl(
        "get", "pods", "-n", namespace, "-l", sel_str, "--field-selector=status.phase=Running", "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}")
    all_pods = [p.strip() for p in rp.stdout.strip().splitlines() if p.strip()]
    if not all_pods:
        raise RuntimeError(f"No running pods found matching selector '{sel_str}' in namespace {namespace}")

    # Determine how many pods to pick based on mode/value
    import math as _math
    import secrets as _secrets

    if chaos_mode == "one":
        target_pods = all_pods[:1]
    elif chaos_mode == "all":
        target_pods = all_pods
    elif chaos_mode == "fixed":
        n = int(chaos_value) if chaos_value.isdigit() else 1
        n = max(1, min(n, len(all_pods)))
        target_pods = all_pods[:n]
    elif chaos_mode == "fixed-percent":
        pct = float(chaos_value) if chaos_value else 50.0
        n   = max(1, _math.ceil(len(all_pods) * pct / 100))
        target_pods = all_pods[:n]
    elif chaos_mode == "random-max-percent":
        pct = float(chaos_value) if chaos_value else 50.0
        max_n = max(1, _math.ceil(len(all_pods) * pct / 100))
        n     = _secrets.randbelow(max_n) + 1
        target_pods = all_pods[:n]
    else:
        target_pods = all_pods[:1]

    # Build selector using fieldSelectors — one entry per pod joined with OR via
    # separate kills. For a single pod we use fieldSelectors directly.
    # For multiple pods we issue one PodChaos per pod (mode: one, pinned by name)
    # so every target pod gets its own kill CR each cycle, using the proven
    # fieldSelectors format that works across all Chaos Mesh versions.
    if len(target_pods) == 1:
        pass  # single pod handled uniformly below via _make_manifest
    else:
        pass  # multiple pods also handled below via _make_manifest per pod

    target_display = (
        f"pods=[bold]{', '.join(target_pods)}[/bold]  "
        f"({len(target_pods)}/{len(all_pods)} selected)"
    )
    poll_selector = ",".join(f"{k}={v}" for k, v in (label_selectors_map or {label_key: label_val}).items())

    def _make_manifest(pod_name, cr_name):
        """Build a PodChaos CR pinned to one pod using fieldSelectors (proven format)."""
        spec = {
            "action":      "container-kill",
            "mode":        "one",
            "selector": {
                "namespaces":     [namespace],
                "fieldSelectors": {"metadata.name": pod_name},
            },
            "gracePeriod": 0,
        }
        if container:
            spec["containerNames"] = [container]
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind":       "PodChaos",
            "metadata":   {"name": cr_name, "namespace": CHAOS_NAMESPACE},
            "spec":       spec,
        }

    # CR names — one per target pod, stable across cycles (deleted + recreated each cycle)
    cr_names = [f"{podchaos_name}-{i}" for i in range(len(target_pods))]

    log_crashloop_event(
        _console, "CHAOS",
        f"CrashLoopBackOff starting — {target_display}  "
        f"namespace=[bold]{namespace}[/bold]  duration=[bold]{duration_secs}s[/bold]",
    )

    def _delete_all_crs():
        for cr in cr_names:
            _kubectl("delete", "podchaos", cr, "-n", CHAOS_NAMESPACE, "--ignore-not-found")

    # Clean up any leftover from a previous run
    _delete_all_crs()

    start    = time.time()
    kill_num = 0
    # Kill every ~20s: create one PodChaos CR per target pod (fieldSelectors, mode one),
    # hold 5s so Chaos Mesh controller has time to reconcile and execute,
    # then delete all CRs and wait 5s before next cycle.
    while time.time() - start < duration_secs:
        applied = []
        for pod_name, cr_name in zip(target_pods, cr_names):
            manifest = _make_manifest(pod_name, cr_name)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                             prefix="chaos-crashloop-", delete=False) as f:
                json.dump(manifest, f)
                tmppath = f.name
            try:
                r = _kubectl("apply", "-f", tmppath)
                if r.returncode != 0:
                    raise RuntimeError(f"Failed to apply PodChaos for {pod_name}: {r.stderr.strip()}")
                applied.append(pod_name)
            finally:
                os.unlink(tmppath)

        kill_num += 1
        elapsed   = int(time.time() - start)
        remaining = max(0, duration_secs - elapsed)
        ev = crashloop_kill_event(kill_num, ", ".join(applied), remaining)
        log_crashloop_event(_console, ev["severity"], ev["message"])

        # Hold long enough for Chaos Mesh controller to reconcile and execute the kill
        time.sleep(5)
        _delete_all_crs()

        # Wait for containers to restart, then report CrashLoopBackOff
        time.sleep(5)
        _rr = _kubectl(
            "get", "pods", "-n", namespace, "-l", poll_selector, "--no-headers")
        for _row in (_rr.stdout.strip().splitlines() if _rr.returncode == 0 else []):
            _parts = _row.split()
            if len(_parts) >= 4 and _parts[3] != "0" and _parts[0] in target_pods:
                try:
                    _rc = int(_parts[3])
                except ValueError:
                    _rc = 0
                if _rc > 0:
                    ev2 = crashloop_restart_detected(_parts[0], _rc)
                    log_crashloop_event(_console, ev2["severity"], ev2["message"])

    log_crashloop_event(
        _console, "SUCCESS",
        f"CrashLoop complete — [bold]{kill_num}[/bold] kills applied  {target_display}",
    )


def _cleanup_crashloop(ctx):
    """Remove all PodChaos CRs created by crashloop experiment on rollback."""
    namespace  = ctx.get("namespace") or "default"
    label_val  = ctx.get("label_val") or ctx.get("deployment") or ""
    base_name  = _crashloop_podchaos_name(namespace, label_val)
    print(f"[AKS Chaos] Cleaning up crashloop PodChaos: {base_name}*")
    # Delete base name + any indexed variants (multi-pod: base-0, base-1, ...)
    r = _kubectl(
        "get", "podchaos", "-n", CHAOS_NAMESPACE, "-o", "jsonpath={.items[*].metadata.name}")
    names = r.stdout.strip().split() if r.returncode == 0 else []
    for name in names:
        if name == base_name or name.startswith(f"{base_name}-"):
            _kubectl("delete", "podchaos", name, "-n", CHAOS_NAMESPACE, "--ignore-not-found")









_EXPORTED_FUNCTIONS = (
    "_deploy_stress_pod",
    "_run_node_cpu_stress",
    "_run_node_memory_pressure",
    "_cleanup_stress_pod",
    "_crashloop_podchaos_name",
    "_resolve_target_pod",
    "_run_crashloop",
    "_cleanup_crashloop",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update({name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS})
globals().update(_LOCAL_EXPORTS)
__all__ = list(_EXPORTED_FUNCTIONS)
