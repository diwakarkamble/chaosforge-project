"""Extracted AKS Chaos Studio operations."""

from typing import Any

from .execution_support import executor_compatible

_get_deployment_readiness: Any = None
_get_node_conditions: Any = None
_get_unhealthy_pods: Any = None
_kubectl: Any = None
_kubectl_json: Any = None
_node_pod_count: Any = None
CHAOS_NAMESPACE: Any = None
console: Any = None
NODE_STRESS_CANARY_EXCLUDED_NAMESPACES: Any = None
subprocess: Any = None
time: Any = None

def _stress_pod_name(experiment_id, node):
    """Generate a deterministic stress pod name from experiment and node."""
    kind = "cpu" if "cpu" in experiment_id else "memory"
    # Truncate node name to fit K8s 63-char limit
    short_node = node[:40] if len(node) > 40 else node
    return f"chaosforge-{kind}-stress-{short_node}"


def _get_node_top(node):
    """Return (cpu_pct, cpu_cores_str, mem_pct, mem_bytes_str) from kubectl top node, or None on failure."""
    r = _kubectl(
        "top", "node", node, "--no-headers")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    # Format: NAME  CPU(cores)  CPU(%)  MEMORY(bytes)  MEMORY(%)
    parts = r.stdout.strip().split()
    if len(parts) < 5:
        return None
    try:
        return {
            "cpu_cores": parts[1],
            "cpu_pct":   int(parts[2].rstrip("%")),
            "mem_bytes": parts[3],
            "mem_pct":   int(parts[4].rstrip("%")),
        }
    except (ValueError, IndexError):
        return None


def _get_pod_restart_counts(node):
    """Return dict of {(name, ns): restart_count} for non-DaemonSet pods on node."""
    data = _kubectl_json(["kubectl", "get", "pods", "--all-namespaces",
                          "--field-selector", f"spec.nodeName={node}"])
    counts = {}
    if not data:
        return counts
    for item in data.get("items", []):
        owners = item.get("metadata", {}).get("ownerReferences", [])
        if any(o.get("kind") == "DaemonSet" for o in owners):
            continue
        name = item["metadata"]["name"]
        ns   = item["metadata"]["namespace"]
        restarts = sum(
            cs.get("restartCount", 0)
            for cs in item.get("status", {}).get("containerStatuses", [])
        )
        counts[(name, ns)] = restarts
    return counts


def _get_node_io_wait(node, stress_pod_name=None):
    """
    Read I/O wait % from the node by exec-ing into the privileged stress pod (hostPID=True).
    Reads /proc/stat twice 1s apart and computes the delta (same method as iostat).
    Returns float iowait_pct or None if unavailable (pre-check, pod not yet running, etc).
    """
    if not stress_pod_name:
        return None  # Only available during experiment when stress pod is running

    script = (
        "python3 -c '"
        "import time; "
        "def r(): return list(map(int, open(\"/proc/stat\").readline().split()[1:8])); "
        "a=r(); time.sleep(1); b=r(); "
        "d=[b[i]-a[i] for i in range(7)]; t=sum(d); "
        "print(round(d[4]*100/t,1) if t else 0)'"
    )
    try:
        result = _kubectl(
            "exec", stress_pod_name, "-n", CHAOS_NAMESPACE, "--", "sh", "-c", script, timeout=8)
        return float(result.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def _get_node_stress_workload_status(node):
    """Return lightweight workload health counters for non-DaemonSet pods on the target node."""
    data = _kubectl_json(["kubectl", "get", "pods", "--all-namespaces",
                          "--field-selector", f"spec.nodeName={node}"])
    if not data:
        return None

    total_pods = 0
    running_pods = 0
    ready_pods = 0
    restart_total = 0

    for item in data.get("items", []):
        owners = item.get("metadata", {}).get("ownerReferences", [])
        if any(o.get("kind") == "DaemonSet" for o in owners):
            continue

        total_pods += 1
        phase = item.get("status", {}).get("phase", "Unknown")
        if phase == "Running":
            running_pods += 1

        conditions = item.get("status", {}).get("conditions", [])
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            ready_pods += 1

        restart_total += sum(
            cs.get("restartCount", 0)
            for cs in item.get("status", {}).get("containerStatuses", [])
        )

    return {
        "total_pods": total_pods,
        "running_pods": running_pods,
        "ready_pods": ready_pods,
        "not_ready_pods": max(0, total_pods - ready_pods),
        "restart_total": restart_total,
    }


def _resolve_node_stress_canary(node):
    """
    Pick one ready, non-DaemonSet workload pod on the target node for impact sampling.
    Probes up to 5 candidates for DNS capability and returns the first that has DNS tools.
    Falls back to the first ready pod if none have DNS tools (dns=n/a will be shown).
    """
    data = _kubectl_json(["kubectl", "get", "pods", "--all-namespaces",
                          "--field-selector", f"spec.nodeName={node}"])
    if not data:
        return None

    candidates = []
    for item in data.get("items", []):
        owners = item.get("metadata", {}).get("ownerReferences", [])
        if any(o.get("kind") == "DaemonSet" for o in owners):
            continue

        namespace = item.get("metadata", {}).get("namespace", "")
        if namespace in NODE_STRESS_CANARY_EXCLUDED_NAMESPACES:
            continue

        status = item.get("status", {})
        if status.get("phase") != "Running":
            continue

        conditions = status.get("conditions", [])
        if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            continue

        containers = item.get("spec", {}).get("containers", [])
        candidates.append({
            "namespace": namespace,
            "pod": item.get("metadata", {}).get("name", ""),
            "container": containers[0].get("name", "") if containers else "",
        })
        if len(candidates) >= 10:
            break

    if not candidates:
        return None

    # Probe up to 5 candidates; return first with working DNS tools
    for canary in candidates[:5]:
        probe = _probe_node_stress_canary(canary)
        if probe and probe.get("dns_status") in ("ok", "failed"):
            return canary

    # No DNS-capable pod found — return first candidate anyway
    return candidates[0]


def _is_missing_exec_command(output):
    text = (output or "").lower()
    return (
        "executable file not found" in text or
        "no such file or directory" in text or
        "not found" in text
    )


def _probe_node_stress_canary(canary):
    """Best-effort DNS probe from a workload pod on the stressed node."""
    if not canary:
        return None

    namespace = canary.get("namespace", "")
    pod = canary.get("pod", "")
    target_name = "kubernetes.default.svc.cluster.local"
    result = {
        "namespace": namespace,
        "pod": pod,
        "dns_status": "skipped",
    }

    dns_commands = [
        ["getent", "hosts", target_name],
        ["nslookup", target_name],
    ]
    for dns_command in dns_commands:
        dns_started = time.time()
        try:
            dns_run = _kubectl(
                "exec", pod, "-n", namespace, "--", *dns_command, timeout=6)
            dns_elapsed_ms = int((time.time() - dns_started) * 1000)
            dns_output = f"{dns_run.stdout}\n{dns_run.stderr}"

            if dns_run.returncode == 0:
                result["dns_status"] = "ok"
                result["dns_elapsed_ms"] = dns_elapsed_ms
                break
            if _is_missing_exec_command(dns_output):
                result["dns_status"] = "unavailable"
                continue
            result["dns_status"] = "failed"
            result["dns_elapsed_ms"] = dns_elapsed_ms
            break
        except subprocess.TimeoutExpired:
            result["dns_status"] = "failed"
            result["dns_elapsed_ms"] = int((time.time() - dns_started) * 1000)
            break

    summary_parts = [f"canary: {namespace}/{pod}"]
    if result["dns_status"] == "ok":
        summary_parts.append(f"dns={result['dns_elapsed_ms']}ms")
    elif result["dns_status"] == "failed":
        summary_parts.append("dns=fail")
    else:
        summary_parts.append("dns=n/a")

    result["summary"] = "  ".join(summary_parts)
    return result


def _record_node_stress_impact(snapshot, workload_status=None, canary_probe=None,
                               node_conditions=None, iowait_pct=None):
    """Persist during-fault impact counters into the node-stress snapshot."""
    if workload_status:
        prev_min_ready = snapshot.get("min_ready_pods_during")
        snapshot["min_ready_pods_during"] = (
            workload_status["ready_pods"]
            if prev_min_ready is None
            else min(prev_min_ready, workload_status["ready_pods"])
        )
        prev_min_running = snapshot.get("min_running_pods_during")
        snapshot["min_running_pods_during"] = (
            workload_status["running_pods"]
            if prev_min_running is None
            else min(prev_min_running, workload_status["running_pods"])
        )
        snapshot["max_not_ready_pods_during"] = max(
            snapshot.get("max_not_ready_pods_during", workload_status["not_ready_pods"]),
            workload_status["not_ready_pods"],
        )
        baseline_workload = snapshot.get("baseline_workload") or {}
        baseline_restarts = baseline_workload.get("restart_total", 0)
        restart_delta = max(0, workload_status["restart_total"] - baseline_restarts)
        snapshot["max_restart_delta_during"] = max(
            snapshot.get("max_restart_delta_during", 0),
            restart_delta,
        )

    if not canary_probe:
        return

    snapshot["last_canary_summary"] = canary_probe.get("summary")
    if canary_probe.get("dns_status") == "ok":
        snapshot["canary_dns_ok"] = True
        snapshot["canary_worst_dns_ms"] = max(
            snapshot.get("canary_worst_dns_ms", 0),
            canary_probe.get("dns_elapsed_ms", 0),
        )
    elif canary_probe.get("dns_status") == "failed":
        snapshot["canary_dns_failures"] = snapshot.get("canary_dns_failures", 0) + 1
    elif canary_probe.get("dns_status") == "unavailable":
        snapshot["canary_dns_unavailable"] = True

    # Node condition pressure flags (set once if they ever fire during fault)
    if node_conditions:
        if node_conditions.get("DiskPressure") == "True":
            snapshot["disk_pressure_fired"] = True
        if node_conditions.get("MemoryPressure") == "True":
            snapshot["mem_pressure_fired"] = True
        if node_conditions.get("PIDPressure") == "True":
            snapshot["pid_pressure_fired"] = True

    # I/O wait — track worst (highest) seen during fault
    if iowait_pct is not None:
        snapshot["max_iowait_pct_during"] = max(
            snapshot.get("max_iowait_pct_during", 0.0),
            iowait_pct,
        )



def _prechecks_node_stress(node, kind, *, ui=None, session=None, cluster=None):
    """
    Pre-experiment checks for CPU/memory stress.
    kind: 'cpu' or 'memory'
    Returns (ok, snapshot) where snapshot has baseline metrics.
    """
    label = "CPU Stress" if kind == "cpu" else "Memory Pressure"

    if ui:
        ui.step(f"Pre-checks: node {label.lower()} — {node}")
    if session:
        session.log_event("pre-check", f"Node stress pre-checks ({kind}): {node}")

    # Node Ready check
    conditions = _get_node_conditions(node)
    if conditions.get("Ready") != "True":
        console.print(f"  [bold red]✗[/bold red] HARD FAIL: Node '{node}' is not Ready — aborting")
        if session:
            session.log_event("pre-check", f"Node {node} not Ready — aborting")
        return False, {}
    console.print("  [bold green]✓[/bold green] Node is Ready")

    # Check no existing stress pod
    pod_name = _stress_pod_name(f"aks-node-{kind}-stress", node)
    r = _kubectl(
        "get", "pod", pod_name, "-n", CHAOS_NAMESPACE, "-o", "jsonpath={.status.phase}")
    existing_phase = r.stdout.strip()
    if existing_phase and existing_phase not in ("Succeeded", "Failed"):
        console.print(f"  [yellow]⚠[/yellow] Existing stress pod found (phase={existing_phase}) — will be replaced")
    else:
        console.print("  [bold green]✓[/bold green] No leftover stress pod")

    # chaos namespace
    r2 = _kubectl("get", "namespace", CHAOS_NAMESPACE)
    if r2.returncode != 0:
        console.print(f"  [bold red]✗[/bold red] HARD FAIL: namespace '{CHAOS_NAMESPACE}' does not exist")
        if session:
            session.log_event("pre-check", f"Namespace '{CHAOS_NAMESPACE}' missing — aborting")
        return False, {}
    console.print(f"  [bold green]✓[/bold green] Namespace '{CHAOS_NAMESPACE}' exists")

    # Baseline metrics
    top = _get_node_top(node)
    if top:
        console.print(f"  [bold green]✓[/bold green] Baseline CPU: {top['cpu_pct']}% ({top['cpu_cores']})")
        console.print(f"  [bold green]✓[/bold green] Baseline MEM: {top['mem_pct']}% ({top['mem_bytes']})")
    else:
        console.print("  [yellow]⚠[/yellow] Could not read baseline metrics (metrics-server unavailable?)")

    # Baseline node pressure conditions
    disk_pressure_before  = conditions.get("DiskPressure") == "True"
    mem_pressure_before   = conditions.get("MemoryPressure") == "True"
    pid_pressure_before   = conditions.get("PIDPressure") == "True"
    for cname, flag, icon in [
        ("DiskPressure",   disk_pressure_before,  "⚠"),
        ("MemoryPressure", mem_pressure_before,   "⚠"),
        ("PIDPressure",    pid_pressure_before,   "⚠"),
    ]:
        tag = f"[yellow]{icon}[/yellow]" if flag else "[bold green]✓[/bold green]"
        console.print(f"  {tag} Baseline {cname}: {flag}")

    # Baseline I/O wait — not available at pre-check (stress pod not yet running)
    baseline_iowait = None
    console.print("  [dim]ℹ Baseline I/O wait: measured during experiment via stress pod[/dim]")

    # Baseline unhealthy pods + deployments
    unhealthy_before   = _get_unhealthy_pods()
    deployments_before = _get_deployment_readiness()
    restarts_before    = [[n, ns, c] for (n, ns), c in _get_pod_restart_counts(node).items()]
    pod_count_before   = _node_pod_count(node)
    workload_before    = _get_node_stress_workload_status(node)
    canary             = _resolve_node_stress_canary(node)
    canary_probe       = _probe_node_stress_canary(canary) if canary else None

    cluster_tag = f" in cluster [bold]{cluster}[/bold]" if cluster else ""
    console.print(f"  [bold green]✓[/bold green] Pods on node (non-DaemonSet): {pod_count_before}")
    if workload_before:
        console.print(f"  [bold green]✓[/bold green] Target-node workload Ready: "
                      f"{workload_before['ready_pods']}/{workload_before['total_pods']}")
    if unhealthy_before:
        console.print(f"  [yellow]⚠[/yellow] {len(unhealthy_before)} pre-existing unhealthy pod(s){cluster_tag} "
                      f"[dim]— will be excluded from post-checks[/dim]")
        for name, ns, phase in unhealthy_before[:5]:
            console.print(f"      [dim]- {name}  →  {phase}  (ns: {ns})[/dim]")
        if len(unhealthy_before) > 5:
            console.print(f"      [dim]... and {len(unhealthy_before) - 5} more[/dim]")
    else:
        console.print(f"  [bold green]✓[/bold green] All pods healthy before experiment{cluster_tag}")

    if canary:
        console.print(f"  [dim]ℹ Canary pod for during-fault sampling: "
                      f"{canary['namespace']}/{canary['pod']}[/dim]")
        if canary_probe:
            console.print(f"  [dim]  Baseline canary: {canary_probe['summary']}[/dim]")
    else:
        console.print("  [yellow]⚠[/yellow] No suitable workload pod found on target node for DNS/latency sampling")

    if session:
        session.log_event("pre-check",
                          f"Node stress pre-checks complete ({kind})  "
                          f"pod_count={pod_count_before}  unhealthy={len(unhealthy_before)}")

    snapshot = {
        "baseline_top":              top,
        "baseline_workload":         workload_before,
        "baseline_iowait_pct":       baseline_iowait,
        "baseline_disk_pressure":    disk_pressure_before,
        "baseline_mem_pressure":     mem_pressure_before,
        "baseline_pid_pressure":     pid_pressure_before,
        "unhealthy_before":          [[n, ns, p] for n, ns, p in unhealthy_before],
        "deployments_before":        [[n, ns, rv, d] for n, ns, rv, d in deployments_before],
        "restarts_before":           restarts_before,
        "pod_count_before":          pod_count_before,
        "peak_cpu_pct":              top["cpu_pct"] if top else None,
        "peak_mem_pct":              top["mem_pct"] if top else None,
        "min_ready_pods_during":     workload_before["ready_pods"] if workload_before else None,
        "min_running_pods_during":   workload_before["running_pods"] if workload_before else None,
        "max_not_ready_pods_during": workload_before["not_ready_pods"] if workload_before else 0,
        "max_restart_delta_during":  0,
        "max_iowait_pct_during":     0.0,
        "disk_pressure_fired":       False,
        "mem_pressure_fired":        False,
        "pid_pressure_fired":        False,
        "canary":                    canary,
        "canary_baseline":           canary_probe,
    }
    _record_node_stress_impact(snapshot, workload_before, canary_probe,
                               node_conditions=conditions, iowait_pct=baseline_iowait)
    return True, snapshot


def _postchecks_node_stress(node, kind, snapshot, *, ui=None, session=None):
    """
    Post-experiment checks for CPU/memory stress.
    Polls CPU/MEM for up to 60s after cleanup to confirm values return toward baseline.
    """
    label       = "CPU Stress" if kind == "cpu" else "Memory Pressure"
    metric_key  = "cpu_pct" if kind == "cpu" else "mem_pct"
    metric_name = "CPU" if kind == "cpu" else "MEM"

    if ui:
        ui.step(f"Post-checks: node {label.lower()} — {node}")
    if session:
        session.log_event("post-check", f"Node stress post-checks ({kind}): {node}")

    baseline_top = snapshot.get("baseline_top")
    baseline_val = baseline_top[metric_key] if baseline_top else None
    peak_val     = snapshot.get(f"peak_{metric_key}")

    # ── Recovery poll: up to 60s every 15s ──────────────────────────────────
    console.print(f"\n  [bold]Monitoring {metric_name} recovery for up to 60s...[/bold]")
    if baseline_val is not None:
        console.print(f"  [dim]Baseline was: {baseline_val}%[/dim]")
    if peak_val is not None:
        console.print(f"  [dim]Peak during experiment: {peak_val}%[/dim]")

    recovery_confirmed = False
    last_val = None
    RECOVERY_THRESHOLD = 20

    for attempt in range(1, 5):  # 4 polls × 15s = 60s
        time.sleep(15)
        top = _get_node_top(node)
        if not top:
            console.print(f"  [dim][{attempt}/4] Could not read metrics[/dim]")
            continue
        val            = top[metric_key]
        last_val       = val
        secondary_key  = "mem_bytes" if kind == "cpu" else "cpu_pct"
        secondary_val  = top[secondary_key]
        secondary_lbl  = f"MEM: {secondary_val}" if kind == "cpu" else f"CPU: {secondary_val}%"
        cores_or_bytes = top["cpu_cores"] if kind == "cpu" else top["mem_bytes"]
        console.print(f"  [dim][{attempt}/4] {metric_name}: {val}%  ({cores_or_bytes})  {secondary_lbl}[/dim]")
        if baseline_val is not None and val <= baseline_val + RECOVERY_THRESHOLD:
            recovery_confirmed = True
            console.print(f"  [bold green]✓[/bold green] {metric_name} returned to near-baseline "
                          f"({val}% ≈ {baseline_val}% baseline)")
            break

    if not recovery_confirmed:
        if last_val is not None and baseline_val is not None:
            console.print(f"  [yellow]⚠[/yellow] {metric_name} at {last_val}% after 60s "
                          f"[dim](baseline: {baseline_val}%) — may still be settling[/dim]")
        elif last_val is None:
            console.print(f"  [yellow]⚠[/yellow] Could not confirm {metric_name} recovery "
                          f"[dim](metrics unavailable)[/dim]")

    # ── During-fault impact summary ────────────────────────────────────────────
    baseline_workload = snapshot.get("baseline_workload") or {}
    baseline_ready = baseline_workload.get("ready_pods")
    baseline_total = baseline_workload.get("total_pods")
    min_ready = snapshot.get("min_ready_pods_during")
    max_not_ready = snapshot.get("max_not_ready_pods_during")
    max_restart_delta_during = snapshot.get("max_restart_delta_during", 0)

    console.print("\n  [bold]During-experiment impact observed:[/bold]")
    if baseline_ready is not None and baseline_total is not None and min_ready is not None:
        console.print(f"  [dim]Ready pods on target node: baseline {baseline_ready}/{baseline_total}  "
                      f"→ worst {min_ready}/{baseline_total}[/dim]")
        if min_ready < baseline_ready:
            console.print(f"  [yellow]⚠[/yellow] Ready workload pods dropped by "
                          f"{baseline_ready - min_ready} on target node during stress")
        else:
            console.print("  [bold green]✓[/bold green] No ready-pod drop observed on target node")
    if max_not_ready:
        console.print(f"  [yellow]⚠[/yellow] Maximum NotReady workload pods during fault: {max_not_ready}")
    if max_restart_delta_during:
        console.print(f"  [yellow]⚠[/yellow] Maximum restart delta seen during fault sampling: +{max_restart_delta_during}")
    else:
        console.print("  [bold green]✓[/bold green] No restart spike observed during fault sampling")

    # I/O wait during fault
    max_iowait = snapshot.get("max_iowait_pct_during")
    baseline_iowait = snapshot.get("baseline_iowait_pct")
    if max_iowait is not None and max_iowait > 0:
        iowait_delta = f"  [dim](baseline: {baseline_iowait}%)[/dim]" if baseline_iowait is not None else ""
        tag = "[yellow]⚠[/yellow]" if max_iowait > 20 else "[dim]ℹ[/dim]"
        console.print(f"  {tag} Peak I/O wait during fault: {max_iowait}%{iowait_delta}")
    else:
        console.print("  [bold green]✓[/bold green] No significant I/O wait observed during fault")

    # Node pressure flags that fired during fault
    for flag_key, cname in [
        ("disk_pressure_fired",  "DiskPressure"),
        ("mem_pressure_fired",   "MemoryPressure"),
        ("pid_pressure_fired",   "PIDPressure"),
    ]:
        baseline_key = f"baseline_{flag_key.replace('_fired', '')}"
        fired = snapshot.get(flag_key, False)
        was_baseline = snapshot.get(baseline_key, False)
        if fired and not was_baseline:
            console.print(f"  [bold red]✗[/bold red] {cname} condition fired during experiment "
                          f"[dim](was False at baseline)[/dim]")
        elif fired and was_baseline:
            console.print(f"  [yellow]⚠[/yellow] {cname} was already True at baseline")
        else:
            console.print(f"  [bold green]✓[/bold green] {cname} did not fire during experiment")

    canary = snapshot.get("canary")
    if canary:
        console.print(f"  [dim]Canary pod: {canary['namespace']}/{canary['pod']}[/dim]")
        if snapshot.get("canary_worst_dns_ms") is not None:
            baseline_dns = snapshot.get("canary_baseline", {})
            baseline_dns_ms = baseline_dns.get("dns_elapsed_ms") if baseline_dns else None
            baseline_str = f"  [dim](baseline: {baseline_dns_ms}ms)[/dim]" if baseline_dns_ms else ""
            console.print(f"  [dim]Worst DNS lookup time during fault: {snapshot['canary_worst_dns_ms']} ms{baseline_str}[/dim]")
        elif snapshot.get("canary_dns_failures"):
            console.print(f"  [yellow]⚠[/yellow] Canary DNS lookup failed "
                          f"{snapshot['canary_dns_failures']} time(s) during fault")
        elif snapshot.get("canary_dns_unavailable"):
            console.print("  [dim]DNS lookup command unavailable in canary pod image[/dim]")

    # ── Node health ──────────────────────────────────────────────────────────
    console.print("\n  [bold]Node health (post-experiment):[/bold]")
    conditions    = _get_node_conditions(node)
    node_ready    = conditions.get("Ready") == "True"
    mem_pressure  = conditions.get("MemoryPressure") == "True"
    disk_pressure = conditions.get("DiskPressure") == "True"
    pid_pressure  = conditions.get("PIDPressure") == "True"

    console.print(f"  {'[bold green]✓[/bold green]' if node_ready else '[bold red]✗[/bold red]'} "
                  f"Node Ready: {node_ready}")
    console.print(f"  {'[bold red]✗[/bold red]' if mem_pressure else '[bold green]✓[/bold green]'} "
                  f"MemoryPressure: {mem_pressure}")
    console.print(f"  {'[yellow]⚠[/yellow]' if disk_pressure else '[bold green]✓[/bold green]'} "
                  f"DiskPressure: {disk_pressure}")
    console.print(f"  {'[yellow]⚠[/yellow]' if pid_pressure else '[bold green]✓[/bold green]'} "
                  f"PIDPressure: {pid_pressure}")

    # ── Pod restart delta ────────────────────────────────────────────────────
    console.print("\n  [bold]Pod restart delta:[/bold]")
    restarts_before = {(n, ns): c for n, ns, c in snapshot.get("restarts_before", [])}
    restarts_after  = _get_pod_restart_counts(node)
    new_restarts    = []
    for (name, ns), after_count in restarts_after.items():
        delta = after_count - restarts_before.get((name, ns), 0)
        if delta > 0:
            new_restarts.append((name, ns, delta))

    if new_restarts:
        for name, ns, delta in new_restarts:
            console.print(f"  [yellow]⚠[/yellow] {ns}/{name}: +{delta} restart(s) during stress")
    else:
        console.print("  [bold green]✓[/bold green] No new container restarts triggered")

    # ── Deployment readiness (baseline-aware) ────────────────────────────────
    deployments_before = snapshot.get("deployments_before", [])
    healthy_before     = {(n, ns) for n, ns, r, d in deployments_before if r >= d}
    deployments_after  = _get_deployment_readiness()
    degraded           = [(n, ns, r, d) for n, ns, r, d in deployments_after
                          if r < d and (n, ns) in healthy_before]

    console.print("\n  [bold]Deployment readiness:[/bold]")
    if degraded:
        for n, ns, r, d in degraded:
            console.print(f"  [bold red]✗[/bold red] {ns}/{n}: {r}/{d} ready [dim](was healthy before)[/dim]")
    else:
        console.print("  [bold green]✓[/bold green] All previously-healthy deployments still healthy")

    # ── Unhealthy pods (new ones) ─────────────────────────────────────────────
    unhealthy_before_list = snapshot.get("unhealthy_before", [])
    unhealthy_before_set  = {(n, ns) for n, ns, _ in unhealthy_before_list}
    unhealthy_after       = _get_unhealthy_pods()
    new_unhealthy         = [(n, ns, reason) for n, ns, reason in unhealthy_after
                             if (n, ns) not in unhealthy_before_set]

    # Get pods on target node to split cluster vs node failures
    try:
        r = _kubectl(
            "get", "pods", "--all-namespaces", "--field-selector", f"spec.nodeName={node}", "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}")
        node_pods = set(r.stdout.strip().splitlines()) if r.returncode == 0 else set()
    except Exception:
        node_pods = set()

    new_on_node    = [(n, ns, r) for n, ns, r in new_unhealthy if n in node_pods]
    new_on_cluster = [(n, ns, r) for n, ns, r in new_unhealthy if n not in node_pods]

    console.print("\n  [bold]Pod Health Comparison:[/bold]")
    console.print(f"  [dim]ℹ Before: {len(unhealthy_before_list)} unhealthy  |  "
                  f"After: {len(unhealthy_after)} unhealthy (cluster-wide)[/dim]")

    if new_on_node:
        console.print(f"\n  [bold]New unhealthy pods on target node ({node}):[/bold]")
        for n, ns, reason in new_on_node:
            console.print(f"  [bold red]✗[/bold red] {ns}/{n}: {reason}")
    else:
        console.print(f"  [bold green]✓[/bold green] No new pod failures on target node ({node})")

    if new_on_cluster:
        console.print("\n  [bold]New unhealthy pods elsewhere in cluster:[/bold]")
        for n, ns, reason in new_on_cluster[:5]:
            console.print(f"  [yellow]⚠[/yellow] {ns}/{n}: {reason}  [dim](not on target node)[/dim]")
        if len(new_on_cluster) > 5:
            console.print(f"      [dim]... and {len(new_on_cluster) - 5} more[/dim]")
    else:
        console.print("  [bold green]✓[/bold green] No new pod failures elsewhere in cluster")

    # ── Summary ──────────────────────────────────────────────────────────────
    overall = recovery_confirmed and node_ready and not degraded and not new_unhealthy
    if overall:
        console.print(f"\n  [bold green]✅ Node fully recovered — {metric_name} normalized, cluster healthy[/bold green]")
    elif not node_ready:
        console.print("\n  [bold red]✗ Node is NOT Ready after experiment — investigate[/bold red]")
    else:
        console.print("\n  [yellow]⚠ Experiment complete — review warnings above[/yellow]")

    if session:
        session.log_event("post-check",
                          f"Node stress post-checks ({kind}): overall={'PASS' if overall else 'WARN'}  "
                          f"node_ready={node_ready}  recovery={recovery_confirmed}  "
                          f"new_restarts={len(new_restarts)}  new_unhealthy={len(new_unhealthy)}")



from . import node_stress_execution as _node_stress_execution

_deploy_stress_pod = _node_stress_execution._LOCAL_EXPORTS["_deploy_stress_pod"]
_run_node_cpu_stress = _node_stress_execution._LOCAL_EXPORTS["_run_node_cpu_stress"]
_run_node_memory_pressure = _node_stress_execution._LOCAL_EXPORTS["_run_node_memory_pressure"]
_cleanup_stress_pod = _node_stress_execution._LOCAL_EXPORTS["_cleanup_stress_pod"]
_crashloop_podchaos_name = _node_stress_execution._LOCAL_EXPORTS["_crashloop_podchaos_name"]
_resolve_target_pod = _node_stress_execution._LOCAL_EXPORTS["_resolve_target_pod"]
_run_crashloop = _node_stress_execution._LOCAL_EXPORTS["_run_crashloop"]
_cleanup_crashloop = _node_stress_execution._LOCAL_EXPORTS["_cleanup_crashloop"]

_EXPORTED_FUNCTIONS = (
    "_stress_pod_name",
    "_get_node_top",
    "_get_pod_restart_counts",
    "_get_node_io_wait",
    "_get_node_stress_workload_status",
    "_resolve_node_stress_canary",
    "_is_missing_exec_command",
    "_probe_node_stress_canary",
    "_record_node_stress_impact",
    "_prechecks_node_stress",
    "_postchecks_node_stress",
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
_LOCAL_EXPORTS.update(
    {name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS}
)
__all__ = list(_EXPORTED_FUNCTIONS)
