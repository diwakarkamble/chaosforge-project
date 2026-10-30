"""
chaos_event_log.py — severity-tagged event formatting for chaos experiment execution.

All during-execution console output is routed through this module so message
style is consistent across experiment types and easy to change in one place.

Severity levels
---------------
INFO     — informational milestones (start, end, status polls)
CHAOS    — the actual fault action (kill issued, taint applied, stress deployed)
EVENT    — observed state change in the cluster (pod terminated, restart detected)
RECOVERY — system self-healing action (pod rescheduled, replica restored)
SUCCESS  — clean completion of a phase
WARNING  — threshold breach or anomalous pre-existing state

Public API
----------
log_line(live, severity, message, ts=None)
    Print one severity-tagged line that persists above a Rich Live display.

log_stress_metrics(live, ts, data)
    Print the multi-row pod+node metrics block for cpu/memory stress experiments.

log_crashloop_event(console, severity, message, ts=None)
    Like log_line but writes to a plain Rich console (crashloop has no Live context).

format_experiment_start(experiment_id, namespace, deployment, duration_secs, dry_run)
    Return the multi-line experiment banner printed at the start of Phase 4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console
    from rich.live import Live

# ── Severity → Rich colour mapping ───────────────────────────────────────────

_SEVERITY_STYLE: dict[str, str] = {
    "INFO":     "bold cyan",
    "CHAOS":    "bold magenta",
    "EVENT":    "bold yellow",
    "RECOVERY": "bold blue",
    "SUCCESS":  "bold green",
    "WARNING":  "bold red",
}

_INDENT = "  "   # two-space left margin consistent with phase_ui.py


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _severity_tag(severity: str) -> str:
    style = _SEVERITY_STYLE.get(severity.upper(), "bold white")
    label = severity.upper()
    return f"[{style}]{label:<8}[/{style}]"


# ── Primary output helpers ────────────────────────────────────────────────────

def log_line(live: Live, severity: str, message: str, ts: str | None = None) -> None:
    """
    Print a persistent severity-tagged line above a Rich Live display.

    Format:  HH:MM:SS  SEVERITY  message
    """
    ts = ts or _ts()
    live.console.print(
        f"{_INDENT}[dim]{ts}[/dim]  {_severity_tag(severity)}  {message}"
    )


def log_console_line(console: Console, severity: str, message: str, ts: str | None = None) -> None:
    """Print a severity-tagged line directly to a console (no Live context needed)."""
    ts = ts or _ts()
    console.print(
        f"{_INDENT}[dim]{ts}[/dim]  {_severity_tag(severity)}  {message}"
    )


def log_crashloop_event(console: Console, severity: str, message: str, ts: str | None = None) -> None:
    """Same as log_console_line — kept for backward compatibility."""
    log_console_line(console, severity, message, ts=ts)


def log_stress_metrics(live: Live, ts: str, data: dict) -> None:
    """
    Print the stress-metrics block — summary line followed by pod and node rows.

    data keys:
        summary   str                       one-liner for the progress bar
        pod_rows  list[(pod, ctr, cpu, mem)]
        node_rows list[(node, cpu, cpu%, mem, mem%)]

    Example output:
      08:53:15  INFO      pods: 3/3 Running (stress active)
                          POD                                        CONTAINER         CPU    MEM
                          api-7fff465b-k2dfb                         echo-server        1m    16Mi
                          NODE                                       CPU    CPU%    MEM    MEM%
                          aks-default-87249099-vmss000000            305m    3%   4786Mi   15%
    """
    c = live.console

    c.print(f"{_INDENT}[dim]{ts}[/dim]  {_severity_tag('INFO')}  {data.get('message') or data.get('summary', '')}")

    _PAD = f"{_INDENT}[dim]{'':12}[/dim]  "

    pod_rows = data.get("pod_rows", [])
    if pod_rows:
        c.print(
            f"{_PAD}"
            f"[dim]{'POD':<42} {'CONTAINER':<16} {'CPU':>6}  {'MEM':>7}[/dim]"
        )
        for pod, container, cpu, mem in pod_rows:
            c.print(
                f"{_PAD}"
                f"[dim bright_white]{pod:<42}[/dim bright_white] "
                f"[dim]{container:<16} [cyan]{cpu:>6}[/cyan]  [yellow]{mem:>7}[/yellow][/dim]"
            )

    node_rows = data.get("node_rows", [])
    if node_rows:
        c.print(
            f"{_PAD}"
            f"[dim]{'NODE':<42} {'CPU':>6}  {'CPU%':>5}  {'MEM':>7}  {'MEM%':>5}[/dim]"
        )
        for node, cpu, cpu_pct, mem, mem_pct in node_rows:
            c.print(
                f"{_PAD}"
                f"[dim bright_white]{node:<42}[/dim bright_white] "
                f"[dim][cyan]{cpu:>6}[/cyan]  [cyan]{cpu_pct:>5}[/cyan]  "
                f"[yellow]{mem:>7}[/yellow]  [yellow]{mem_pct:>5}[/yellow][/dim]"
            )


def log_net_metrics(live: Live, ts: str, data: dict) -> None:
    """
    Print the network-chaos metrics block — summary line followed by key-value rows.

    data keys:
        message   str                        one-liner summary (injection state, pod count)
        severity  str                        CHAOS / WARNING
        net_rows  list[(metric, value, detail)]  per-metric rows; detail may be ""

    Example output:
      09:28:44  CHAOS     pods: 2/2 Running | NetworkChaos AllInjected=True
                          METRIC                         VALUE              DETAIL
                          Measured RTT                   548 ms             +547ms vs baseline (1ms)
                          Endpoints ready                2 / 2
                          Container restarts             5                  liveness probe kills
    """
    c = live.console
    sev = data.get("severity", "CHAOS")
    c.print(f"{_INDENT}[dim]{ts}[/dim]  {_severity_tag(sev)}  {data.get('message', '')}")

    net_rows = data.get("net_rows", [])
    if not net_rows:
        return

    _PAD = f"{_INDENT}[dim]{'':12}[/dim]  "
    c.print(
        f"{_PAD}"
        f"[dim]{'METRIC':<30} {'VALUE':<18} {'DETAIL'}[/dim]"
    )
    for row in net_rows:
        metric = row[0] if len(row) > 0 else ""
        value  = row[1] if len(row) > 1 else ""
        detail = row[2] if len(row) > 2 else ""
        c.print(
            f"{_PAD}"
            f"[dim bright_white]{metric:<30}[/dim bright_white] "
            f"[cyan]{value:<18}[/cyan]"
            + (f"  [dim]{detail}[/dim]" if detail else "")
        )


# ── Experiment-start banner ───────────────────────────────────────────────────

_EXP_LABELS: dict[str, str] = {
    "aks-pod-kill":          "Pod Kill",
    "aks-pod-failure":       "Pod Failure",
    "aks-container-kill":    "Container Kill",
    "aks-crashloop":         "CrashLoopBackOff",
    "aks-cpu-stress":        "CPU Stress",
    "aks-memory-stress":     "Memory Stress",
    "aks-network-delay":     "Network Delay",
    "aks-network-loss":      "Network Loss",
    "aks-network-corrupt":   "Network Corruption",
    "aks-network-bandwidth": "Network Bandwidth",
    "aks-dns-chaos":         "DNS Chaos",
    "aks-disk-fill":         "Disk Fill",
    "aks-io-latency":        "I/O Latency",
    "aks-time-skew":         "Time Skew",
    "aks-http-abort":        "HTTP Abort",
    "aks-http-delay":        "HTTP Delay",
    "aks-node-drain":        "Node Drain",
    "aks-node-taint":        "Node Taint (NoExecute)",
    "aks-node-cpu-stress":   "Node CPU Stress",
    "aks-node-memory-pressure": "Node Memory Pressure",
    "aks-node-notready":     "Node NotReady",
    "aks-node-zone-failure": "Zone Node Failure",
}

_EXP_DESC: dict[str, str] = {
    "aks-pod-kill":       "Terminating target pod(s) — Kubernetes will reschedule them",
    "aks-pod-failure":    "Forcing pod(s) into a not-ready state without termination",
    "aks-container-kill": "Killing container process inside running pod(s)",
    "aks-crashloop":      "Triggering repeated container kills to induce CrashLoopBackOff",
    "aks-cpu-stress":     "Saturating CPU on target pod(s) via stress workload",
    "aks-memory-stress":  "Exhausting memory on target pod(s) via stress workload",
}


def format_experiment_start(
    experiment_id: str,
    namespace: str,
    deployment: str,
    duration_secs: int,
    dry_run: bool,
    target_pods: list[str] | None = None,
    target_summary: list[str] | None = None,
    chaos_mode: str = "one",
) -> list[str]:
    """
    Return a list of Rich markup lines for the experiment start announcement.
    Printed once at the beginning of Phase 4 before the Live timer starts.

    target_pods: resolved pod names that Chaos Mesh will act on (optional).
    target_summary: selector/mode summary when exact pods are chosen by Chaos Mesh at runtime.
    """
    label = _EXP_LABELS.get(experiment_id, experiment_id)
    desc  = _EXP_DESC.get(experiment_id, "Injecting fault against target workload")
    ts    = _ts()
    tag   = _severity_tag("CHAOS") if not dry_run else _severity_tag("INFO")
    mode  = "[dim yellow]DRY RUN PREVIEW[/dim yellow]" if dry_run else "[bold magenta]LIVE FAULT[/bold magenta]"

    lines = [
        (f"{_INDENT}[dim]{ts}[/dim]  {tag}  "
        f"[bold]{label}[/bold] — {mode}"),
        (f"{_INDENT}[dim]{'':12}[/dim]  "
        f"[dim]target: [bold]{deployment}[/bold]  "
        f"namespace: [bold]{namespace}[/bold]  "
        f"duration: [bold]{duration_secs}s[/bold][/dim]"),
        (f"{_INDENT}[dim]{'':12}[/dim]  "
        f"[dim]{desc}[/dim]"),
    ]

    if target_pods:
        # mode=one: Chaos Mesh picks ONE pod from the pool at injection time.
        # We show the full selector pool here — the actual targeted pod is
        # determined by Chaos Mesh and visible in:
        #   kubectl get <kind> -n chaos-testing -o jsonpath='{..podRecords}'
        _mode_desc = {
            "one":           "eligible pod pool (Chaos Mesh picks 1 at injection time)",
            "all":           "all pods targeted (mode=all)",
            "fixed":         "fixed count targeted — pods in scope",
            "fixed-percent": "fixed % targeted — pods in scope",
            "random-max-percent": "random % targeted — pods in scope",
        }
        _pool_label = _mode_desc.get(chaos_mode, f"pods in scope (mode={chaos_mode})")
        lines.append(
            f"{_INDENT}[dim]{'':12}[/dim]  "
            f"[dim]  {_pool_label}:[/dim]"
        )
        for pod in target_pods:
            lines.append(
                f"{_INDENT}[dim]{'':12}[/dim]  "
                f"[dim]  › pod/[bold]{pod}[/bold][/dim]"
            )
    elif target_summary:
        for summary in target_summary:
            lines.append(
                f"{_INDENT}[dim]{'':12}[/dim]  "
                f"[dim]  › {summary}[/dim]"
            )

    return lines


# ── Per-experiment event message builders ────────────────────────────────────
# Called from verify_fault_active() to produce structured event dicts instead
# of raw strings, so the caller can choose severity and message independently.

def pod_kill_status(running: int, total: int, terminating: int) -> dict:
    if terminating:
        return {
            "severity": "EVENT",
            "message":  f"pods: {running} Running, [bold yellow]{terminating} Terminating[/bold yellow]",
        }
    return {
        "severity": "INFO",
        "message":  f"pods: [bold]{running}/{total}[/bold] Running — all replicas up",
    }


def pod_kill_event(pod_name: str) -> dict:
    return {
        "severity": "CHAOS",
        "message":  f"pod/[bold]{pod_name}[/bold] terminated — Kubernetes is rescheduling",
    }


def pod_recovery_event(pod_name: str) -> dict:
    return {
        "severity": "RECOVERY",
        "message":  f"pod/[bold]{pod_name}[/bold] rescheduled — new pod is starting",
    }


def pod_failure_status(running: int, total: int, not_ready: int) -> dict:
    if not_ready:
        return {
            "severity": "EVENT",
            "message":  (
                f"pods: {running} Running — "
                f"[bold yellow]{not_ready}/{total} not Ready[/bold yellow] (fault active)"
            ),
        }
    return {
        "severity": "RECOVERY",
        "message":  f"pods: [bold]{running}/{total}[/bold] Running and Ready — fault subsiding",
    }


def container_kill_status(total: int, restarts: list[str]) -> dict:
    if restarts:
        return {
            "severity": "EVENT",
            "message":  (
                f"pods: {total} Running — "
                f"[bold yellow]restarts detected:[/bold yellow] {', '.join(restarts)}"
            ),
        }
    return {
        "severity": "INFO",
        "message":  f"pods: [bold]{total}[/bold] Running — waiting for restart signal",
    }


def crashloop_kill_event(kill_num: int, pod_name: str, remaining: int) -> dict:
    return {
        "severity": "CHAOS",
        "message":  (
            f"Kill [bold]#{kill_num}[/bold] applied to pod/[bold]{pod_name}[/bold] — "
            f"[dim]{remaining}s remaining[/dim]"
        ),
    }


def crashloop_restart_detected(pod_name: str, restart_count: int) -> dict:
    return {
        "severity": "EVENT",
        "message":  (
            f"pod/[bold]{pod_name}[/bold] — "
            f"[bold yellow]CrashLoopBackOff[/bold yellow] "
            f"(restarts: {restart_count})"
        ),
    }


def stress_summary(running: int, total: int, kind: str, peak_pct: str = "") -> dict:
    peak_str = f"  [bold yellow]peak {kind.upper()}: {peak_pct}[/bold yellow]" if peak_pct else ""
    return {
        "severity": "WARNING" if peak_pct else "INFO",
        "message":  f"pods: [bold]{running}/{total}[/bold] Running ({kind} stress active){peak_str}",
    }
