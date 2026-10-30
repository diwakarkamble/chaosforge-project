"""Extracted AKS Chaos Studio operations."""

from typing import Any

from .execution_support import executor_compatible

_az_rest_put: Any = None
_get_chaos_identity_id: Any = None
_get_experiment_failure_detail: Any = None
_get_node_conditions: Any = None
_kubectl: Any = None
_kubectl_json: Any = None
_state_file: Any = None
CHAOS_NAMESPACE: Any = None
console: Any = None
json: Any = None
os: Any = None
re: Any = None
subprocess: Any = None
tempfile: Any = None
time: Any = None
azure_cli_command: Any = None

def _run_zone_failure(exp_name, spec, capability_urn, sub, node_rg, aks_rg, cluster, vmss_targets, ctx, *, ui=None, session=None):
    """Run zone-level failure: shut down ALL nodes in a zone simultaneously via a single Chaos Studio experiment."""
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

    duration_secs = int(ctx.get("duration") or 60)
    td_duration   = _timedelta(seconds=duration_secs)
    location      = ctx.get("location") or "eastus"

    # Group target
    # s by VMSS name (multiple nodes can share a VMSS with different instance IDs)
    vmss_groups = {}
    node_names = []
    for t in vmss_targets:
        vmss_name = t["vmss_name"]
        if vmss_name not in vmss_groups:
            vmss_groups[vmss_name] = []
        vmss_groups[vmss_name].append(t["instance_id"])
        node_names.append(t["node"])

    console.print(f"  [dim]Zone failure targeting {len(vmss_targets)} node(s): {', '.join(node_names)}[/dim]")
    console.print(f"  [dim]VMSS groups: {len(vmss_groups)} scale set(s)[/dim]")

    # Pre-checks ran in setup_studio pre-check phase; read snapshot from state.
    snapshot = ctx.get("_node_precheck_snapshot", {})
    if not ctx.get("_node_precheck_ok", True):
        raise RuntimeError("Pre-experiment checks failed for zone failure — aborting")

    ctx["_zone_snapshot"] = snapshot
    state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
    with open(state_path, "w") as f:
        json.dump(ctx, f)

    # Build one branch per VMSS, each with its own selector and instance list
    branches = []
    selectors = []
    base_params = dict(spec.get("parameters", {}))
    base_params.pop("virtualMachineScaleSetInstances", None)

    for i, (vmss_name, instance_ids) in enumerate(vmss_groups.items()):
        sel_id = f"sel{i+1}"
        vmss_id = (f"/subscriptions/{sub}/resourceGroups/{node_rg}"
                   f"/providers/Microsoft.Compute/virtualMachineScaleSets/{vmss_name}")
        target_id = f"{vmss_id}/providers/Microsoft.Chaos/targets/Microsoft-VirtualMachineScaleSet"

        # Instance list format: "[0,1,3]"
        instances_str = "[" + ",".join(str(iid) for iid in instance_ids) + "]"
        params = dict(base_params)
        params["instances"] = instances_str
        parameters = [KeyValuePair(key=k, value=v) for k, v in params.items()]

        branches.append(ChaosExperimentBranch(
            name=f"Branch-{vmss_name}",
            actions=[ContinuousAction(
                name=capability_urn, duration=td_duration,
                parameters=parameters,
                selector_id=sel_id
            )]
        ))
        selectors.append(ChaosTargetListSelector(
            id=sel_id,
            targets=[TargetReference(type=TargetReferenceType.CHAOS_TARGET, id=target_id)]
        ))

    client   = ChaosManagementClient(DefaultAzureCredential(), sub)
    identity = _get_chaos_identity_id(sub, aks_rg)

    experiment = Experiment(
        location=location,
        identity=ManagedServiceIdentity(
            type=ManagedServiceIdentityType.USER_ASSIGNED,
            user_assigned_identities={identity: {}}
        ),
        steps=[ChaosExperimentStep(name="Step1", branches=branches)],
        selectors=selectors
    )

    # Delete existing if location mismatch
    try:
        existing = client.experiments.get(node_rg, exp_name)
        existing_location = (existing.location or "").lower().replace(" ", "")
        target_location   = location.lower().replace(" ", "")
        if existing_location and existing_location != target_location:
            print(f"[AKS Chaos] Existing experiment in '{existing.location}', recreating in '{location}'...")
            client.experiments.begin_delete(node_rg, exp_name).result()
            time.sleep(10)
    except Exception:
        pass

    print(f"[AKS Chaos] Creating zone failure experiment: {exp_name}")
    client.experiments.begin_create_or_update(node_rg, exp_name, experiment).result()

    print(f"[AKS Chaos] Starting: {exp_name}")
    client.experiments.begin_start(node_rg, exp_name).result()

    from rich.live import Live
    from rich.text import Text

    if ui:
        ui.step("Waiting for execution to register...", live=True)
    time.sleep(15)

    poll_interval       = 20
    TICK                = 0.5
    elapsed             = 0
    running             = False
    terminal_ok         = False
    terminal_status     = ""
    nodes_notready_seen = set()
    fault_status        = ""

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
                "  [bold yellow]⚡[/bold yellow]  [dim]Waiting for zone fault to start...[/dim]"
            )
        return Text.from_markup(
            f"  [bold yellow]⚡[/bold yellow]  {bar}  [bold]{timer} remaining[/bold]{extra}"
        )

    max_iters = max(30, duration_secs // poll_interval + 15)

    with Live(_render(duration_secs), console=console,
              refresh_per_second=4, transient=True) as live:
        for _ in range(max_iters):
            try:
                execs = list(client.experiments.list_all_executions(node_rg, exp_name))
                if execs:
                    exe    = client.experiments.get_execution(node_rg, exp_name, execs[0].name)
                    status = exe.status
                    if status == "Running":
                        running = True
                        if session:
                            session.log_event("experiment", "Zone fault Running")
                    if status in ("Succeeded", "Success", "Failed", "Cancelled"):
                        terminal_ok     = status in ("Succeeded", "Success")
                        terminal_status = status
                        if session:
                            session.log_event("experiment", f"Terminal status: {status}")
                        if not terminal_ok or elapsed >= duration_secs:
                            break
            except RuntimeError:
                raise
            except Exception as e:
                live.update(Text.from_markup(
                    f"  [dim yellow]⚠  Polling error (retrying): {e}[/dim yellow]"
                ))

            # Probe nodes + pending pods every poll cycle
            not_ready_now = []
            for t in vmss_targets:
                conds = _get_node_conditions(t["node"])
                if conds.get("Ready") != "True":
                    not_ready_now.append(t["node"])
                    nodes_notready_seen.add(t["node"])
            pending_count = sum(
                1 for item in (_kubectl_json(
                    ["kubectl", "get", "pods", "--all-namespaces",
                     "--field-selector", "status.phase=Pending"]) or {}).get("items", [])
                if not any(o.get("kind") == "DaemonSet"
                           for o in item.get("metadata", {}).get("ownerReferences", []))
            )
            fault_status = (
                f"NotReady: {len(not_ready_now)}/{len(vmss_targets)}"
                f"  pending: {pending_count}"
            )

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
    elif running and ui:
        ui.step("Experiment completed (status poll timed out)", live=True)

    ctx["_zone_snapshot"]["nodes_notready_seen"] = list(nodes_notready_seen)
    state_path = ctx.get("_state_path") or _state_file(ctx.get("experiment_id", "unknown"))
    with open(state_path, "w") as f:
        json.dump(ctx, f)



def _setup_vmss_target(subscription_id, rg, vmss_name):
    """Register VMSS as an Azure Chaos Studio target with all VMSS capabilities."""
    base = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{rg}"
        f"/providers/Microsoft.Compute/virtualMachineScaleSets/{vmss_name}"
        f"/providers/Microsoft.Chaos/targets/Microsoft-VirtualMachineScaleSet"
    )
    api = "?api-version=2024-01-01"

    print(f"[AKS Chaos] Registering VMSS Chaos Studio target ({vmss_name})...")
    _az_rest_put(f"{base}{api}", f"VMSS target ({vmss_name})")

    for cap in ["shutdown-1.0", "shutdown-2.0"]:
        subprocess.run(
            azure_cli_command("rest", "--method", "put",
             "--url", f"{base}/capabilities/{cap}{api}",
             "--body", '{"properties":{}}'),
            capture_output=True)


def _apply_direct(spec, kind, experiment_id, ctx=None, *, ui=None):
    """Fallback: kubectl apply when Studio doesn't support the kind."""
    from chaosforge.interfaces.cli.interactive.ui.console import console
    res_name      = experiment_id.replace("aks-", "test-")
    duration_secs = int((ctx or {}).get("duration", 60))

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": kind,
        "metadata": {"name": res_name, "namespace": CHAOS_NAMESPACE},
        "spec": spec
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     prefix="/tmp/chaos-", delete=False) as f:
        json.dump(manifest, f)
        tmppath = f.name
    try:
        r = _kubectl("apply", "-f", tmppath)
        if r.returncode != 0:
            raise subprocess.CalledProcessError(r.returncode, ["kubectl", "apply", "-f", tmppath],
                                                output=r.stdout, stderr=r.stderr)
    finally:
        os.unlink(tmppath)

    if ui:
        ui.step(f"Chaos Mesh resource applied ({duration_secs}s)", live=True)
    _live_wait(duration_secs, console)
    # Resource is intentionally left in place after the wait so it can be
    # inspected in Chaos Studio / kubectl during debugging. Cleanup is handled
    # by cleanup_experiment via the normal rollback path.


def _live_wait(duration_secs: int, console):
    """Print a live countdown to the console, then return."""
    for elapsed in range(duration_secs):
        remaining = duration_secs - elapsed
        mins, secs = divmod(remaining, 60)
        label = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
        console.print(
            f"\r  [dim]  › {label} remaining   [/dim]",
            end="", highlight=False,
        )
        time.sleep(1)
    console.print("\r" + " " * 40 + "\r", end="", highlight=False)


def _safe_name(experiment_id, ctx=None):
    # Format: chaosforge-<cluster>-<namespace>-<experiment>-<epoch>
    # e.g. chaosforge-myakscluster-pradeep-testing-pod-failure-1733400000
    # The epoch suffix keeps every run's name unique so a re-run never collides
    # with a stale experiment resource left behind by a failed/skipped cleanup,
    # and so the same name is never reused across resource groups/locations.
    parts = ["chaosforge"]
    if ctx:
        cluster   = re.sub(r'[^a-z0-9-]', '', (ctx.get("aks_name") or "").lower())
        namespace = re.sub(r'[^a-z0-9-]', '', (ctx.get("namespace") or "").lower())
        exp       = re.sub(r'[^a-z0-9-]', '', experiment_id.replace("aks-", "").lower())
        if cluster:
            parts.append(cluster)
        if namespace:
            parts.append(namespace)
        parts.append(exp)
    else:
        parts.append(re.sub(r'[^a-z0-9-]', '', experiment_id.lower()))
    suffix = f"-{int(time.time())}"
    # Azure resource names max 64 chars — reserve room for the unique suffix
    base = "-".join(parts)[:64 - len(suffix)]
    return base + suffix




_EXPORTED_FUNCTIONS = (
    "_run_zone_failure",
    "_setup_vmss_target",
    "_apply_direct",
    "_live_wait",
    "_safe_name",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update({name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS})
globals().update(_LOCAL_EXPORTS)
__all__ = list(_EXPORTED_FUNCTIONS)
