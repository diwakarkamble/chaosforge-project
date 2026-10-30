"""Extracted AKS Chaos Studio operations."""

from typing import Any

from .execution_support import executor_compatible

_build_studio_experiment_object: Any = None
_capture_missing_net_baseline: Any = None
_extract_net_metrics: Any = None
_kubectl: Any = None
_read_chaos_target_pods: Any = None
_read_io_baseline_ms: Any = None
_read_restart_total: Any = None
_save_state_field: Any = None
_target_selection_preview: Any = None
datetime: Any = None
IO_CHAOS_EXPERIMENTS: Any = None
json: Any = None
KUBE_SYSTEM_EXPERIMENTS: Any = None
NETWORK_CHAOS_EXPERIMENTS: Any = None
POD_PINNING_CAPABLE_EXPERIMENTS: Any = None
time: Any = None
timezone: Any = None
verify_fault_active: Any = None

def _run_studio_experiment(exp_name, json_spec, capability_urn, sub, chaos_rg, cluster, ctx,
                           *, ui=None, session=None):
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.chaos import ChaosManagementClient

    from chaosforge.interfaces.cli.interactive.ui.console import console
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log import (
        format_experiment_start,
        log_line,
        log_stress_metrics,
    )

    duration_secs = int(ctx.get("duration", 60))
    client        = ChaosManagementClient(DefaultAzureCredential(), sub)
    cluster_rg    = ctx.get("resource_group", chaos_rg)

    # If setup already created the ARM resource, skip begin_create_or_update.
    if not ctx.get("_experiment_pre_created"):
        experiment = _build_studio_experiment_object(json_spec, capability_urn, sub, cluster_rg, cluster, ctx)
        client.experiments.begin_create_or_update(chaos_rg, exp_name, experiment).result()
        if ui:
            ui.step(f"Studio experiment created: {exp_name}")

    import threading as _threading

    from rich.live import Live
    from rich.text import Text

    # Two poll cadences:
    #   pre-running : 5s  — tighter loop so we catch the Running transition quickly
    #   running     : 10s — matches fault window granularity; saves API calls
    POLL_PRE_RUNNING = 5
    POLL_RUNNING     = 10
    TICK_INTERVAL    = 0.5   # inner sleep; gives smooth countdown without extra kubectl

    elapsed          = 0
    running          = False
    fault_status      = ""
    terminal_ok       = False
    terminal_status   = ""
    _seen_killed: set = set()
    _pod_probe_accum  = 0.0
    _last_status_msg  = ""   # dedup: only print when status message changes
    _actual_target_logged = False  # print actual Chaos Mesh target pods once
    _targeted_pods: list = []
    _restart_baseline = None
    _just_started     = False  # burst-probe flag: catch Terminating window at fault start
    _net_pre_fault: dict   = {}    # first-poll snapshot (before fault active)
    _net_peak: dict        = {}    # worst values while fault is CHAOS-severity
    _io_pre_fault: dict    = {}    # IOChaos baseline (pre-fault write+read+delete ms)
    _io_peak: dict         = {}    # IOChaos worst round-trip ms observed while CHAOS-severity
    _fault_confirmed: bool = False # whether AllInjected=True was observed

    # begin_start blocks for 5–25s while Azure schedules the fault.
    # Fire it in a background thread so the Live timer renders immediately
    # and the operator sees activity rather than a frozen terminal.
    _start_error: list = []   # filled by thread on failure

    def _do_start():
        try:
            client.experiments.begin_start(chaos_rg, exp_name).result()
            if session:
                session.log_event("experiment", f"Experiment started: {exp_name}")
        except Exception as exc:
            _start_error.append(exc)

    _start_thread = _threading.Thread(target=_do_start, daemon=True)
    _start_thread.start()

    def _render(remaining_secs):
        mins, secs  = divmod(int(max(0, remaining_secs)), 60)
        timer       = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        bar_width   = 25
        filled      = int(bar_width * max(0, duration_secs - remaining_secs) / duration_secs) \
                      if duration_secs else bar_width
        bar         = "[green]" + "█" * filled + "[/green][dim]" + "░" * (bar_width - filled) + "[/dim]"
        _fs_summary = fault_status.get("message", "") if isinstance(fault_status, dict) else fault_status
        pod_part    = f"  [dim]│[/dim]  [dim]{_fs_summary}[/dim]" if _fs_summary else ""
        # Show a "starting" label until begin_start returns
        if _start_thread.is_alive():
            return Text.from_markup(
                "  [bold yellow]⚡[/bold yellow]  [dim]Starting experiment...[/dim]"
            )
        return Text.from_markup(
            f"  [bold yellow]⚡[/bold yellow]  {bar}  [bold]{timer} remaining[/bold]{pod_part}"
        )

    # Upper bound on iterations: use the tighter pre-running interval for sizing
    max_iters = max(120, duration_secs // POLL_PRE_RUNNING + 40)

    # Resolve the actual pod names that Chaos Mesh will target (read-only kubectl)
    _target_pods: list = []
    _cp_component = ""
    try:
        _exp_id = ctx.get("experiment_id", "")
        if _exp_id in KUBE_SYSTEM_EXPERIMENTS:
            # namespace/deployment are intentionally None here — these
            # experiments have no app-level target, only a fixed kube-system component.
            from .checks._extended_cluster_plane import _CLUSTER_PLANE_TARGETS
            _cp_target    = _CLUSTER_PLANE_TARGETS.get(_exp_id, {})
            _cp_component = _cp_target.get("component", "")
            _ns  = "kube-system"
            _sel = _cp_target.get("selector", "")
        else:
            _ns  = ctx.get("namespace", "")
            # Use corrected selector from validator when present (handles label collisions)
            _label_map = ctx.get("label_selectors_map")
            if _label_map:
                _sel = ",".join(f"{k}={v}" for k, v in _label_map.items())
            else:
                _lk  = ctx.get("label_key", "")
                _lv  = ctx.get("label_val", "")
                _dep = ctx.get("deployment", "")
                _sel = f"{_lk}={_lv}" if (_lk and _lv) else f"app={_dep}"
        _exact_pod_name = (
            ctx.get("exact_pod_name", "")
            if ctx.get("experiment_id") in POD_PINNING_CAPABLE_EXPERIMENTS else ""
        )
        _selection_args = (
            ["--field-selector", f"metadata.name={_exact_pod_name}"]
            if _exact_pod_name else ["-l", _sel]
        )
        _rp  = _kubectl(
            "get", "pods", "-n", _ns, *_selection_args, "--no-headers", "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase")
        if _rp.returncode == 0:
            for _row in _rp.stdout.strip().splitlines():
                _parts = _row.split()
                if _parts:
                    _status = _parts[1] if len(_parts) > 1 else "Unknown"
                    _target_pods.append(f"{_parts[0]}  ({_status})")
    except Exception:
        pass

    _display_pods, _target_summary = _target_selection_preview(
        _target_pods,
        ctx.get("chaos_mode", "one"),
        ctx.get("chaos_value", ""),
    )
    if ctx.get("experiment_id") in NETWORK_CHAOS_EXPERIMENTS:
        _restart_baseline = _read_restart_total(
            _ns, _sel, ctx.get("aks_context", ""), ctx.get("exact_pod_name", "")
        )
        if _restart_baseline is not None:
            _net_pre_fault["restarts"] = _restart_baseline
    if ctx.get("experiment_id") in IO_CHAOS_EXPERIMENTS:
        # Prefer the number the pre-check already measured (shown to the
        # operator during PHASE 2) so "Before fault" in the final summary
        # always matches what was printed there. Only fall back to a fresh
        # probe if the pre-check's value wasn't captured for some reason
        # (e.g. the operator overrode a failed pre-check).
        _io_baseline_ms = ctx.get("_io_baseline_ms")
        if _io_baseline_ms is None:
            _io_baseline_ms = _read_io_baseline_ms(
                _ns, _sel, ctx.get("aks_context", ""), ctx.get("volume_path", "/data")
            )
        if _io_baseline_ms is not None:
            _io_pre_fault["io_ms"] = _io_baseline_ms

    # Print experiment start banner before the Live timer begins
    for line in format_experiment_start(
        ctx.get("experiment_id", ""),
        _ns,
        _cp_component or ctx.get("deployment", ""),
        duration_secs,
        dry_run=False,
        target_pods=_display_pods,
        target_summary=_target_summary,
        chaos_mode=ctx.get("chaos_mode", "one"),
    ):
        console.print(line)

    with Live(_render(duration_secs), console=console,
              refresh_per_second=4, transient=True) as live:
        # Wait for begin_start outside the max_iters loop so slow Studio provisioning
        # (e.g. 70s+ for some namespaces) does not exhaust the iteration budget before
        # the experiment even starts. begin_start has no upper-bound timeout from Azure
        # so we wait indefinitely here — the operator can Ctrl-C if needed.
        while _start_thread.is_alive():
            live.update(_render(duration_secs))
            time.sleep(TICK_INTERVAL)

        for _ in range(max_iters):

            # Propagate any error from begin_start
            if _start_error:
                raise RuntimeError(
                    f"begin_start failed for {exp_name}: {_start_error[0]}"
                )

            # ── Azure status poll ────────────────────────────────────────────
            try:
                execs = list(client.experiments.list_all_executions(chaos_rg, exp_name))
                if execs:
                    exe    = client.experiments.get_execution(chaos_rg, exp_name, execs[0].name)
                    status = exe.status
                    if not running and status == "Running":
                        running       = True
                        _just_started = True
                        if session:
                            session.log_event("experiment", "Fault Running")
                    if status in ("Succeeded", "Success", "Failed", "Cancelled"):
                        terminal_ok     = status in ("Succeeded", "Success")
                        terminal_status = status
                        if session:
                            session.log_event("experiment", f"Terminal status: {status}")
                        break
            except RuntimeError:
                raise
            except Exception as e:
                live.update(Text.from_markup(
                    f"  [dim yellow]⚠  Polling error (retrying): {e}[/dim yellow]"
                ))

            # ── Burst-probe: catch the short Terminating window at fault start ──
            # The Terminating phase lasts ~1-3s; the normal 10s poll cadence misses it.
            # Fire 3 quick probes at 0.5s intervals the moment Running is first observed.
            if _just_started:
                _just_started = False
                from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log import (
                    pod_kill_event as _pke,
                )
                for _ in range(3):
                    time.sleep(TICK_INTERVAL)
                    _prev = set(_seen_killed)
                    try:
                        _fs = verify_fault_active(
                            ctx.get("experiment_id", ""),
                            ctx.get("aks_context", ""),
                            ctx.get("namespace", ""),
                            ctx.get("deployment", ""),
                            ctx.get("label_key", ""),
                            ctx.get("label_val", ""),
                            session=session,
                            _seen_killed=_seen_killed,
                            label_selectors_map=ctx.get("label_selectors_map"),
                            target_pod_names=_targeted_pods,
                            restart_baseline=_restart_baseline,
                            exact_pod_name=ctx.get("exact_pod_name", ""),
                            volume_path=ctx.get("volume_path", "/data"),
                        )
                    except Exception:
                        _fs = None
                    if _fs and isinstance(_fs, dict):
                        if "net_rows" in _fs:
                            ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log import (
                                log_net_metrics,
                            )
                            log_net_metrics(live, ts_now, _fs)
                            _m = _extract_net_metrics(_fs.get("net_rows", []))
                            _capture_missing_net_baseline(_net_pre_fault, _m)
                            if _fs.get("severity") == "CHAOS":
                                _fault_confirmed = True
                                for _k, _v in _m.items():
                                    if _k == "endpoints_ready":
                                        _net_peak[_k] = min(_net_peak.get(_k, 9999), _v)
                                    elif _k == "endpoints_total":
                                        _net_peak[_k] = _v
                                    elif isinstance(_v, (int, float)):
                                        _net_peak[_k] = max(_net_peak.get(_k, 0), _v)
                        elif "io_ms" in _fs:
                            _msg = _fs.get("message", "")
                            if _msg and _msg != _last_status_msg:
                                _last_status_msg = _msg
                                ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                                log_line(live, _fs.get("severity", "INFO"), _msg, ts=ts_now)
                            if _fs.get("crd_injected"):
                                _fault_confirmed = True
                                _io_ms_val = _fs.get("io_ms")
                                if isinstance(_io_ms_val, (int, float)):
                                    _io_peak["io_ms"] = max(_io_peak.get("io_ms", 0), _io_ms_val)
                        else:
                            _msg = _fs.get("message", "")
                            if _msg and _msg != _last_status_msg:
                                _last_status_msg = _msg
                                ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                                log_line(live, _fs.get("severity", "INFO"), _msg, ts=ts_now)
                    for _pn in (_seen_killed - _prev):
                        ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                        _ev = _pke(_pn)
                        log_line(live, _ev["severity"], _ev["message"], ts=ts_now)
                    live.update(_render(max(0, duration_secs - elapsed)))

            # ── One-time: resolve which pod Chaos Mesh actually targeted ─────
            # mode=one means Chaos Mesh picks a single pod from the selector pool
            # at injection time. The CRD status.experiment field records the actual
            # target. Log it once so the operator knows exactly which pod to watch.
            if running and not _actual_target_logged:
                try:
                    _crd_kind_map = {
                        "aks-dns-failure":        "dnschaos",
                        "aks-http-delay":         "httpchaos",
                        "aks-http-abort":         "httpchaos",
                        "aks-clock-skew-forward": "timechaos",
                        "aks-clock-skew-backward":"timechaos",
                        "aks-pod-kill":           "podchaos",
                        "aks-pod-failure":        "podchaos",
                        "aks-container-kill":     "podchaos",
                        "aks-crashloop":          "podchaos",
                        "aks-cpu-stress":         "stresschaos",
                        "aks-memory-stress":      "stresschaos",
                        "aks-coredns-kill":       "podchaos",
                        "aks-coredns-cpu":        "stresschaos",
                        "aks-kube-proxy-kill":    "podchaos",
                        "aks-network-delay":      "networkchaos",
                        "aks-packet-loss":        "networkchaos",
                        "aks-bandwidth-limit":    "networkchaos",
                        "aks-packet-corruption":  "networkchaos",
                        "aks-packet-duplication": "networkchaos",
                        "aks-network-partition":  "networkchaos",
                        "aks-io-latency":         "iochaos",
                        "aks-io-errors":          "iochaos",
                    }
                    _eid    = ctx.get("experiment_id", "")
                    _ckind  = _crd_kind_map.get(_eid)
                    _actx   = ctx.get("aks_context", "")
                    if _ckind and _actx:
                        if _eid in NETWORK_CHAOS_EXPERIMENTS:
                            _targeted_pods = _read_chaos_target_pods(_ckind, _actx)
                        else:
                            _legacy = _kubectl(
                                "get", _ckind, "-n", "chaos-testing", "-o", "json", context=_actx, timeout=10)
                            if _legacy.returncode == 0:
                                # Multiple podchaos CRDs can exist in chaos-testing at
                                # once (stale ones from other/older runs that weren't
                                # cleaned up). Picking the first one with a populated
                                # status.experiment silently reported the wrong pod
                                # (e.g. an unrelated leftover CR) instead of this run's
                                # own target. Scope candidates to this run's namespace
                                # and, among matches, pick the most recently created —
                                # that is always this run's own CRD.
                                _ns = ctx.get("namespace", "")
                                _candidates = []
                                for _crd in json.loads(_legacy.stdout).get("items", []):
                                    _crd_ns = (
                                        _crd.get("spec", {}).get("selector", {}).get("namespaces")
                                        or []
                                    )
                                    if _ns and _crd_ns and _ns not in _crd_ns:
                                        continue
                                    _exp = _crd.get("status", {}).get("experiment", {})
                                    _records = (
                                        _exp.get("containerRecords")
                                        or _exp.get("podRecords")
                                        or _exp.get("records")
                                    )
                                    if _records:
                                        _candidates.append((
                                            _crd.get("metadata", {}).get("creationTimestamp", ""),
                                            _records,
                                        ))
                                if _candidates:
                                    _candidates.sort(key=lambda c: c[0])
                                    _records = _candidates[-1][1]
                                    _targeted_pods = (
                                        [r.get("id", "?").split("/")[-1] for r in _records]
                                        if isinstance(_records, list)
                                        else list(_records.keys())
                                    )
                        if _targeted_pods:
                            _actual_target_logged = True
                            ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            _cmode = ctx.get("chaos_mode", "one")
                            if _eid in NETWORK_CHAOS_EXPERIMENTS:
                                _tlabel = (
                                    "actual target pod" if _cmode == "one"
                                    else f"actual targeted pods (mode={_cmode})"
                                )
                            else:
                                _tlabel = (
                                    "actual target pod" if _cmode == "one"
                                    else f"targeted pods (mode={_cmode})"
                                )
                            log_line(
                                live, "CHAOS",
                                f"Chaos Mesh {_tlabel}: [bold]{', '.join(_targeted_pods)}[/bold]",
                                ts=ts_now,
                            )
                            if session:
                                session.log_event(
                                    "experiment",
                                    f"Actual targeted pod(s): {_targeted_pods}",
                                )
                except Exception:
                    pass

            # ── Sub-second tick loop: smooth countdown + pod probe every 2s ──
            poll_interval = POLL_RUNNING if running else POLL_PRE_RUNNING
            ticks         = int(poll_interval / TICK_INTERVAL)
            for tick in range(ticks, 0, -1):
                if running:
                    remaining        = max(0, duration_secs - elapsed - (poll_interval - tick * TICK_INTERVAL))
                    _pod_probe_accum += TICK_INTERVAL
                    if _pod_probe_accum >= 2.0:
                        _pod_probe_accum = 0.0
                        prev_killed = set(_seen_killed)
                        try:
                            fault_status = verify_fault_active(
                                ctx.get("experiment_id", ""),
                                ctx.get("aks_context", ""),
                                ctx.get("namespace", ""),
                                ctx.get("deployment", ""),
                                ctx.get("label_key", ""),
                                ctx.get("label_val", ""),
                                session=session,
                                _seen_killed=_seen_killed,
                                label_selectors_map=ctx.get("label_selectors_map"),
                                target_pod_names=_targeted_pods,
                                restart_baseline=_restart_baseline,
                                exact_pod_name=ctx.get("exact_pod_name", ""),
                                volume_path=ctx.get("volume_path", "/data"),
                            )
                        except Exception:
                            pass
                        if isinstance(fault_status, dict) and "pod_rows" in fault_status:
                            # Stress metrics: always print (values change continuously)
                            ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            log_stress_metrics(live, ts_now, fault_status)
                        elif isinstance(fault_status, dict) and "net_rows" in fault_status:
                            # Network metrics: always print (values change continuously)
                            ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log import (
                                log_net_metrics,
                            )
                            log_net_metrics(live, ts_now, fault_status)
                            # ── Peak tracking ────────────────────────────────
                            _m = _extract_net_metrics(fault_status.get("net_rows", []))
                            _capture_missing_net_baseline(_net_pre_fault, _m)
                            _sev = fault_status.get("severity", "")
                            if _sev == "CHAOS":
                                _fault_confirmed = True
                                for _k, _v in _m.items():
                                    if _k == "endpoints_ready":
                                        _net_peak[_k] = min(_net_peak.get(_k, 9999), _v)
                                    elif _k == "endpoints_total":
                                        _net_peak[_k] = _v
                                    elif isinstance(_v, (int, float)):
                                        _net_peak[_k] = max(_net_peak.get(_k, 0), _v)
                        elif isinstance(fault_status, dict) and "io_ms" in fault_status:
                            _msg = fault_status.get("message", "")
                            if _msg and _msg != _last_status_msg:
                                _last_status_msg = _msg
                                ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                                log_line(live, fault_status.get("severity", "INFO"),
                                         _msg, ts=ts_now)
                            if fault_status.get("crd_injected"):
                                _fault_confirmed = True
                                _io_ms_val = fault_status.get("io_ms")
                                if isinstance(_io_ms_val, (int, float)):
                                    _io_peak["io_ms"] = max(_io_peak.get("io_ms", 0), _io_ms_val)
                        elif isinstance(fault_status, dict):
                            # State events: only print when the message changes
                            _msg = fault_status.get("message", "")
                            if _msg and _msg != _last_status_msg:
                                _last_status_msg = _msg
                                ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                                log_line(live, fault_status.get("severity", "INFO"),
                                         _msg, ts=ts_now)
                        for pod_name in (_seen_killed - prev_killed):
                            from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log import (
                                pod_kill_event,
                            )
                            ts_now = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            ev = pod_kill_event(pod_name)
                            log_line(live, ev["severity"], ev["message"], ts=ts_now)
                    live.update(_render(remaining))
                time.sleep(TICK_INTERVAL)

            if running:
                elapsed += poll_interval

    # Save network peak metrics to state so cleanup_experiment can print the summary
    if _net_pre_fault or _net_peak:
        _save_state_field(ctx, "_net_pre_fault",    _net_pre_fault)
        _save_state_field(ctx, "_net_peak",         _net_peak)
        _save_state_field(ctx, "_fault_confirmed",  _fault_confirmed)
    if _io_pre_fault or _io_peak:
        _save_state_field(ctx, "_io_pre_fault",     _io_pre_fault)
        _save_state_field(ctx, "_io_peak",          _io_peak)
        _save_state_field(ctx, "_fault_confirmed",  _fault_confirmed)
    if ctx.get("experiment_id") in NETWORK_CHAOS_EXPERIMENTS | IO_CHAOS_EXPERIMENTS:
        _save_state_field(ctx, "_targeted_pods", _targeted_pods)
        _save_state_field(ctx, "_restart_baseline", _restart_baseline)

    # Print final status as a persistent timestamped line after Live clears
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log import (
        log_console_line,
    )
    if terminal_status:
        ok_sev = "SUCCESS" if terminal_ok else "WARNING"
        log_console_line(console, ok_sev, f"Experiment [bold]{terminal_status}[/bold]")
        if ui:
            ui.status(f"Experiment {terminal_status}", ok=terminal_ok)
        if not terminal_ok:
            # Fetch execution details to surface the actual failure reason
            failure_detail = _get_experiment_failure_detail(
                client, chaos_rg, exp_name, session=session)
            if failure_detail:
                console.print(f"[bold red]Failure detail:[/bold red] {failure_detail}")
                if session:
                    session.log_event("experiment", f"Failure detail: {failure_detail}")
            raise RuntimeError(
                f"Experiment {terminal_status} — check Azure Portal → Chaos Studio → {exp_name}"
                + (f"\nReason: {failure_detail}" if failure_detail else "")
            )
    elif running:
        log_console_line(console, "INFO", "Experiment completed (status poll timed out)")
        if ui:
            ui.step("Experiment completed (status poll timed out)", live=True)


def _get_experiment_failure_detail(client, chaos_rg, exp_name, *, session=None):
    """
    Fetch the first failure reason from Azure Chaos Studio execution details.
    Returns a human-readable string, or None if details are unavailable.
    Walks: execution → properties.failure_reason, then run_information steps →
    branches → actions → targets → error for the first non-empty error found.
    """
    try:
        execs = list(client.experiments.list_all_executions(chaos_rg, exp_name))
        if not execs:
            return None
        detail = client.experiments.execution_details(chaos_rg, exp_name, execs[0].name)
        props  = detail.properties if detail else None
        if not props:
            return None

        # Top-level failure reason is the fastest path
        if getattr(props, "failure_reason", None):
            return props.failure_reason

        # Walk step → branch → action → target for the first error message
        run_info = getattr(props, "run_information", None)
        if run_info:
            for step in (getattr(run_info, "steps", None) or []):
                for branch in (getattr(step, "branches", None) or []):
                    for action in (getattr(branch, "actions", None) or []):
                        for target in (getattr(action, "targets", None) or []):
                            tprops = getattr(target, "properties", None) or target
                            err = getattr(tprops, "error", None)
                            if err:
                                code = getattr(err, "code", "") or ""
                                msg  = getattr(err, "message", "") or str(err)
                                return f"{code}: {msg}".lstrip(": ") if code else msg
    except Exception as exc:
        if session:
            session.log_event("experiment", f"Could not fetch failure detail: {exc}")
    return None






_EXPORTED_FUNCTIONS = (
    "_run_studio_experiment",
    "_get_experiment_failure_detail",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update({name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS})
globals().update(_LOCAL_EXPORTS)
__all__ = list(_EXPORTED_FUNCTIONS)
