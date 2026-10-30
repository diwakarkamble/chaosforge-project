"""Extracted implementation helpers for the AKS Chaos Studio executor."""

from typing import Any

from .execution_support import executor_compatible

console: Any = None
json: Any = None
os: Any = None
subprocess: Any = None
tempfile: Any = None
time: Any = None
CHAOS_NAMESPACE: Any = None
NODE_STRESS_CANARY_EXCLUDED_NAMESPACES: Any = None
_kubectl: Any = None
_kubectl_json: Any = None
_state_file: Any = None


def _node_pod_count(node):
    """Count non-DaemonSet pods running on a node (these are the ones drained/evicted)."""
    data = _kubectl_json(
        ["kubectl", "get", "pods", "--all-namespaces",
         "--field-selector", f"spec.nodeName={node},status.phase=Running"])
    if not data:
        return 0
    count = 0
    for item in data.get("items", []):
        owners = item.get("metadata", {}).get("ownerReferences", [])
        if not any(o.get("kind") == "DaemonSet" for o in owners):
            count += 1
    return count


def _node_is_ready(node):
    """Return True if node has Ready condition = True."""
    r = _kubectl(
        "get", "node", node, "-o", "jsonpath={.status.conditions[?(@.type==\"Ready\")].status}")
    return r.stdout.strip() == "True"


def _node_is_schedulable(node):
    """Return True if node is not cordoned."""
    r = _kubectl(
        "get", "node", node, "-o", "jsonpath={.spec.unschedulable}")
    return r.stdout.strip() != "true"


def _check_pdbs(namespace=None):
    """Return list of PDB names with disruptionsAllowed == 0."""
    cmd = ["kubectl", "get", "poddisruptionbudgets"]
    if namespace:
        cmd += ["-n", namespace]
    else:
        cmd += ["--all-namespaces"]
    data = _kubectl_json(cmd)
    if not data:
        return []
    blocking = []
    for item in data.get("items", []):
        allowed = item.get("status", {}).get("disruptionsAllowed", 1)
        if allowed == 0:
            blocking.append(item["metadata"]["name"])
    return blocking


def _pending_pods_exist():
    """Return list of non-DaemonSet pod names stuck in Pending state cluster-wide."""
    data = _kubectl_json(
        ["kubectl", "get", "pods", "--all-namespaces",
         "--field-selector", "status.phase=Pending"])
    if not data:
        return []
    pending = []
    for item in data.get("items", []):
        owners = item.get("metadata", {}).get("ownerReferences", [])
        if not any(o.get("kind") == "DaemonSet" for o in owners):
            pending.append(item["metadata"]["name"])
    return pending


def _get_node_names():
    """Return set of all current node names."""
    r = _kubectl(
        "get", "nodes", "-o", "jsonpath={.items[*].metadata.name}")
    return set(r.stdout.strip().split())


def _get_unhealthy_pods(namespace=None):
    """Return list of (name, namespace, phase/reason) for non-DaemonSet pods not in Running/Succeeded."""
    cmd = ["kubectl", "get", "pods"]
    cmd += ["-n", namespace] if namespace else ["--all-namespaces"]
    data = _kubectl_json(cmd)
    if not data:
        return []
    unhealthy = []
    for item in data.get("items", []):
        owners = item.get("metadata", {}).get("ownerReferences", [])
        if any(o.get("kind") == "DaemonSet" for o in owners):
            continue
        phase = item.get("status", {}).get("phase", "Unknown")
        if phase in ("Running", "Succeeded"):
            # Check container statuses for CrashLoopBackOff even if phase=Running
            for cs in item.get("status", {}).get("containerStatuses", []):
                reason = cs.get("state", {}).get("waiting", {}).get("reason", "")
                if reason in ("CrashLoopBackOff", "OOMKilled", "Error"):
                    phase = reason
                    break
            else:
                continue
        name = item["metadata"]["name"]
        ns   = item["metadata"]["namespace"]
        unhealthy.append((name, ns, phase))
    return unhealthy


def _get_deployment_readiness(namespace=None):
    """Return list of (name, namespace, ready, desired) for all deployments."""
    cmd = ["kubectl", "get", "deployments"]
    cmd += ["-n", namespace] if namespace else ["--all-namespaces"]
    data = _kubectl_json(cmd)
    if not data:
        return []
    result = []
    for item in data.get("items", []):
        name    = item["metadata"]["name"]
        ns      = item["metadata"]["namespace"]
        desired = item.get("spec", {}).get("replicas", 0)
        ready   = item.get("status", {}).get("readyReplicas", 0)
        result.append((name, ns, ready, desired))
    return result


def _get_node_conditions(node):
    """Return dict of node condition type → status."""
    data = _kubectl_json(["kubectl", "get", "node", node])
    if not data:
        return {}
    conditions = {}
    for c in data.get("status", {}).get("conditions", []):
        conditions[c["type"]] = c["status"]
    return conditions


def _prechecks_node_drain(node, *, ui=None, session=None, cluster=None):
    """Pre-experiment checklist for node drain. Returns (ok, snapshot)."""
    ok = True

    if ui:
        ui.step(f"Pre-checks: node drain — {node}")
    if session:
        session.log_event("pre-check", f"Node drain pre-checks: {node}")

    # Node Ready
    if _node_is_ready(node):
        console.print("  [bold green]✓[/bold green] Node is Ready")
    else:
        console.print("  [bold red]✗[/bold red] Node is NOT Ready — aborting")
        ok = False

    # Schedulable
    if _node_is_schedulable(node):
        console.print("  [bold green]✓[/bold green] Node is schedulable (not already cordoned)")
    else:
        console.print("  [yellow]⚠[/yellow] Node is already cordoned — drain may be redundant")

    # Pod count on node
    pod_count = _node_pod_count(node)
    console.print(f"  [dim]ℹ[/dim] {pod_count} non-DaemonSet pod(s) on node "
                  f"[dim](will be evicted; DaemonSet pods stay)[/dim]")

    # PDB check
    blocking_pdbs = _check_pdbs()
    if blocking_pdbs:
        console.print(f"  [yellow]⚠[/yellow] Blocking PDB(s): {', '.join(blocking_pdbs)} — drain may hang")
    else:
        console.print("  [bold green]✓[/bold green] No blocking PodDisruptionBudgets found")

    # Other nodes capacity
    r = _kubectl(
        "get", "nodes", "--field-selector", "spec.unschedulable!=true", "-o", "jsonpath={.items[*].metadata.name}")
    other_nodes = [n for n in r.stdout.strip().split() if n and n != node]
    if other_nodes:
        console.print(f"  [bold green]✓[/bold green] {len(other_nodes)} other schedulable node(s) available")
    else:
        console.print("  [yellow]⚠[/yellow] No other schedulable nodes — evicted pods will stay Pending")

    # Unhealthy pods baseline
    unhealthy_before = _get_unhealthy_pods()
    cluster_tag = f" in cluster [bold]{cluster}[/bold]" if cluster else ""
    if unhealthy_before:
        console.print(f"  [yellow]⚠[/yellow] {len(unhealthy_before)} pod(s) already unhealthy before experiment{cluster_tag}:")
        for name, ns, phase in unhealthy_before[:5]:
            console.print(f"      [dim]- {name}  →  {phase}  (ns: {ns})[/dim]")
        if len(unhealthy_before) > 5:
            console.print(f"      [dim]... and {len(unhealthy_before) - 5} more[/dim]")
    else:
        console.print(f"  [bold green]✓[/bold green] All pods healthy before experiment{cluster_tag}")

    # Deployment readiness baseline
    deployments_before = _get_deployment_readiness()
    not_ready = [(n, ns, rv, d) for n, ns, rv, d in deployments_before if rv < d]
    if not_ready:
        console.print(f"  [yellow]⚠[/yellow] {len(not_ready)} deployment(s) not at full replicas{cluster_tag}:")
        for n, ns, rv, d in not_ready[:3]:
            console.print(f"      [dim]- {n} ({ns}): {rv}/{d} ready[/dim]")
    else:
        console.print(f"  [bold green]✓[/bold green] All deployments at full replica count{cluster_tag}")

    if session:
        session.log_event("pre-check",
                          f"Node drain pre-checks complete — ok={ok}  "
                          f"pod_count={pod_count}  unhealthy={len(unhealthy_before)}")

    snapshot = {
        "unhealthy_before":   [(n, ns, p) for n, ns, p in unhealthy_before],
        "deployments_before": [(n, ns, rv, d) for n, ns, rv, d in deployments_before],
        "pod_count_before":   pod_count,
    }
    return ok, snapshot


def _run_node_drain(node, ctx, *, ui=None):
    """Drain a node — evicts all pods, marks unschedulable. Rollback: uncordon."""
    import threading as _threading

    from rich.live import Live
    from rich.text import Text

    duration_secs = int(ctx.get("duration", 60))

    # Snapshot was captured in setup_studio pre-check phase; read it back from state.
    snapshot = ctx.get("_node_precheck_snapshot", {})
    ctx["nodes_before"]       = list(_get_node_names())
    ctx["unhealthy_before"]   = snapshot.get("unhealthy_before", [])
    ctx["deployments_before"] = snapshot.get("deployments_before", [])
    ctx["pod_count_before"]   = snapshot.get("pod_count_before", 0)
    ctx["drain_start_time"]   = time.time()
    state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
    with open(state_path, "w") as f:
        json.dump(ctx, f)

    if ui:
        ui.step(f"Draining node: {node}", live=True)

    _drain_error: list = []

    def _do_drain():
        r = _kubectl(
            "drain", node, "--ignore-daemonsets", "--delete-emptydir-data", "--force", f"--timeout={duration_secs}s")
        if r.returncode != 0:
            _drain_error.append(r.stderr.strip() or "kubectl drain failed")

    _drain_thread = _threading.Thread(target=_do_drain, daemon=True)
    _drain_thread.start()

    poll_interval = 15
    TICK          = 0.5
    elapsed       = 0
    last_count    = None
    stuck_polls   = 0
    pod_status    = ""

    def _render(remaining_secs):
        mins, secs = divmod(int(max(0, remaining_secs)), 60)
        timer      = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        bar_width  = 25
        filled     = int(bar_width * max(0, duration_secs - remaining_secs) / duration_secs) \
                     if duration_secs else bar_width
        bar        = "[green]" + "█" * filled + "[/green][dim]" + "░" * (bar_width - filled) + "[/dim]"
        extra      = f"  [dim]│[/dim]  [dim]{pod_status}[/dim]" if pod_status else ""
        if _drain_thread.is_alive():
            return Text.from_markup(
                f"  [bold yellow]⚡[/bold yellow]  [dim]Draining node {node}...[/dim]"
            )
        return Text.from_markup(
            f"  [bold yellow]⚡[/bold yellow]  {bar}  [bold]{timer} remaining[/bold]{extra}"
        )

    max_iters = max(120, duration_secs // poll_interval + 40)

    with Live(_render(duration_secs), console=console,
              refresh_per_second=4, transient=True) as live:
        for _ in range(max_iters):
            if _drain_thread.is_alive():
                live.update(_render(duration_secs))
                time.sleep(TICK)
                continue

            if _drain_error:
                raise RuntimeError(f"Node drain failed for {node}: {_drain_error[0]}")

            remaining = max(0, duration_secs - elapsed)

            # Poll pod / node status every poll_interval
            ticks = int(poll_interval / TICK)
            for tick in range(ticks, 0, -1):
                remaining = max(0, duration_secs - elapsed - (poll_interval - tick * TICK))
                live.update(_render(remaining))
                time.sleep(TICK)

            pod_count   = _node_pod_count(node)
            schedulable = not _node_is_schedulable(node)
            if last_count is not None and pod_count == last_count and pod_count > 0:
                stuck_polls += 1
            else:
                stuck_polls = 0
            last_count = pod_count
            pod_status = f"evictable pods: {pod_count} | unschedulable: {schedulable}"
            if stuck_polls >= 2 and pod_count > 0:
                pod_status += " ⚠ stuck (PDB?)"

            elapsed += poll_interval
            if elapsed >= duration_secs:
                break

    if ui:
        ui.step("Drain hold complete", live=True)


def _postchecks_node_drain(node, state=None, *, ui=None, session=None):
    """Wait for pod recovery then print full post-experiment health summary."""
    if state is None:
        state = {}

    nodes_before       = state.get("nodes_before")
    unhealthy_before   = state.get("unhealthy_before", [])
    deployments_before = state.get("deployments_before", [])
    pod_count_before   = state.get("pod_count_before", 0)
    drain_start        = state.get("drain_start_time")

    if ui:
        ui.step(f"Post-checks: node drain — {node}")

    time.sleep(10)

    # ── Node state ────────────────────────────────────────
    ready = False
    schedulable = False
    for attempt in range(6):  # up to 60s
        ready       = _node_is_ready(node)
        schedulable = _node_is_schedulable(node)
        if ready and schedulable:
            break
        console.print(f"  [dim]↻ Waiting for node... ({(attempt + 1) * 10}s)[/dim]")
        time.sleep(10)

    console.print(f"  {'[bold green]✓[/bold green]' if ready else '[bold red]✗[/bold red]'} "
                  f"Node is {'Ready' if ready else 'NOT Ready'}")
    console.print(f"  {'[bold green]✓[/bold green]' if schedulable else '[bold red]✗[/bold red]'} "
                  f"Node is {'schedulable' if schedulable else 'still cordoned'}")

    # ── Node conditions ───────────────────────────────────
    conditions = _get_node_conditions(node)
    for ctype in ("MemoryPressure", "DiskPressure", "PIDPressure"):
        val = conditions.get(ctype, "Unknown")
        ok  = val == "False"
        console.print(f"  {'[bold green]✓[/bold green]' if ok else '[yellow]⚠[/yellow]'} {ctype}: {val}")

    # ── Wait for pods to recover ───────────────────────────
    healthy_before        = {(n, ns) for n, ns, r, d in deployments_before if r >= d}
    preexisting_unhealthy = {n for n, _, _ in unhealthy_before}

    console.print("\n  [dim]Waiting for evicted pods to recover...[/dim]")
    for attempt in range(9):  # 9 x 10s = 90s max
        deps = _get_deployment_readiness()
        not_ready_deps = [(n, ns, r, d) for n, ns, r, d in deps
                          if r < d and (n, ns) in healthy_before]
        pending = [p for p in _pending_pods_exist() if p not in preexisting_unhealthy]
        if not not_ready_deps and not pending:
            break
        console.print(f"  [dim]↻ {len(not_ready_deps)} deployment(s) not recovered, "
                      f"{len(pending)} pod(s) Pending... ({(attempt + 1) * 10}s)[/dim]")
        time.sleep(10)

    # ── Deployment readiness ──────────────────────────────
    console.print("\n  [bold]Deployment Readiness:[/bold]")
    deps_after      = _get_deployment_readiness()
    deps_before_map = {(n, ns): (r, d) for n, ns, r, d in deployments_before}
    shown           = 0
    all_deps_ok     = True
    for name, ns, ready_now, desired in deps_after:
        was_ready, was_desired = deps_before_map.get((name, ns), (ready_now, desired))
        was_healthy = was_ready >= was_desired
        changed     = ready_now != was_ready
        not_full    = ready_now < desired
        if changed or (not_full and was_healthy):
            icon = "[bold green]✓[/bold green]" if ready_now >= desired else "[yellow]⚠[/yellow]"
            if ready_now < desired and was_healthy:
                all_deps_ok = False
            console.print(f"  {icon} {name} ({ns}): {ready_now}/{desired} ready"
                          + (f"  [dim]← was {was_ready}/{was_desired}[/dim]" if changed else ""))
            shown += 1
    if shown == 0:
        console.print("  [bold green]✓[/bold green] All previously-healthy deployments at full replica count")

    # ── Pod health comparison ─────────────────────────────
    console.print("\n  [bold]Pod Health Comparison:[/bold]")
    unhealthy_after = _get_unhealthy_pods()
    before_names    = {n for n, _, _ in unhealthy_before}
    after_names     = {n for n, _, _ in unhealthy_after}
    new_failures    = [(n, ns, p) for n, ns, p in unhealthy_after if n not in before_names]
    resolved        = [(n, ns, p) for n, ns, p in unhealthy_before if n not in after_names]

    cluster_tag = f" in cluster [bold]{state.get('aks_name')}[/bold]" if state and state.get('aks_name') else ""
    console.print(f"  [dim]ℹ Before: {len(unhealthy_before)} unhealthy  |  "
                  f"After: {len(unhealthy_after)} unhealthy[/dim]")
    if new_failures:
        all_deps_ok = False
        console.print(f"  [yellow]⚠[/yellow] {len(new_failures)} new failure(s) introduced{cluster_tag}:")
        for n, ns, p in new_failures[:5]:
            console.print(f"      [dim]- {n}  →  {p}  (ns: {ns})[/dim]")
    else:
        console.print(f"  [bold green]✓[/bold green] No new pod failures introduced by experiment{cluster_tag}")
    if resolved:
        console.print(f"  [dim]ℹ {len(resolved)} pre-existing failure(s) resolved:[/dim]")
        for n, ns, p in resolved[:3]:
            console.print(f"      [dim]- {n}  (was {p})[/dim]")

    # ── Eviction / timing summary ─────────────────────────
    if drain_start:
        elapsed = int(time.time() - drain_start)
        console.print(f"\n  [dim]ℹ {pod_count_before} pod(s) evicted | total time: {elapsed}s[/dim]")

    # ── New nodes ─────────────────────────────────────────
    if nodes_before is not None:
        new_nodes = _get_node_names() - set(nodes_before)
        if new_nodes:
            console.print(f"  [dim]ℹ {len(new_nodes)} new node(s) joined (autoscaler):[/dim]")
            for n in sorted(new_nodes):
                console.print(f"      [dim]+ {n}[/dim]")
        else:
            console.print("  [bold green]✓[/bold green] No new nodes added during experiment")

    overall = ready and schedulable and not new_failures and all_deps_ok
    if overall:
        console.print("\n  [bold green]✅ Cluster healthy — experiment complete.[/bold green]")
    else:
        console.print("\n  [yellow]⚠  Some issues remain — manual check recommended.[/yellow]")

    if session:
        session.log_event("post-check",
                          f"Node drain post-checks: overall={'PASS' if overall else 'WARN'}  "
                          f"node_ready={ready}  schedulable={schedulable}  "
                          f"new_failures={len(new_failures)}")


def _node_has_chaos_taint(node):
    """Return True if chaos=test:NoExecute taint already exists on node."""
    r = _kubectl(
        "get", "node", node, "-o", "jsonpath={.spec.taints[*].key}={.spec.taints[*].effect}")
    return "chaos=NoExecute" in r.stdout.replace(" ", "")


def _node_taint_confirmed(node):
    """Return True if chaos=test:NoExecute taint is currently on the node."""
    data = _kubectl_json(["kubectl", "get", "node", node])
    if not data:
        return False
    for t in data.get("spec", {}).get("taints", []):
        if t.get("key") == "chaos" and t.get("value") == "test" and t.get("effect") == "NoExecute":
            return True
    return False


def _prechecks_node_taint(node, *, ui=None, session=None, cluster=None):
    """Pre-experiment checklist for node taint. Returns (ok, snapshot)."""
    ok = True

    if ui:
        ui.step(f"Pre-checks: node taint — {node}")
    if session:
        session.log_event("pre-check", f"Node taint pre-checks: {node}")

    # Node Ready
    if _node_is_ready(node):
        console.print("  [bold green]✓[/bold green] Node is Ready")
    else:
        console.print("  [bold red]✗[/bold red] Node is NOT Ready — aborting")
        ok = False

    # No existing chaos taint
    if _node_has_chaos_taint(node):
        console.print("  [bold red]✗[/bold red] Node already has chaos=test:NoExecute taint — aborting")
        ok = False
    else:
        console.print("  [bold green]✓[/bold green] No existing chaos taint on node")

    # Schedulable baseline
    if _node_is_schedulable(node):
        console.print("  [bold green]✓[/bold green] Node is schedulable")
    else:
        console.print("  [yellow]⚠[/yellow] Node is already cordoned")

    # Pod count
    pod_count = _node_pod_count(node)
    console.print(f"  [dim]ℹ[/dim] {pod_count} non-DaemonSet pod(s) on node "
                  f"[dim](will be evicted by taint)[/dim]")

    # PDB check
    blocking_pdbs = _check_pdbs()
    if blocking_pdbs:
        console.print(f"  [yellow]⚠[/yellow] Blocking PDB(s): {', '.join(blocking_pdbs)} — eviction may hang")
    else:
        console.print("  [bold green]✓[/bold green] No blocking PodDisruptionBudgets found")

    # Other nodes capacity
    r = _kubectl(
        "get", "nodes", "--field-selector", "spec.unschedulable!=true", "-o", "jsonpath={.items[*].metadata.name}")
    other_nodes = [n for n in r.stdout.strip().split() if n and n != node]
    if other_nodes:
        console.print(f"  [bold green]✓[/bold green] {len(other_nodes)} other schedulable node(s) available")
    else:
        console.print("  [yellow]⚠[/yellow] No other schedulable nodes — evicted pods will stay Pending")

    # Unhealthy pods baseline
    unhealthy_before = _get_unhealthy_pods()
    cluster_tag = f" in cluster [bold]{cluster}[/bold]" if cluster else ""
    if unhealthy_before:
        console.print(f"  [yellow]⚠[/yellow] {len(unhealthy_before)} pod(s) already unhealthy before experiment{cluster_tag}:")
        for name, ns, phase in unhealthy_before[:5]:
            console.print(f"      [dim]- {name}  →  {phase}  (ns: {ns})[/dim]")
        if len(unhealthy_before) > 5:
            console.print(f"      [dim]... and {len(unhealthy_before) - 5} more[/dim]")
    else:
        console.print(f"  [bold green]✓[/bold green] All pods healthy before experiment{cluster_tag}")

    # Deployment readiness baseline
    deployments_before = _get_deployment_readiness()
    not_ready = [(n, ns, rv, d) for n, ns, rv, d in deployments_before if rv < d]
    if not_ready:
        console.print(f"  [yellow]⚠[/yellow] {len(not_ready)} deployment(s) not at full replicas{cluster_tag}:")
        for n, ns, rv, d in not_ready[:3]:
            console.print(f"      [dim]- {n} ({ns}): {rv}/{d} ready[/dim]")
    else:
        console.print(f"  [bold green]✓[/bold green] All deployments at full replica count{cluster_tag}")

    if session:
        session.log_event("pre-check",
                          f"Node taint pre-checks complete — ok={ok}  "
                          f"pod_count={pod_count}  unhealthy={len(unhealthy_before)}")

    snapshot = {
        "unhealthy_before":   [(n, ns, p) for n, ns, p in unhealthy_before],
        "deployments_before": [(n, ns, rv, d) for n, ns, rv, d in deployments_before],
        "pod_count_before":   pod_count,
    }
    return ok, snapshot


def _run_node_taint(node, ctx, *, ui=None):
    """Apply NoExecute taint — evicts non-tolerating pods. Rollback: remove taint."""
    from rich.live import Live
    from rich.text import Text

    duration_secs = int(ctx.get("duration", 60))

    # Snapshot was captured in setup_studio pre-check phase; read it back from state.
    snapshot = ctx.get("_node_precheck_snapshot", {})
    ctx["nodes_before"]       = list(_get_node_names())
    ctx["unhealthy_before"]   = snapshot.get("unhealthy_before", [])
    ctx["deployments_before"] = snapshot.get("deployments_before", [])
    ctx["pod_count_before"]   = snapshot.get("pod_count_before", 0)
    ctx["taint_start_time"]   = time.time()
    state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
    with open(state_path, "w") as f:
        json.dump(ctx, f)

    if ui:
        ui.step(f"Tainting node: {node} with chaos=test:NoExecute", live=True)
    r = _kubectl(
        "taint", "nodes", node, "chaos=test:NoExecute", "--overwrite")
    if r.returncode != 0:
        raise RuntimeError(f"Node taint failed for {node}: {r.stderr.strip()}")

    poll_interval = 15
    TICK          = 0.5
    elapsed       = 0
    last_count    = None
    stuck_polls   = 0
    pod_status    = ""

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

            pod_count   = _node_pod_count(node)
            schedulable = _node_is_schedulable(node)
            taint_ok    = _node_taint_confirmed(node)
            if last_count is not None and pod_count == last_count and pod_count > 0:
                stuck_polls += 1
            else:
                stuck_polls = 0
            last_count = pod_count
            pod_status = (f"evictable pods: {pod_count} | schedulable: {schedulable}"
                          f" | taint: {'✓' if taint_ok else '✗'}")
            if stuck_polls >= 2 and pod_count > 0:
                pod_status += " ⚠ stuck (PDB?)"

            elapsed += poll_interval
            if elapsed >= duration_secs:
                break

    if ui:
        ui.step("Taint hold complete", live=True)


def _postchecks_node_taint(node, state=None, *, ui=None, session=None):
    """Verify taint removed, wait for pod recovery, print full health summary."""
    if state is None:
        state = {}

    nodes_before       = state.get("nodes_before")
    unhealthy_before   = state.get("unhealthy_before", [])
    deployments_before = state.get("deployments_before", [])
    pod_count_before   = state.get("pod_count_before", 0)
    taint_start        = state.get("taint_start_time")

    if ui:
        ui.step(f"Post-checks: node taint — {node}")

    time.sleep(10)

    # ── Node state ────────────────────────────────────────
    ready       = _node_is_ready(node)
    schedulable = _node_is_schedulable(node)
    taint_gone  = not _node_taint_confirmed(node)

    console.print(f"  {'[bold green]✓[/bold green]' if ready else '[bold red]✗[/bold red]'} "
                  f"Node is {'Ready' if ready else 'NOT Ready'}")
    console.print(f"  {'[bold green]✓[/bold green]' if schedulable else '[yellow]⚠[/yellow]'} "
                  f"Node is {'schedulable' if schedulable else 'cordoned'}")
    console.print(f"  {'[bold green]✓[/bold green]' if taint_gone else '[bold red]✗[/bold red]'} "
                  f"Chaos taint {'removed' if taint_gone else 'STILL PRESENT — manual removal needed'}")

    # ── Node conditions ───────────────────────────────────
    conditions = _get_node_conditions(node)
    for ctype in ("MemoryPressure", "DiskPressure", "PIDPressure"):
        val = conditions.get(ctype, "Unknown")
        console.print(f"  {'[bold green]✓[/bold green]' if val == 'False' else '[yellow]⚠[/yellow]'} "
                      f"{ctype}: {val}")

    # ── Wait for evicted pods to recover ──────────────────
    healthy_before        = {(n, ns) for n, ns, r, d in deployments_before if r >= d}
    preexisting_unhealthy = {n for n, _, _ in unhealthy_before}

    console.print("\n  [dim]Waiting for evicted pods to recover...[/dim]")
    for attempt in range(9):  # up to 90s
        deps           = _get_deployment_readiness()
        not_ready_deps = [(n, ns, r, d) for n, ns, r, d in deps
                          if r < d and (n, ns) in healthy_before]
        pending        = [p for p in _pending_pods_exist() if p not in preexisting_unhealthy]
        if not not_ready_deps and not pending:
            break
        console.print(f"  [dim]↻ {len(not_ready_deps)} deployment(s) not recovered, "
                      f"{len(pending)} pod(s) Pending... ({(attempt + 1) * 10}s)[/dim]")
        time.sleep(10)

    # ── Deployment readiness ──────────────────────────────
    console.print("\n  [bold]Deployment Readiness:[/bold]")
    deps_after      = _get_deployment_readiness()
    deps_before_map = {(n, ns): (r, d) for n, ns, r, d in deployments_before}
    shown           = 0
    all_deps_ok     = True
    for name, ns, ready_now, desired in deps_after:
        was_ready, was_desired = deps_before_map.get((name, ns), (ready_now, desired))
        was_healthy = was_ready >= was_desired
        changed     = ready_now != was_ready
        not_full    = ready_now < desired
        if changed or (not_full and was_healthy):
            icon = "[bold green]✓[/bold green]" if ready_now >= desired else "[yellow]⚠[/yellow]"
            if ready_now < desired and was_healthy:
                all_deps_ok = False
            console.print(f"  {icon} {name} ({ns}): {ready_now}/{desired} ready"
                          + (f"  [dim]← was {was_ready}/{was_desired}[/dim]" if changed else ""))
            shown += 1
    if shown == 0:
        console.print("  [bold green]✓[/bold green] All previously-healthy deployments at full replica count")

    # ── Pod health comparison ─────────────────────────────
    console.print("\n  [bold]Pod Health Comparison:[/bold]")
    unhealthy_after = _get_unhealthy_pods()
    before_names    = {n for n, _, _ in unhealthy_before}
    after_names     = {n for n, _, _ in unhealthy_after}
    new_failures    = [(n, ns, p) for n, ns, p in unhealthy_after if n not in before_names]
    resolved        = [(n, ns, p) for n, ns, p in unhealthy_before if n not in after_names]

    cluster_tag = f" in cluster [bold]{state.get('aks_name')}[/bold]" if state and state.get('aks_name') else ""
    console.print(f"  [dim]ℹ Before: {len(unhealthy_before)} unhealthy  |  "
                  f"After: {len(unhealthy_after)} unhealthy[/dim]")
    if new_failures:
        all_deps_ok = False
        console.print(f"  [yellow]⚠[/yellow] {len(new_failures)} new failure(s) introduced{cluster_tag}:")
        for n, ns, p in new_failures[:5]:
            console.print(f"      [dim]- {n}  →  {p}  (ns: {ns})[/dim]")
    else:
        console.print(f"  [bold green]✓[/bold green] No new pod failures introduced by experiment{cluster_tag}")
    if resolved:
        console.print(f"  [dim]ℹ {len(resolved)} pre-existing failure(s) resolved:[/dim]")
        for n, ns, p in resolved[:3]:
            console.print(f"      [dim]- {n}  (was {p})[/dim]")

    # ── Timing summary ────────────────────────────────────
    if taint_start:
        elapsed = int(time.time() - taint_start)
        console.print(f"\n  [dim]ℹ {pod_count_before} pod(s) evicted | total time: {elapsed}s[/dim]")

    # ── New nodes ─────────────────────────────────────────
    if nodes_before is not None:
        new_nodes = _get_node_names() - set(nodes_before)
        if new_nodes:
            console.print(f"  [dim]ℹ {len(new_nodes)} new node(s) joined (autoscaler):[/dim]")
            for n in sorted(new_nodes):
                console.print(f"      [dim]+ {n}[/dim]")
        else:
            console.print("  [bold green]✓[/bold green] No new nodes added during experiment")

    overall = ready and schedulable and taint_gone and not new_failures and all_deps_ok
    if overall:
        console.print("\n  [bold green]✅ Cluster healthy — experiment complete.[/bold green]")
    else:
        console.print("\n  [yellow]⚠  Some issues remain — manual check recommended.[/yellow]")

    if session:
        session.log_event("post-check",
                          f"Node taint post-checks: overall={'PASS' if overall else 'WARN'}  "
                          f"node_ready={ready}  taint_gone={taint_gone}  "
                          f"new_failures={len(new_failures)}")



from . import node_stress_operations as _node_stress_operations

_stress_pod_name = _node_stress_operations._LOCAL_EXPORTS["_stress_pod_name"]
_get_node_top = _node_stress_operations._LOCAL_EXPORTS["_get_node_top"]
_get_pod_restart_counts = _node_stress_operations._LOCAL_EXPORTS["_get_pod_restart_counts"]
_get_node_io_wait = _node_stress_operations._LOCAL_EXPORTS["_get_node_io_wait"]
_get_node_stress_workload_status = _node_stress_operations._LOCAL_EXPORTS["_get_node_stress_workload_status"]
_resolve_node_stress_canary = _node_stress_operations._LOCAL_EXPORTS["_resolve_node_stress_canary"]
_is_missing_exec_command = _node_stress_operations._LOCAL_EXPORTS["_is_missing_exec_command"]
_probe_node_stress_canary = _node_stress_operations._LOCAL_EXPORTS["_probe_node_stress_canary"]
_record_node_stress_impact = _node_stress_operations._LOCAL_EXPORTS["_record_node_stress_impact"]
_prechecks_node_stress = _node_stress_operations._LOCAL_EXPORTS["_prechecks_node_stress"]
_postchecks_node_stress = _node_stress_operations._LOCAL_EXPORTS["_postchecks_node_stress"]
_deploy_stress_pod = _node_stress_operations._LOCAL_EXPORTS["_deploy_stress_pod"]
_run_node_cpu_stress = _node_stress_operations._LOCAL_EXPORTS["_run_node_cpu_stress"]
_run_node_memory_pressure = _node_stress_operations._LOCAL_EXPORTS["_run_node_memory_pressure"]
_cleanup_stress_pod = _node_stress_operations._LOCAL_EXPORTS["_cleanup_stress_pod"]
_crashloop_podchaos_name = _node_stress_operations._LOCAL_EXPORTS["_crashloop_podchaos_name"]
_resolve_target_pod = _node_stress_operations._LOCAL_EXPORTS["_resolve_target_pod"]
_run_crashloop = _node_stress_operations._LOCAL_EXPORTS["_run_crashloop"]
_cleanup_crashloop = _node_stress_operations._LOCAL_EXPORTS["_cleanup_crashloop"]

_EXPORTED_FUNCTIONS = (
    "_node_pod_count",
    "_node_is_ready",
    "_node_is_schedulable",
    "_check_pdbs",
    "_pending_pods_exist",
    "_get_node_names",
    "_get_unhealthy_pods",
    "_get_deployment_readiness",
    "_get_node_conditions",
    "_prechecks_node_drain",
    "_run_node_drain",
    "_postchecks_node_drain",
    "_node_has_chaos_taint",
    "_node_taint_confirmed",
    "_prechecks_node_taint",
    "_run_node_taint",
    "_postchecks_node_taint",
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
