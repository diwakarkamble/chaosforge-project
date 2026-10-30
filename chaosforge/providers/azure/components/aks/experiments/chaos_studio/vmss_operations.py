"""Extracted implementation helpers for the AKS Chaos Studio executor."""

from typing import Any

from .execution_support import executor_compatible

console: Any = None
datetime: Any = None
json: Any = None
os: Any = None
re: Any = None
subprocess: Any = None
tempfile: Any = None
time: Any = None
timezone: Any = None
CHAOS_NAMESPACE: Any = None
_az_rest_put: Any = None
_check_pdbs: Any = None
_get_chaos_identity_id: Any = None
_get_deployment_readiness: Any = None
_get_experiment_failure_detail: Any = None
_get_node_conditions: Any = None
_get_node_names: Any = None
_get_unhealthy_pods: Any = None
_kubectl: Any = None
_kubectl_json: Any = None
_node_is_ready: Any = None
_node_is_schedulable: Any = None
_node_pod_count: Any = None
_pending_pods_exist: Any = None
_state_file: Any = None
azure_cli_command: Any = None


def _get_vm_power_state(sub, node_rg, vmss_name, instance_id):
    """Return VM power state string e.g. 'running', 'deallocated', 'stopping'."""
    r = subprocess.run(
        azure_cli_command("vmss", "get-instance-view",
         "--subscription", sub,
         "--resource-group", node_rg,
         "--name", vmss_name,
         "--instance-id", str(instance_id),
         "--query", "statuses[?starts_with(code,'PowerState/')].displayStatus",
         "-o", "tsv"),
        capture_output=True, text=True)
    return r.stdout.strip().lower().replace("vm ", "") if r.returncode == 0 else "unknown"


def _prechecks_node_notready(node, sub, node_rg, vmss_name, instance_id, *, ui=None, session=None, cluster=None):
    """Pre-experiment checklist for node notready. Returns (ok, snapshot)."""
    ok = True

    if ui:
        ui.step(f"Pre-checks: node notready — {node}")
    if session:
        session.log_event("pre-check", f"Node notready pre-checks: {node}")

    # Node Ready
    if _node_is_ready(node):
        console.print("  [bold green]✓[/bold green] Node is Ready")
    else:
        console.print("  [bold red]✗[/bold red] Node is NOT Ready — aborting")
        ok = False

    # Not already cordoned
    if _node_is_schedulable(node):
        console.print("  [bold green]✓[/bold green] Node is schedulable")
    else:
        console.print("  [yellow]⚠[/yellow] Node is already cordoned")

    # VMSS VM power state
    vm_state = _get_vm_power_state(sub, node_rg, vmss_name, instance_id)
    if "running" in vm_state:
        console.print(f"  [bold green]✓[/bold green] Azure VM power state: {vm_state}")
    else:
        console.print(f"  [bold red]✗[/bold red] Azure VM not running (state: {vm_state}) — aborting")
        ok = False

    # Pod count
    pod_count = _node_pod_count(node)
    console.print(f"  [dim]ℹ[/dim] {pod_count} non-DaemonSet pod(s) on node")
    console.print("  [dim]ℹ[/dim] Pods evict after ~5min NotReady [dim](K8s default eviction timeout)[/dim]")

    # Other nodes capacity
    r = _kubectl(
        "get", "nodes", "--field-selector", "spec.unschedulable!=true", "-o", "jsonpath={.items[*].metadata.name}")
    other_nodes = [n for n in r.stdout.strip().split() if n and n != node]
    if other_nodes:
        console.print(f"  [bold green]✓[/bold green] {len(other_nodes)} other schedulable node(s) available")
    else:
        console.print("  [yellow]⚠[/yellow] No other schedulable nodes — evicted pods will stay Pending")

    # PDB check
    blocking_pdbs = _check_pdbs()
    if blocking_pdbs:
        console.print(f"  [yellow]⚠[/yellow] Blocking PDB(s): {', '.join(blocking_pdbs)}")
    else:
        console.print("  [bold green]✓[/bold green] No blocking PodDisruptionBudgets found")

    # Unhealthy pods baseline
    cluster_tag = f" in cluster [bold]{cluster}[/bold]" if cluster else ""
    unhealthy_before = _get_unhealthy_pods()
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
                          f"Node notready pre-checks complete — ok={ok}  "
                          f"pod_count={pod_count}  unhealthy={len(unhealthy_before)}")

    snapshot = {
        "unhealthy_before":   [(n, ns, p) for n, ns, p in unhealthy_before],
        "deployments_before": [(n, ns, rv, d) for n, ns, rv, d in deployments_before],
        "pod_count_before":   pod_count,
    }
    return ok, snapshot


def _postchecks_node_notready(node, sub, node_rg, vmss_name, instance_id,
                               state=None, *, ui=None, session=None):
    """Wait for VM restart + node Ready, then print full health summary."""
    if state is None:
        state = {}

    nodes_before       = state.get("nodes_before")
    unhealthy_before   = state.get("unhealthy_before", [])
    deployments_before = state.get("deployments_before", [])
    pod_count_before   = state.get("pod_count_before", 0)
    exp_start          = state.get("notready_start_time")

    if ui:
        ui.step(f"Post-checks: node notready — {node}")

    # ── Phase 1: wait for VM to come back (up to 8 min) ──
    console.print("\n  [bold]Waiting for Azure VM to restart...[/bold]")
    vm_ready = False
    for attempt in range(24):  # 24 x 20s = 8 min
        vm_state = _get_vm_power_state(sub, node_rg, vmss_name, instance_id)
        if "running" in vm_state:
            console.print(f"  [bold green]✓[/bold green] VM power state: {vm_state}")
            vm_ready = True
            break
        console.print(f"  [dim]↻ VM state: {vm_state}... ({(attempt + 1) * 20}s)[/dim]")
        time.sleep(20)
    if not vm_ready:
        console.print("  [bold red]✗[/bold red] VM did not return to running within 8 min — manual check needed")

    # ── Phase 2: wait for node to rejoin (up to 4 min after VM running) ──
    console.print("\n  [bold]Waiting for node to rejoin cluster...[/bold]")
    node_ready = False
    for attempt in range(12):  # 12 x 20s = 4 min
        if _node_is_ready(node):
            console.print("  [bold green]✓[/bold green] Node is Ready")
            node_ready = True
            break
        console.print(f"  [dim]↻ Node: NotReady... ({(attempt + 1) * 20}s)[/dim]")
        time.sleep(20)
    if not node_ready:
        console.print("  [bold red]✗[/bold red] Node did not return to Ready within 4 min after VM running")

    # ── Phase 3: node conditions + cluster health ─────────
    if node_ready:
        console.print("\n  [bold]Cluster health check...[/bold]")
        schedulable = _node_is_schedulable(node)
        console.print(f"  {'[bold green]✓[/bold green]' if schedulable else '[yellow]⚠[/yellow]'} "
                      f"Node is {'schedulable' if schedulable else 'cordoned'}")

        conditions = _get_node_conditions(node)
        for ctype in ("MemoryPressure", "DiskPressure", "PIDPressure"):
            val = conditions.get(ctype, "Unknown")
            console.print(f"  {'[bold green]✓[/bold green]' if val == 'False' else '[yellow]⚠[/yellow]'} "
                          f"{ctype}: {val}")

        # Note: node-notready shuts the VM briefly via Chaos Studio. K8s only
        # starts evicting pods after ~5min NotReady, so in a typical short-duration
        # run pods stay on the node and resume when it rejoins — no eviction wait needed.

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

        console.print("\n  [bold]Pod Health Comparison:[/bold]")
        unhealthy_after    = _get_unhealthy_pods()
        # Only flag pods as new failures if they were healthy before the experiment.
        # Pods already in unhealthy_before (by namespace+name) are pre-existing issues.
        preexisting_broken = {(n, ns) for n, ns, _ in unhealthy_before}
        new_failures       = [(n, ns, p) for n, ns, p in unhealthy_after
                              if (n, ns) not in preexisting_broken]
        resolved           = [(n, ns, p) for n, ns, p in unhealthy_before
                              if not any(n2 == n and ns2 == ns for n2, ns2, _ in unhealthy_after)]

        console.print(f"  [dim]ℹ Before: {len(unhealthy_before)} unhealthy  |  "
                      f"After: {len(unhealthy_after)} unhealthy[/dim]")
        if new_failures:
            all_deps_ok = False
            console.print(f"  [yellow]⚠[/yellow] {len(new_failures)} new failure(s) introduced:")
            for n, ns, p in new_failures[:5]:
                console.print(f"      [dim]- {n}  →  {p}  (ns: {ns})[/dim]")
        else:
            console.print("  [bold green]✓[/bold green] No new pod failures introduced by experiment")
        if resolved:
            console.print(f"  [dim]ℹ {len(resolved)} pre-existing failure(s) resolved:[/dim]")
            for n, ns, p in resolved[:3]:
                console.print(f"      [dim]- {n}  (was {p})[/dim]")
    else:
        all_deps_ok = False
        schedulable = False
        new_failures = []

    # ── New nodes ─────────────────────────────────────────
    if nodes_before is not None:
        new_nodes = _get_node_names() - set(nodes_before)
        if new_nodes:
            console.print(f"\n  [dim]ℹ {len(new_nodes)} new node(s) joined (autoscaler):[/dim]")
            for n in sorted(new_nodes):
                console.print(f"      [dim]+ {n}[/dim]")
        else:
            console.print("  [bold green]✓[/bold green] No new nodes added during experiment")

    if exp_start:
        elapsed = int(time.time() - exp_start)
        console.print(f"\n  [dim]ℹ {pod_count_before} pod(s) on node at start | total time: {elapsed}s[/dim]")

    overall = vm_ready and node_ready and all_deps_ok
    if overall:
        console.print("\n  [bold green]✅ Cluster healthy — node recovered.[/bold green]")
    else:
        console.print("\n  [yellow]⚠  Recovery incomplete — manual check recommended.[/yellow]")

    if session:
        session.log_event("post-check",
                          f"Node notready post-checks: overall={'PASS' if overall else 'WARN'}  "
                          f"vm_ready={vm_ready}  node_ready={node_ready}  "
                          f"new_failures={len(new_failures) if node_ready else 'N/A'}")


def _run_vmss_experiment(exp_name, spec, capability_urn, sub, node_rg, aks_rg, cluster, node, ctx,
                         *, ui=None, session=None):
    """Run a node-level shutdown fault via Azure Chaos Studio targeting the VMSS instance."""
    from datetime import timedelta as _timedelta

    from azure.identity import DefaultAzureCredential
    from azure.mgmt.chaos import ChaosManagementClient
    from azure.mgmt.chaos.models import (
        ChaosExperimentBranch,
        ChaosExperimentStep,
        ChaosTargetListSelector,
        ContinuousAction,
        Experiment,
        KeyValuePair,
        ManagedServiceIdentity,
        ManagedServiceIdentityType,
        TargetReference,
        TargetReferenceType,
    )

    # Use vmss_name/instance_id from state (set during setup_studio)
    vmss_name   = ctx.get("vmss_name")
    instance_id = ctx.get("instance_id")

    if not vmss_name:
        raise RuntimeError(
            f"Could not find VMSS instance for node '{node}'. "
            "Ensure the node providerID is set and az login is active.")

    if ui:
        ui.step(f"Node '{node}' → VMSS '{vmss_name}' instance {instance_id}")

    # Snapshot was captured in setup_studio pre-check phase; read it back from state.
    snapshot = ctx.get("_node_precheck_snapshot", {})
    ctx["nodes_before"]        = list(_get_node_names())
    ctx["unhealthy_before"]    = snapshot.get("unhealthy_before", [])
    ctx["deployments_before"]  = snapshot.get("deployments_before", [])
    ctx["pod_count_before"]    = snapshot.get("pod_count_before", 0)
    ctx["notready_start_time"] = time.time()
    state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id","unknown"))
    with open(state_path, "w") as f:
        json.dump(ctx, f)

    vmss_id = (f"/subscriptions/{sub}/resourceGroups/{node_rg}"
               f"/providers/Microsoft.Compute/virtualMachineScaleSets/{vmss_name}")
    vmss_target_id = f"{vmss_id}/providers/Microsoft.Chaos/targets/Microsoft-VirtualMachineScaleSet"

    duration_secs = int(ctx.get("duration") or 60)
    td_duration   = _timedelta(seconds=duration_secs)
    location      = ctx.get("location") or "eastus"

    parameters_dict = dict(spec.get("parameters", {}))
    parameters_dict["instances"] = f"[{instance_id}]"
    parameters = [KeyValuePair(key=k, value=v) for k, v in parameters_dict.items()]

    client   = ChaosManagementClient(DefaultAzureCredential(), sub)
    identity = _get_chaos_identity_id(sub, aks_rg)

    experiment = Experiment(
        location=location,
        identity=ManagedServiceIdentity(
            type=ManagedServiceIdentityType.USER_ASSIGNED,
            user_assigned_identities={identity: {}}
        ),
        steps=[ChaosExperimentStep(name="Step1", branches=[
            ChaosExperimentBranch(name="Branch1", actions=[
                ContinuousAction(
                    name=capability_urn, duration=td_duration,
                    parameters=parameters,
                    selector_id="sel1"
                )
            ])
        ])],
        selectors=[ChaosTargetListSelector(
            id="sel1",
            targets=[TargetReference(
                type=TargetReferenceType.CHAOS_TARGET,
                id=vmss_target_id
            )]
        )]
    )

    # Only delete if existing experiment is in a different location
    try:
        existing = client.experiments.get(node_rg, exp_name)
        existing_location = (existing.location or "").lower().replace(" ", "")
        target_location   = location.lower().replace(" ", "")
        if existing_location and existing_location != target_location:
            print(f"[AKS Chaos] Existing VMSS experiment in '{existing.location}', deleting before recreating in '{location}'...")
            client.experiments.begin_delete(node_rg, exp_name).result()
            time.sleep(10)
    except Exception:
        pass  # Does not exist yet — nothing to delete

    if ui:
        ui.step(f"Creating VMSS Studio experiment: {exp_name}")
    client.experiments.begin_create_or_update(node_rg, exp_name, experiment).result()

    if ui:
        ui.step(f"Starting: {exp_name}")
    client.experiments.begin_start(node_rg, exp_name).result()
    if session:
        session.log_event("experiment", f"VMSS experiment started: {exp_name}")

    from rich.live import Live
    from rich.text import Text

    if ui:
        ui.step("Waiting for execution to register...", live=True)
    time.sleep(15)

    poll_interval   = 10
    TICK            = 0.5
    elapsed         = 0
    running         = False
    last_node_ready = True   # node was Ready before experiment started
    fault_status    = ""
    terminal_ok     = False
    terminal_status = ""

    def _render(remaining_secs):
        mins, secs = divmod(int(max(0, remaining_secs)), 60)
        timer      = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        bar_width  = 25
        filled     = int(bar_width * max(0, duration_secs - remaining_secs) / duration_secs) \
                     if duration_secs else bar_width
        bar        = "[green]" + "█" * filled + "[/green][dim]" + "░" * (bar_width - filled) + "[/dim]"
        extra      = f"  [dim]│[/dim]  [dim]{fault_status}[/dim]" if fault_status else ""
        if not running:
            return Text.from_markup(
                "  [bold yellow]⚡[/bold yellow]  [dim]Waiting for VMSS fault to start...[/dim]"
            )
        return Text.from_markup(
            f"  [bold yellow]⚡[/bold yellow]  {bar}  [bold]{timer} remaining[/bold]{extra}"
        )

    max_iters = max(60, duration_secs // poll_interval + 20)

    with Live(_render(duration_secs), console=console,
              refresh_per_second=4, transient=True) as live:
        for _ in range(max_iters):
            try:
                execs = list(client.experiments.list_all_executions(node_rg, exp_name))
                if execs:
                    exe    = client.experiments.get_execution(node_rg, exp_name, execs[0].name)
                    status = exe.status
                    if not running and status == "Running":
                        running = True
                        if session:
                            session.log_event("experiment", "VMSS fault Running")
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

            # Probe node + VM on every poll cycle while fault is running.
            # Catching transitions every 10s is accurate enough — the node typically
            # takes 20-40s to go NotReady and another 30-60s to auto-heal.
            if running:
                node_ready_now = _node_is_ready(node)
                vm_state       = _get_vm_power_state(sub, node_rg, vmss_name, instance_id)
                pod_count      = _node_pod_count(node)
                ts_now         = datetime.now(timezone.utc).strftime("%H:%M:%S")

                # Transition: Ready → NotReady (fault landed)
                if last_node_ready and not node_ready_now:
                    live.console.print(
                        f"  [dim]{ts_now}[/dim]  [bold yellow]⚡ FAULT[/bold yellow]"
                        f"  Node {node} → [bold yellow]NotReady[/bold yellow]"
                        f"  VM: {vm_state}  pods on node: {pod_count}"
                    )
                    if session:
                        session.log_event("experiment",
                                          f"Node {node} → NotReady  VM: {vm_state}  elapsed={elapsed}s")

                # Transition: NotReady → Ready (VMSS auto-heal kicked in)
                elif not last_node_ready and node_ready_now:
                    live.console.print(
                        f"  [dim]{ts_now}[/dim]  [bold cyan]✓ HEAL[/bold cyan]"
                        f"  Node {node} → [bold cyan]Ready[/bold cyan]"
                        f"  VM: {vm_state}  elapsed: {elapsed}s"
                        f"  [dim](VMSS auto-healed — Studio fault still active)[/dim]"
                    )
                    if session:
                        session.log_event("experiment",
                                          f"Node {node} → Ready (auto-heal)  VM: {vm_state}  elapsed={elapsed}s")

                last_node_ready = node_ready_now
                node_str        = "[yellow]NotReady[/yellow]" if not node_ready_now else "Ready"
                fault_status    = f"node: {node_str} | VM: {vm_state} | pods: {pod_count}"

            ticks = int(poll_interval / TICK)
            for tick in range(ticks, 0, -1):
                remaining = max(0, duration_secs - elapsed - (poll_interval - tick * TICK))
                live.update(_render(remaining))
                time.sleep(TICK)

            if running:
                elapsed += poll_interval

    if terminal_status:
        if ui:
            ui.status(f"Experiment {terminal_status}", ok=terminal_ok)
        if not terminal_ok:
            failure_detail = _get_experiment_failure_detail(
                client, node_rg, exp_name, session=session)
            if failure_detail and ui:
                ui.step(f"Failure detail: {failure_detail}", live=True)
            raise RuntimeError(
                f"Experiment {terminal_status} — check Azure Portal → Chaos Studio → {exp_name}"
                + (f"\nReason: {failure_detail}" if failure_detail else "")
            )
    elif running:
        if ui:
            ui.step("Experiment completed (status poll timed out)", live=True)

    if running and last_node_ready:
        # last_node_ready=True at end means node never went NotReady OR it came back
        # before the final poll. Check session log to distinguish — emit the advisory.
        console.print("  [dim]ℹ Node was Ready at end of experiment "
                      "— if it went NotReady during the run, see timestamped events above.[/dim]")


def _prechecks_zone_failure(vmss_targets, sub, node_rg, *, ui=None, session=None, cluster=None):
    """
    Pre-experiment checks for zone failure.
    Returns (ok, snapshot) with baseline state across all target nodes.
    """
    node_names = [t["node"] for t in vmss_targets]

    if ui:
        ui.step(f"Pre-checks: zone failure — {len(node_names)} node(s)")
    if session:
        session.log_event("pre-check", f"Zone failure pre-checks: {node_names}")

    # Node Ready + VM power state per target
    any_not_ready = False
    for t in vmss_targets:
        node      = t["node"]
        conditions = _get_node_conditions(node)
        ready      = conditions.get("Ready") == "True"
        vm_state   = _get_vm_power_state(sub, node_rg, t["vmss_name"], t["instance_id"])
        icon       = "[bold green]✓[/bold green]" if ready else "[bold red]✗[/bold red]"
        console.print(f"  {icon} {node}  [dim]Ready: {ready}  VM: {vm_state or 'unknown'}[/dim]")
        if not ready:
            any_not_ready = True

    if any_not_ready:
        console.print("  [bold red]✗[/bold red] HARD FAIL: one or more target nodes already NotReady — aborting")
        if session:
            session.log_event("pre-check", "Zone failure aborted — nodes already NotReady")
        return False, {}

    all_nodes       = _get_node_names()
    surviving_nodes = all_nodes - set(node_names)
    console.print(f"\n  [dim]Zone nodes targeted: {len(node_names)}  "
                  f"Surviving nodes: {len(surviving_nodes)}[/dim]")

    total_evictable = 0
    pods_per_node   = {}
    for node in node_names:
        count = _node_pod_count(node)
        pods_per_node[node] = count
        total_evictable += count
        console.print(f"  [bold green]✓[/bold green] Evictable pods on {node}: {count}")

    surviving_capacity = sum(_node_pod_count(n) for n in surviving_nodes)
    console.print(f"\n  [dim]Total evictable pods (zone): {total_evictable}  "
                  f"Current load on surviving nodes: {surviving_capacity}[/dim]")
    if total_evictable > 0 and surviving_nodes:
        console.print(f"  [yellow]⚠[/yellow] {total_evictable} pods need to reschedule "
                      f"[dim]— surviving nodes may be constrained[/dim]")

    # PV zone-pinning warning
    r = _kubectl(
        "get", "pv", "-o", "jsonpath={range .items[*]}{.metadata.name} "
         "{.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]}"
         "{'\\n'}{end}")
    zone_pinned_pvs = [line.split()[0] for line in r.stdout.strip().splitlines()
                       if len(line.split()) >= 2 and line.split()[1]]
    if zone_pinned_pvs:
        console.print(f"  [yellow]⚠[/yellow] {len(zone_pinned_pvs)} zone-pinned PV(s) detected "
                      f"[dim]— pods using these will stay Pending if zone is down[/dim]")
    else:
        console.print("  [bold green]✓[/bold green] No zone-pinned PVs detected")

    unhealthy_before   = _get_unhealthy_pods()
    deployments_before = _get_deployment_readiness()
    cluster_tag = f" in cluster [bold]{cluster}[/bold]" if cluster else ""
    if unhealthy_before:
        console.print(f"  [yellow]⚠[/yellow] {len(unhealthy_before)} pre-existing unhealthy pod(s){cluster_tag} "
                      f"[dim]— excluded from post-checks[/dim]")

    if session:
        session.log_event("pre-check",
                          f"Zone failure pre-checks complete — nodes={len(node_names)}  "
                          f"total_evictable={total_evictable}  unhealthy={len(unhealthy_before)}")

    snapshot = {
        "node_names":         node_names,
        "nodes_before":       list(all_nodes),
        "pods_per_node":      pods_per_node,
        "total_evictable":    total_evictable,
        "surviving_nodes":    list(surviving_nodes),
        "unhealthy_before":   [[n, ns, p] for n, ns, p in unhealthy_before],
        "deployments_before": [[n, ns, r, d] for n, ns, r, d in deployments_before],
        "nodes_notready_seen": [],
    }
    return True, snapshot


def _postchecks_zone_failure(vmss_targets, sub, node_rg, snapshot,
                              *, ui=None, session=None):
    """
    Post-experiment checks for zone failure.
    Phase 1: all VMs running. Phase 2: all nodes Ready. Phase 3: cluster health.
    """
    node_names = [t["node"] for t in vmss_targets]

    if ui:
        ui.step(f"Post-checks: zone failure — {len(node_names)} node(s)")
    if session:
        session.log_event("post-check", f"Zone failure post-checks: {node_names}")

    # ── Phase 1: VMs back to running ─────────────────────────────────────────
    console.print("\n  [bold]Waiting for all zone VMs to restart (up to 2 min)...[/bold]")
    vm_running = {t["node"]: False for t in vmss_targets}
    for attempt in range(6):  # 6 × 20s = 2 min
        for t in vmss_targets:
            if vm_running[t["node"]]:
                continue
            state_str = _get_vm_power_state(sub, node_rg, t["vmss_name"], t["instance_id"])
            if state_str and "running" in state_str:
                vm_running[t["node"]] = True
        done = sum(vm_running.values())
        icon = "  [bold green]✓[/bold green]" if done == len(vmss_targets) else ""
        console.print(f"  [dim][{attempt+1}] VMs running: {done}/{len(vmss_targets)}{icon}[/dim]")
        if done == len(vmss_targets):
            break
        time.sleep(20)
    else:
        not_running = [n for n, v in vm_running.items() if not v]
        console.print(f"  [yellow]⚠[/yellow] VMs still not running after 2 min: {', '.join(not_running)}")

    # ── Phase 2: nodes back to Ready ─────────────────────────────────────────
    console.print("\n  [bold]Waiting for all zone nodes to be Ready (up to 1 min)...[/bold]")
    node_ready = {node: False for node in node_names}
    for attempt in range(3):  # 3 × 20s = 1 min
        for node in node_names:
            if node_ready[node]:
                continue
            conditions = _get_node_conditions(node)
            if conditions.get("Ready") == "True":
                node_ready[node] = True
        done     = sum(node_ready.values())
        statuses = "  ".join(
            f"{n.split('-')[1][:8]}: {'[bold green]✓[/bold green]' if node_ready[n] else '[dim]…[/dim]'}"
            for n in node_names)
        console.print(f"  [dim][{attempt+1}] Nodes Ready: {done}/{len(node_names)}[/dim]  [{statuses}]")
        if done == len(node_names):
            break
        time.sleep(20)
    else:
        not_ready_nodes = [n for n, v in node_ready.items() if not v]
        console.print(f"  [yellow]⚠[/yellow] Nodes still NotReady after 1 min: {', '.join(not_ready_nodes)}")

    # ── Phase 3: cluster health ───────────────────────────────────────────────
    console.print("\n  [bold]Cluster health after zone recovery:[/bold]")

    pending = _pending_pods_exist()
    if pending:
        console.print("  [yellow]⚠[/yellow] Pods still Pending after zone recovery — capacity gap detected:")
        data = _kubectl_json(["kubectl", "get", "pods", "--all-namespaces",
                              "--field-selector", "status.phase=Pending"])
        if data:
            for item in (data.get("items") or [])[:10]:
                owners = item.get("metadata", {}).get("ownerReferences", [])
                if any(o.get("kind") == "DaemonSet" for o in owners):
                    continue
                name = item["metadata"]["name"]
                ns   = item["metadata"]["namespace"]
                console.print(f"    [yellow]⚠[/yellow] {ns}/{name}: Pending")
    else:
        console.print("  [bold green]✓[/bold green] No Pending pods — all evicted pods rescheduled")

    nodes_notready_seen = snapshot.get("nodes_notready_seen", [])
    if set(nodes_notready_seen) >= set(node_names):
        console.print(f"  [bold green]✓[/bold green] All {len(node_names)} target nodes confirmed NotReady during experiment")
    elif nodes_notready_seen:
        console.print(f"  [yellow]⚠[/yellow] Only {len(nodes_notready_seen)}/{len(node_names)} nodes confirmed NotReady")
    else:
        console.print("  [yellow]⚠[/yellow] No target nodes observed NotReady — experiment may not have triggered")

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
        console.print("  [bold green]✓[/bold green] All previously-healthy deployments recovered")

    unhealthy_before_set = {(n, ns) for n, ns, _ in snapshot.get("unhealthy_before", [])}
    unhealthy_after      = _get_unhealthy_pods()
    new_unhealthy        = [(n, ns, reason) for n, ns, reason in unhealthy_after
                            if (n, ns) not in unhealthy_before_set]
    if new_unhealthy:
        console.print("\n  [bold]New unhealthy pods after zone recovery:[/bold]")
        for n, ns, reason in new_unhealthy:
            console.print(f"  [bold red]✗[/bold red] {ns}/{n}: {reason}")
    else:
        console.print("  [bold green]✓[/bold green] No new unhealthy pods")

    nodes_before_set = set(snapshot.get("nodes_before", []))
    new_nodes        = _get_node_names() - nodes_before_set
    if new_nodes:
        console.print(f"\n  [dim]ℹ {len(new_nodes)} new node(s) joined (autoscaler triggered):[/dim]")
        for n in sorted(new_nodes):
            console.print(f"    [dim]+ {n}[/dim]")
    else:
        console.print("  [bold green]✓[/bold green] No new nodes added (autoscaler not triggered)")

    all_nodes_ready = all(node_ready.values())
    overall         = all_nodes_ready and not pending and not degraded and not new_unhealthy
    if overall:
        console.print("\n  [bold green]✅ Zone fully recovered — all nodes Ready, cluster healthy[/bold green]")
    elif not all_nodes_ready:
        console.print("\n  [bold red]✗ One or more zone nodes NOT Ready — investigate[/bold red]")
    elif pending:
        console.print("\n  [yellow]⚠ Zone recovered but pods still Pending — capacity gap exposed[/yellow]")
    else:
        console.print("\n  [yellow]⚠ Zone recovered — review warnings above[/yellow]")

    if session:
        session.log_event("post-check",
                          f"Zone failure post-checks: overall={'PASS' if overall else 'WARN'}  "
                          f"all_nodes_ready={all_nodes_ready}  pending={bool(pending)}  "
                          f"degraded={len(degraded)}  new_unhealthy={len(new_unhealthy)}")



from . import zone_operations as _zone_operations

_run_zone_failure = _zone_operations._LOCAL_EXPORTS["_run_zone_failure"]
_setup_vmss_target = _zone_operations._LOCAL_EXPORTS["_setup_vmss_target"]
_apply_direct = _zone_operations._LOCAL_EXPORTS["_apply_direct"]
_live_wait = _zone_operations._LOCAL_EXPORTS["_live_wait"]
_safe_name = _zone_operations._LOCAL_EXPORTS["_safe_name"]

_EXPORTED_FUNCTIONS = (
    "_get_vm_power_state",
    "_prechecks_node_notready",
    "_postchecks_node_notready",
    "_run_vmss_experiment",
    "_prechecks_zone_failure",
    "_postchecks_zone_failure",
    "_run_zone_failure",
    "_setup_vmss_target",
    "_apply_direct",
    "_live_wait",
    "_safe_name",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update(
    {name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS}
)
__all__ = list(_EXPORTED_FUNCTIONS)
