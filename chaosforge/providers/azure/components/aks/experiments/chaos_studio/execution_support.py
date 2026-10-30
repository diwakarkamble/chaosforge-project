"""Extracted implementation helpers for the AKS Chaos Studio executor."""

from functools import wraps
from importlib import import_module
from typing import Any

ValidationSession: Any = None
console: Any = None
json: Any = None
os: Any = None
subprocess: Any = None
tempfile: Any = None
KUBE_SYSTEM_EXPERIMENTS: Any = None
NODE_KUBECTL_EXPERIMENTS: Any = None
NODE_VMSS_EXPERIMENTS: Any = None
POD_DISRUPTIVE_EXPERIMENTS: Any = None
STUDIO_CAPABILITY: Any = None
VMSS_CAPABILITY: Any = None
_build_spec: Any = None
_safe_name: Any = None
_state_file: Any = None
azure_cli_command: Any = None


def executor_compatible(function):
    """Resolve globals through the stable executor facade before each call."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        executor = import_module(
            "chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor"
        )
        for name, value in vars(executor).items():
            if name.startswith("__"):
                continue
            function.__globals__[name] = value
        return function(*args, **kwargs)

    return wrapped


def _reopen_session(experiment_id: str, state: dict):
    """
    Re-attach to the ValidationSession started in setup_studio.
    The log_dir is persisted into the state file so run/cleanup steps can append
    events without reopening a new session (which would create a second folder).
    Returns None if no log_dir is stored (backward-compat or dry-run).
    """
    return ValidationSession.reopen(experiment_id, state.get("_log_dir", ""))


# ─── INTERNAL HELPERS ────────────────────────────────────────────────────────
def _delete_studio_experiment(sub, rg, exp_name):
    """Delete the Chaos Studio experiment ARM resource. Non-fatal on failure —
    the operator still gets a clean rollback even if Azure delete has a hiccup."""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.chaos import ChaosManagementClient
        client = ChaosManagementClient(DefaultAzureCredential(), sub)
        client.experiments.begin_delete(rg, exp_name).result()
        print("[AKS Chaos] Studio experiment resource deleted.")
    except Exception as e:
        print(f"[AKS Chaos] WARNING: could not delete Studio experiment '{exp_name}' "
              f"(non-fatal — remove it manually from Azure Portal → Chaos Studio): {e}")


def _get_node_resource_group(sub, rg, cluster):
    """Return the MC_ node resource group where AKS VMSS instances live."""
    r = subprocess.run(
        azure_cli_command("aks", "show", "--name", cluster, "--resource-group", rg,
         "--subscription", sub, "--query", "nodeResourceGroup", "-o", "tsv"),
        capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise RuntimeError(
        f"Could not resolve node resource group for cluster '{cluster}' in '{rg}'. "
        "Ensure 'az login' is active and the cluster name/resource group are correct."
    )


def _load_state(experiment_id=None):
    # Each ChaosToolkit run is a single OS process, so os.getpid() always
    # returns the same PID across setup → run → cleanup within one run.
    # We iterate /tmp for any state file belonging to this PID as a fallback
    # in case the experiment_id embedded in the path differs from what was
    # written (shouldn't happen, but defensive).
    pid = os.getpid()
    prefix = "aks_chaos_state_"
    suffix = f"_{pid}.json"
    tmpdir = tempfile.gettempdir()
    if experiment_id:
        path = _state_file(experiment_id)
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    for fname in os.listdir(tmpdir):
        if fname.startswith(prefix) and fname.endswith(suffix):
            path = os.path.join(tmpdir, fname)
            try:
                with open(path) as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
    return {}


def _save_state_field(state, key, value):
    """Persist one extra field into the state dict/file so a later step (e.g.
    cleanup_experiment) can read it back."""
    state[key] = value
    path = state.get("_state_path") or _state_file(state.get("experiment_id", "unknown"))
    with open(path, "w") as f:
        json.dump(state, f)


def _print_dry_run_preview(experiment_id, node, state):
    """Print exactly what run_experiment would do, without touching anything."""
    print("\n[DRY RUN] No changes will be made. Preview of the fault that would run:")

    if experiment_id == "aks-node-drain":
        duration_secs = int(state.get("duration", 60))
        print(f"  Would run: kubectl drain {node} --ignore-daemonsets "
              f"--delete-emptydir-data --force --timeout={duration_secs}s")
        return

    if experiment_id == "aks-node-taint":
        print(f"  Would run: kubectl taint nodes {node} chaos=test:NoExecute --overwrite")
        return

    if experiment_id in ("aks-node-cpu-stress", "aks-node-memory-pressure"):
        kind = "cpu" if experiment_id == "aks-node-cpu-stress" else "memory"
        print(f"  Would deploy a {kind} stress pod on node: {node}")
        print(f"  Duration : {state.get('duration', 60)}s")
        return

    if experiment_id in NODE_VMSS_EXPERIMENTS:
        _, _, kind = _build_spec(experiment_id, state)
        capability_urn = VMSS_CAPABILITY.get(kind)
        print(f"  Would target the Azure VMSS instance backing node '{node}' via Chaos Studio")
        print(f"  Capability : {capability_urn}")
        print(f"  Duration   : {state.get('duration', 60)}s")
        vmss_name = state.get("vmss_name")
        vmss_targets = state.get("vmss_targets")
        if vmss_targets:
            for t in vmss_targets:
                console.print(f"  [dim]VMSS: {t['vmss_name']}  instance {t['instance_id']}  (node: {t['node']})[/dim]")
        elif vmss_name:
            instance_id = state.get("instance_id", "")
            console.print(f"  [dim]VMSS: {vmss_name}  instance {instance_id}[/dim]")
        return

    spec, json_spec, kind = _build_spec(experiment_id, state)
    capability_urn = STUDIO_CAPABILITY.get(kind)
    if capability_urn:
        print(f"  Would create/start Azure Chaos Studio experiment: {_safe_name(experiment_id, state)}")
        print(f"  Capability : {capability_urn}")
        print(f"  jsonSpec   : {json_spec}")
        print(f"  Duration   : {state.get('duration', 60)}s")
    else:
        print(f"  Would apply directly via Chaos Mesh (kind={kind}):")
        print(f"  {json.dumps(spec, indent=2)}")


def _extract_net_metrics(net_rows: list) -> dict:
    """Extract numeric metrics from a net_rows list for peak tracking."""
    vals = {}
    for row in net_rows:
        if len(row) < 2:
            continue
        metric, value = row[0], str(row[1])
        try:
            if "RTT" in metric:
                vals["rtt_ms"] = float(value.replace("ms", "").strip())
            elif "RetransSegs" in metric:
                vals["retrans"] = int(value)
            elif "DSACKRecv" in metric:
                vals["dsack"] = int(value)
            elif "Endpoints ready" in metric:
                parts = value.replace(" ", "").split("/")
                vals["endpoints_ready"] = int(parts[0])
                if len(parts) > 1:
                    vals["endpoints_total"] = int(parts[1])
            elif "Container restarts" in metric:
                vals["restarts"] = int(value)
            elif "Unhealthy probe events" in metric or "Probe" in metric:
                vals["probe_failures"] = int(value.split()[0])
        except (ValueError, IndexError):
            pass
    return vals


def _capture_missing_net_baseline(baseline: dict, metrics: dict) -> None:
    """Add the first observed value for each network metric."""
    for key, value in metrics.items():
        baseline.setdefault(key, value)


def _probe_recovery_status(results: dict):
    result = results.get("Probe Failures Stopped (post)")
    if not result:
        return None
    detail = str(result.get("detail", "")).lower()
    unavailable_markers = (
        "skipping",
        "skipped",
        "unavailable",
        "could not query",
        "could not parse",
    )
    if any(marker in detail for marker in unavailable_markers):
        return None
    return bool(result.get("passed"))


def _print_network_outcome(
    fault_confirmed: bool,
    pre: dict,
    peak: dict,
    recovery_failures: list,
) -> None:
    """Print distinct injection, impact, and recovery outcomes for network chaos."""
    from chaosforge.interfaces.cli.interactive.ui.console import console

    pre_endpoints = pre.get("endpoints_ready")
    peak_endpoints = peak.get("endpoints_ready")
    pre_restarts = pre.get("restarts", 0)
    peak_restarts = peak.get("restarts", pre_restarts)
    impact_observed = (
        (
            isinstance(pre_endpoints, (int, float))
            and isinstance(peak_endpoints, (int, float))
            and peak_endpoints < pre_endpoints
        )
        or (
            isinstance(pre_restarts, (int, float))
            and isinstance(peak_restarts, (int, float))
            and peak_restarts > pre_restarts
        )
        or peak.get("probe_failures", 0) > pre.get("probe_failures", 0)
        or any(key in peak for key in ("rtt_ms", "retrans", "dsack"))
    )
    recovery_ok = not recovery_failures

    console.print("\n  [bold]Network chaos outcome[/bold]")
    console.print(
        "  "
        + ("[green]SUCCESS[/green]" if fault_confirmed else "[yellow]UNCONFIRMED[/yellow]")
        + "  Fault injection"
    )
    console.print(
        "  "
        + ("[green]OBSERVED[/green]" if impact_observed else "[yellow]NOT MEASURED[/yellow]")
        + "  Application impact"
    )
    console.print(
        "  "
        + ("[green]SUCCESS[/green]" if recovery_ok else "[red]FAILED[/red]")
        + "  Immediate recovery validation"
        + ("" if recovery_ok else f": {', '.join(recovery_failures)}")
    )
    console.print(
        "  [yellow]NOT ASSESSED[/yellow]  Delayed/final recovery "
        "(verify separately after the post-check window)"
    )
    console.print(
        "  "
        + ("[green]PASSED[/green]" if fault_confirmed and recovery_ok else "[red]DEVIATED[/red]")
        + "  Overall resilience result"
    )


def _print_net_impact_summary(experiment_id, pre: dict, peak: dict, duration: int,
                               fault_confirmed: bool, targeted_pods=None,
                               probe_recovered=None):
    """
    Print a non-technical before → during → after summary table
    for network chaos experiments. Called after post-checks pass.
    """
    from rich.box import ROUNDED
    from rich.table import Table

    from chaosforge.interfaces.cli.interactive.ui.console import console

    _exp_label = {
        "aks-network-delay":      "Network Delay",
        "aks-packet-loss":        "Packet Loss",
        "aks-bandwidth-limit":    "Bandwidth Limit",
        "aks-packet-corruption":  "Packet Corruption",
        "aks-packet-duplication": "Packet Duplication",
        "aks-network-partition":  "Network Partition",
    }.get(experiment_id, experiment_id)

    console.print(f"\n  [bold]What happened during the experiment — {_exp_label}[/bold]")
    console.print(f"  [dim]Fault window: {duration}s  |  Chaos Mesh injection accepted: "
                  f"{'[green]Yes ✔[/green]' if fault_confirmed else '[yellow]Unconfirmed[/yellow]'}[/dim]")
    targeted_pods = targeted_pods or []
    if targeted_pods:
        console.print(
            "  [dim]Actual targeted pod(s):[/dim] "
            f"[bold magenta]{', '.join(targeted_pods)}[/bold magenta]\n"
        )
    else:
        console.print("  [yellow]Actual targeted pod names were not reported by Chaos Mesh.[/yellow]\n")

    tbl = Table(box=ROUNDED, show_header=True, border_style="dim",
                header_style="bold dim", padding=(0, 2), expand=False)
    tbl.add_column("What was measured",     style="bold white",   min_width=28)
    tbl.add_column("Before fault",          style="dim",          min_width=16)
    tbl.add_column("Worst during fault",    style="bold yellow",  min_width=20)
    tbl.add_column("After rollback",        style="bold green",   min_width=18)

    def _fmt_rtt(v):
        return f"{v:.0f} ms" if v is not None else "—"

    def _fmt_ep(r, t):
        if r is None:
            return "—"
        return f"{r} / {t} endpoints" if t else f"{r} endpoints"

    def _diff(before, after, invert=False):
        """Return a +/- delta string."""
        if before is None or after is None:
            return ""
        d = after - before
        if d == 0:
            return ""
        sign = "+" if d > 0 else ""
        tag  = "red" if (d > 0) != invert else "green"
        return f"  [dim {tag}]({sign}{d})[/dim {tag}]"

    rows_data = []

    # ── Rows vary by experiment type ────────────────────────────────────────
    if experiment_id == "aks-network-delay":
        pre_rtt  = pre.get("rtt_ms")
        peak_rtt = peak.get("rtt_ms")
        during   = (_fmt_rtt(peak_rtt) + _diff(pre_rtt, peak_rtt, invert=False)) if peak_rtt else "—"
        rows_data.append((
            "Network response time (RTT)",
            _fmt_rtt(pre_rtt) if pre_rtt else "~1 ms",
            during,
            "✔ Back to normal",
        ))

    elif experiment_id == "aks-packet-loss":
        pre_r  = pre.get("retrans")
        peak_r = peak.get("retrans")
        delta  = (peak_r - pre_r) if (peak_r is not None and pre_r is not None) else peak_r
        during = ((f"{peak_r}  (+{delta} retransmits)" if delta else str(peak_r)) if peak_r is not None
                  else ("Active — exec blocked by packet loss" if fault_confirmed else "—"))
        rows_data.append((
            "Dropped packets (TCP retransmits)",
            str(pre_r) if pre_r is not None else "0",
            during,
            "✔ Back to 0",
        ))

    elif experiment_id == "aks-bandwidth-limit":
        rows_data.append((
            "Throughput impact",
            "Normal",
            "Throttled — see post-check logs",
            "✔ Restored",
        ))

    elif experiment_id == "aks-packet-corruption":
        pre_r  = pre.get("retrans")
        peak_r = peak.get("retrans")
        delta  = (peak_r - pre_r) if (peak_r is not None and pre_r is not None) else peak_r
        during = ((f"{peak_r}  (+{delta} from corruption)" if delta else str(peak_r)) if peak_r is not None
                  else ("Active — exec blocked by corruption" if fault_confirmed else "—"))
        rows_data.append((
            "Corrupted packets (TCP retransmits)",
            str(pre_r) if pre_r is not None else "0",
            during,
            "✔ Back to 0",
        ))

    elif experiment_id == "aks-packet-duplication":
        pre_r  = pre.get("retrans")
        peak_r = peak.get("retrans")
        pre_d  = pre.get("dsack")
        peak_d = peak.get("dsack")
        d_ret  = (peak_r - pre_r) if (peak_r is not None and pre_r is not None) else peak_r
        d_dsa  = (peak_d - pre_d) if (peak_d is not None and pre_d is not None) else peak_d
        rows_data.append((
            "Duplicated packets (TCP fast-retransmit)",
            str(pre_r) if pre_r is not None else "0",
            ((f"{peak_r}  (+{d_ret})" if d_ret else str(peak_r)) if peak_r is not None
             else ("Active — exec blocked by duplication" if fault_confirmed else "—")),
            "✔ Stabilised",
        ))
        rows_data.append((
            "Duplicate segments received (DSACK)",
            str(pre_d) if pre_d is not None else "0",
            ((f"{peak_d}  (+{d_dsa})" if d_dsa else str(peak_d)) if peak_d is not None
             else ("Active — exec blocked by duplication" if fault_confirmed else "—")),
            "✔ Stabilised",
        ))

    elif experiment_id == "aks-network-partition":
        pre_ep   = pre.get("endpoints_ready")
        pre_tot  = pre.get("endpoints_total")
        peak_ep  = peak.get("endpoints_ready")
        peak_tot = peak.get("endpoints_total") or pre_tot
        before   = _fmt_ep(pre_ep, pre_tot)
        during   = _fmt_ep(peak_ep, peak_tot) + (" [red](fully partitioned)[/red]" if peak_ep == 0 else "")
        rows_data.append((
            "Service availability (pods in service)",
            before if before != "—" else "Normal",
            during,
            "✔ Fully restored",
        ))

    # ── Common rows for all experiments ─────────────────────────────────────
    # Endpoints (for non-partition experiments — only when service data is available)
    if experiment_id != "aks-network-partition":
        pre_ep  = pre.get("endpoints_ready")
        pre_tot = pre.get("endpoints_total")
        peak_ep = peak.get("endpoints_ready")
        pk_tot  = peak.get("endpoints_total") or pre_tot
        if pre_ep is not None or peak_ep is not None:
            before  = _fmt_ep(pre_ep, pre_tot)
            if peak_ep is not None and pre_ep is not None and peak_ep < pre_ep:
                during = _fmt_ep(peak_ep, pk_tot) + " [yellow](pods removed from service)[/yellow]"
                after  = "✔ All pods back in service"
            else:
                during = _fmt_ep(peak_ep, pk_tot) if peak_ep is not None else "—"
                after  = "✔ No disruption"
            rows_data.append(("Service availability (endpoints)", before, during, after))

    # Container restarts
    pre_r  = pre.get("restarts")
    peak_r = peak.get("restarts")
    if peak_r is not None:
        delta_r = (peak_r - pre_r) if pre_r is not None else None
        new_r   = f"+{delta_r} new kills" if delta_r and delta_r > 0 else "no new kills"
        rows_data.append((
            "Container restarts",
            f"{pre_r} (stable)" if pre_r else "0",
            f"{peak_r}  ({new_r})" if peak_r else "0",
            "✔ No new restarts" if not delta_r or delta_r == 0 else "✔ Recovered",
        ))

    # Probe failures
    pre_pf  = pre.get("probe_failures", 0)
    peak_pf = peak.get("probe_failures")
    if peak_pf:
        if probe_recovered is False:
            probe_after = "⚠ Recent probe events remain (advisory)"
        elif probe_recovered is True:
            probe_after = "✔ No recent probe failures"
        else:
            probe_after = "— Recovery check unavailable"
        rows_data.append((
            "Probe failures (health checks)",
            str(pre_pf) if pre_pf else "0  (healthy)",
            f"{peak_pf}  (expected under fault)",
            probe_after,
        ))

    for row in rows_data:
        tbl.add_row(*row)

    console.print(tbl)
    pre_ep = pre.get("endpoints_ready")
    peak_ep = peak.get("endpoints_ready")
    pre_restarts = pre.get("restarts")
    peak_restarts = peak.get("restarts")
    restart_delta = (
        peak_restarts - pre_restarts
        if peak_restarts is not None and pre_restarts is not None else None
    )
    direct_evidence = any(key in peak for key in ("rtt_ms", "retrans", "dsack"))
    console.print("  [bold]Default resilience guardrails[/bold]")
    console.print(
        "  "
        + ("[green]PASS[/green]" if fault_confirmed else "[yellow]UNCONFIRMED[/yellow]")
        + "  Chaos Mesh reported AllInjected=True"
    )
    console.print(
        "  "
        + ("[green]PASS[/green]" if targeted_pods else "[yellow]UNCONFIRMED[/yellow]")
        + "  Actual target pod names captured"
    )
    if pre_ep is not None and peak_ep is not None:
        console.print(
            "  "
            + ("[green]PASS[/green]" if peak_ep >= pre_ep else "[yellow]WARN[/yellow]")
            + f"  Service endpoints maintained ({peak_ep}/{pre_ep})"
        )
    if restart_delta is not None:
        console.print(
            "  "
            + ("[green]PASS[/green]" if restart_delta <= 0 else "[yellow]WARN[/yellow]")
            + f"  New container restarts during fault: {max(0, restart_delta)}"
        )
    console.print(
        "  "
        + ("[green]MEASURED[/green]" if direct_evidence else "[yellow]NOT MEASURED[/yellow]")
        + "  Independent in-pod network-effect evidence"
    )
    console.print(
        "  [yellow]NOT MEASURED[/yellow]  External request success rate and p95/p99 latency "
        "(configure an external traffic probe for application SLO validation)"
    )
    console.print()


def _print_io_impact_summary(experiment_id, pre: dict, peak: dict, duration: int,
                              fault_confirmed: bool, targeted_pods=None,
                              post_ms=None):
    """
    Print a before → worst-during → after-rollback summary table for IOChaos
    experiments (aks-io-latency, aks-io-errors) — the same evidence pattern
    _print_net_impact_summary gives Network Chaos, built from the live I/O
    round-trip probe's baseline/peak instead of TCP counters.
    """
    from rich.box import ROUNDED
    from rich.table import Table

    from chaosforge.interfaces.cli.interactive.ui.console import console

    _exp_label = {
        "aks-io-latency": "Disk I/O Latency",
        "aks-io-errors":  "Disk I/O Errors",
    }.get(experiment_id, experiment_id)

    console.print(f"\n  [bold]What happened during the experiment — {_exp_label}[/bold]")
    console.print(f"  [dim]Fault window: {duration}s  |  Chaos Mesh injection accepted: "
                  f"{'[green]Yes ✔[/green]' if fault_confirmed else '[yellow]Unconfirmed[/yellow]'}[/dim]")
    targeted_pods = targeted_pods or []
    if targeted_pods:
        console.print(
            "  [dim]Actual targeted pod(s):[/dim] "
            f"[bold magenta]{', '.join(targeted_pods)}[/bold magenta]\n"
        )
    else:
        console.print("  [yellow]Actual targeted pod names were not reported by Chaos Mesh.[/yellow]\n")

    tbl = Table(box=ROUNDED, show_header=True, border_style="dim",
                header_style="bold dim", padding=(0, 2), expand=False)
    tbl.add_column("What was measured",     style="bold white",   min_width=28)
    tbl.add_column("Before fault",          style="dim",          min_width=16)
    tbl.add_column("Worst during fault",    style="bold yellow",  min_width=20)
    tbl.add_column("After rollback",        style="bold green",   min_width=18)

    pre_ms  = pre.get("io_ms")
    peak_ms = peak.get("io_ms")

    def _fmt_ms(v):
        return f"{v} ms" if v is not None else "—"

    if peak_ms is not None:
        delta = (peak_ms - pre_ms) if pre_ms is not None else None
        if delta:
            sign = "+" if delta > 0 else ""
            during = f"{peak_ms} ms  ({sign}{delta} vs baseline)"
        else:
            during = f"{peak_ms} ms"
    else:
        during = "Active — write/read probe unavailable" if fault_confirmed else "—"

    if post_ms is not None:
        after = f"✔ {post_ms} ms — back near baseline" if (
            pre_ms is None or post_ms <= pre_ms * 3 + 50
        ) else f"⚠ {post_ms} ms — still elevated vs baseline"
    else:
        after = "✔ Fault cleared (residual probe unavailable)"

    tbl.add_row("File I/O round-trip (write+read+delete)", _fmt_ms(pre_ms), during, after)

    console.print(tbl)
    console.print(
        "  [dim]Note: 'latency' faults delay each I/O op's completion rather than adding "
        "extra I/O volume — raw disk throughput/IOPS metrics are not expected to move; "
        "this round-trip timing is the direct evidence of the fault taking effect.[/dim]"
    )
    console.print()


def _destructive_warning(experiment_id):
    """Category-specific operator warning shown on the confirmation panel."""
    if experiment_id in POD_DISRUPTIVE_EXPERIMENTS:
        return (
            "This will terminate/disrupt the target pod(s). If managed by a "
            "Deployment, Kubernetes will reschedule them. Standalone pods will "
            "NOT recover automatically."
        )
    if experiment_id in ("aks-node-drain", "aks-node-taint"):
        return (
            "This will drain/taint a live worker node, evicting all its pods. "
            "Workloads without spare capacity elsewhere may experience downtime."
        )
    if experiment_id in ("aks-node-cpu-stress", "aks-node-memory-pressure"):
        return (
            "This deploys a stress pod directly on the target node to exhaust "
            "CPU/memory resources. Other workloads on the node may be throttled "
            "or evicted under pressure."
        )
    if experiment_id == "aks-crashloop":
        return (
            "This will force the target pod into a CrashLoopBackOff state. "
            "Kubernetes will attempt restarts — the pod will be unavailable "
            "for the duration of the experiment."
        )
    if experiment_id in NODE_VMSS_EXPERIMENTS:
        return (
            "This will act on the underlying Azure VM Scale Set instance "
            "(VM shutdown via Azure Chaos Studio). Any pods scheduled on that "
            "node will be disrupted."
        )
    if experiment_id in KUBE_SYSTEM_EXPERIMENTS:
        return (
            "This targets kube-system (CoreDNS / kube-proxy). Cluster-wide DNS "
            "or networking may be degraded for ALL workloads while the fault "
            "is active."
        )
    return (
        "This will inject a fault against pod(s) matching your selector for "
        "the configured duration. Traffic and workloads in the target "
        "namespace may be affected."
    )


def _prompt_precheck_override(experiment_id: str, failures: str):
    """
    Pre-checks failed. Show the failures clearly and ask the operator whether
    to proceed anyway or abort. Raises RuntimeError on abort.

    This is intentionally a separate prompt from _confirm_destructive_action —
    the operator already confirmed the experiment target; this is a second,
    explicit acknowledgement that they understand the cluster is not in a
    healthy steady state.
    """
    from rich.box import SIMPLE
    from rich.table import Table

    from chaosforge.common.execution_mode import is_web_execution
    from chaosforge.interfaces.cli.interactive.ui.console import console
    from chaosforge.interfaces.cli.interactive.ui.panels import title
    from chaosforge.interfaces.cli.interactive.ui.prompts import prompt

    if is_web_execution():
        # Web UI has no interactive stdin to answer this override; abort safely.
        raise RuntimeError(
            f"Experiment aborted — pre-checks failed:\n{failures}"
        )

    title(f"Pre-Experiment Checks Failed — {experiment_id}")

    console.print()
    console.print("[bold red]⚠  One or more pre-experiment steady-state checks did not pass.[/bold red]")
    console.print(
        "[dim]Running the experiment on an already-unhealthy cluster may produce "
        "misleading results and make recovery harder.[/dim]"
    )
    console.print()

    # Display each failure bullet on its own line
    for line in failures.splitlines():
        stripped = line.strip()
        if stripped.startswith("•"):
            console.print(f"  [bold red]{stripped}[/bold red]")
        elif stripped:
            console.print(f"  [dim]{stripped}[/dim]")

    console.print()

    table = Table(show_header=False, box=SIMPLE, expand=False,
                  border_style="yellow", padding=(0, 2))
    table.add_column(style="bold yellow", width=4)
    table.add_column(style="white")
    table.add_row("Y", "Override — I understand the risk and want to run the experiment anyway")
    table.add_row("N", "Abort — do not inject any fault (safe option)")
    console.print(table)
    console.print()

    answer = prompt("Proceed despite failed pre-checks? (Y/N)").strip().lower()
    if answer != "y":
        raise RuntimeError(
            f"Experiment aborted by operator — pre-checks failed and override was declined.\n"
            f"Failures:\n{failures}"
        )

    console.print()
    console.print(
        "[bold yellow]⚠  Operator override accepted — proceeding with failed pre-checks. "
        "Results may not be reliable.[/bold yellow]"
    )
    console.print()


def _confirm_destructive_action(experiment_id, sub, rg, cluster, location,
                                 namespace, deployment, duration, target_node="",
                                 chaos_mode="one", chaos_value="", dry_run=False,
                                 fault_severity=""):
    """
    Show a full confirmation summary before touching the cluster, and abort
    the run if the operator doesn't confirm. Mirrors the confirmation-gate
    pattern used throughout this platform's Azure Chaos Studio actions.

    When dry_run is True, this previews the same summary but nothing will
    actually be created/modified downstream — wording is adjusted accordingly.
    """
    import re

    from rich.box import SIMPLE
    from rich.table import Table

    from chaosforge.application.metadata import get_experiment
    from chaosforge.common.execution_mode import is_web_execution
    from chaosforge.interfaces.cli.interactive.ui.console import console
    from chaosforge.interfaces.cli.interactive.ui.panels import title
    from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
    from chaosforge.interfaces.cli.interactive.ui.status import warning

    meta     = get_experiment("aks", experiment_id) or {}
    exp_name = meta.get("name", experiment_id)
    kind     = meta.get("kind", "")

    if fault_severity:
        # The catalog "name" carries a static example value baked in at
        # authoring time (e.g. "Disk I/O Latency 100ms", "Packet Corruption
        # 50%") purely for menu/listing display — it does NOT reflect
        # whatever the operator actually configured for this run. Whenever
        # fault_severity is populated (built from the real inputs), it is the
        # single source of truth; strip the catalog's stale trailing
        # number+unit from the confirmation title so the two lines can never
        # show conflicting values (e.g. title "100ms" vs "Fault Severity
        # delay=1000ms").
        exp_name = re.sub(
            r"\s+[\d.]+\s*(?:ms|s|m|h|%|mbps|gbps|kbps)$", "", exp_name, flags=re.IGNORECASE
        )

    if experiment_id in NODE_KUBECTL_EXPERIMENTS:
        engine = "direct kubectl node operation"
        kind = ""  # spec kind is irrelevant for kubectl-based experiments
    elif experiment_id in NODE_VMSS_EXPERIMENTS:
        engine = "VMSS fault via Azure Chaos Studio"
    else:
        engine = "AKS Chaos Mesh via Azure Chaos Studio"
    fault_label = f"{kind + ' — ' if kind else ''}{engine}"

    title(f"Azure Chaos Studio \u2014 {exp_name} {'(DRY RUN Preview)' if dry_run else 'Confirmation'}")

    console.print()
    if dry_run:
        console.print("[bold cyan]\u2139  DRY RUN \u2014 no changes will be made. This previews what WOULD happen.[/bold cyan]")
    else:
        console.print("[bold yellow]\u26a0  You are about to run a destructive experiment.[/bold yellow]")
    console.print()

    summary = Table(
        show_header=False, box=SIMPLE, expand=True,
        border_style="bright_blue", padding=(0, 2),
    )
    summary.add_column(style="bold cyan", width=22, ratio=0)
    summary.add_column(style="bold white", ratio=1)

    summary.add_row("Cloud",           "Microsoft Azure")
    summary.add_row("Subscription",    sub or "-")
    summary.add_row("Resource Group",  rg or "-")
    summary.add_row("AKS Cluster",     cluster or "-")
    summary.add_row("Location",        location or "-")
    if namespace:
        summary.add_row("Namespace", namespace)
    if deployment:
        summary.add_row("Deployment/Selector", deployment)
    if target_node:
        summary.add_row("Target Node", target_node)
    summary.add_row("Fault",    f"{exp_name}  ({fault_label})")
    summary.add_row("Duration", f"{duration} second(s)")
    if fault_severity:
        summary.add_row("Fault Severity", fault_severity)
    if chaos_mode and chaos_mode != "one":
        summary.add_row("Chaos Mode", f"{chaos_mode} {chaos_value}".strip())

    console.print(summary)
    console.print()

    warn_style = "bold cyan" if dry_run else "bold red"
    console.print(f"[{warn_style}]{_destructive_warning(experiment_id)}[/{warn_style}]")
    console.print()

    verb = "Preview" if dry_run else "Proceed with"
    if is_web_execution():
        # The web UI's own "run experiment" click is the confirmation gate.
        console.print(f"[dim]Web execution — auto-confirming: {verb} {exp_name}[/dim]")
        return

    answer = prompt(f"{verb} {exp_name}? (Y/N)").strip().lower()
    if answer != "y":
        warning("Experiment cancelled by operator.")
        raise RuntimeError("Experiment cancelled by operator \u2014 no fault was injected.")


def _resolve_azure_details(context_name, subscription_id, resource_group, aks_name):
    """Resolve Azure details, preferring values selected by the interface."""
    from chaosforge.providers.azure.discovery import resolve_subscription_id

    subscription_id = str(subscription_id or "").strip()
    resource_group = str(resource_group or "").strip()
    aks_name = str(aks_name or "").strip()
    context_name = str(context_name or "").strip()
    if subscription_id and resource_group and aks_name:
        return resolve_subscription_id(subscription_id), resource_group, aks_name

    try:
        r = subprocess.run(
            azure_cli_command("account", "show", "--query", "{id:id}", "-o", "json"),
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("Not logged in to Azure. Run 'az login' first.")
        account = json.loads(r.stdout)
        sub = (
            resolve_subscription_id(subscription_id)
            if subscription_id
            else str(account["id"])
        )

        command = azure_cli_command("aks", "list", "--subscription", sub)
        if resource_group:
            command.extend(["--resource-group", resource_group])
        command.extend(["--query", "[].{name:name, rg:resourceGroup}", "-o", "json"])
        r2 = subprocess.run(
            command,
            capture_output=True, text=True)
        clusters = json.loads(r2.stdout) if r2.returncode == 0 else []

        for c in clusters:
            if aks_name and c["name"] == aks_name:
                return sub, c["rg"], c["name"]
            if context_name and (c["name"] in context_name or context_name == c["name"]):
                return sub, c["rg"], c["name"]

        if len(clusters) == 1:
            return sub, clusters[0]["rg"], clusters[0]["name"]

    except Exception as e:
        raise RuntimeError(f"Could not resolve Azure details: {e}")

    raise RuntimeError(
        "Could not resolve the selected AKS cluster. Re-select the Azure subscription "
        "and AKS cluster so subscription_id, resource_group, and aks_name are stored."
    )




_EXPORTED_FUNCTIONS = (
    "_reopen_session",
    "_delete_studio_experiment",
    "_get_node_resource_group",
    "_load_state",
    "_save_state_field",
    "_print_dry_run_preview",
    "_extract_net_metrics",
    "_capture_missing_net_baseline",
    "_probe_recovery_status",
    "_print_network_outcome",
    "_print_net_impact_summary",
    "_print_io_impact_summary",
    "_destructive_warning",
    "_prompt_precheck_override",
    "_confirm_destructive_action",
    "_resolve_azure_details",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update(
    {
        _name: executor_compatible(globals()[_name])
        for _name in _EXPORTED_FUNCTIONS
    }
)
globals().update(_LOCAL_EXPORTS)

__all__ = list(_EXPORTED_FUNCTIONS)
