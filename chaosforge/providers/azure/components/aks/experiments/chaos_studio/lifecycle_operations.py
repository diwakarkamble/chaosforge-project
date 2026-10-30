"""Lifecycle orchestration for AKS Chaos Studio experiments."""

from typing import Any

from .execution_support import executor_compatible

_ACTIVE_KCTX: Any = None
_apply_direct: Any = None
_build_spec: Any = None
_cleanup_crashloop: Any = None
_cleanup_stress_pod: Any = None
_confirm_destructive_action: Any = None
_get_node_resource_group: Any = None
_get_or_create_chaos_rg: Any = None
_ensure_chaos_mesh_in_chaos_testing: Any = None
_http_chaos_sentinel: Any = None
_http_chaos_teardown: Any = None
_is_true: Any = None
_kubectl: Any = None
_load_state: Any = None
_postchecks_node_drain: Any = None
_postchecks_node_notready: Any = None
_postchecks_node_stress: Any = None
_postchecks_node_taint: Any = None
_postchecks_zone_failure: Any = None
_prechecks_node_drain: Any = None
_prechecks_node_notready: Any = None
_prechecks_node_stress: Any = None
_prechecks_node_taint: Any = None
_prechecks_zone_failure: Any = None
_precreate_studio_experiment: Any = None
_print_dry_run_preview: Any = None
_print_net_impact_summary: Any = None
_print_network_outcome: Any = None
_probe_recovery_status: Any = None
_prompt_precheck_override: Any = None
_reopen_session: Any = None
_resolve_azure_details: Any = None
_run_crashloop: Any = None
_run_node_cpu_stress: Any = None
_run_node_drain: Any = None
_run_node_memory_pressure: Any = None
_run_node_taint: Any = None
_run_studio_experiment: Any = None
_run_vmss_experiment: Any = None
_run_zone_failure: Any = None
_safe_name: Any = None
_save_state_field: Any = None
_setup_studio_target: Any = None
_setup_vmss_target: Any = None
_state_file: Any = None
_ui_warning: Any = None
build_post_experiment_checks: Any = None
check_protected_namespace: Any = None
console: Any = None
DNS_CHAOS_EXPERIMENTS: Any = None
HTTP_CHAOS_EXPERIMENTS: Any = None
IO_CHAOS_EXPERIMENTS: Any = None
json: Any = None
KUBE_SYSTEM_EXPERIMENTS: Any = None
NETWORK_CHAOS_EXPERIMENTS: Any = None
NODE_KUBECTL_EXPERIMENTS: Any = None
NODE_VMSS_EXPERIMENTS: Any = None
os: Any = None
PhaseUI: Any = None
POD_CHAOS_EXPERIMENTS: Any = None
POD_DISRUPTIVE_EXPERIMENTS: Any = None
POD_PINNING_CAPABLE_EXPERIMENTS: Any = None
run_parallel_steady_state: Any = None
STRESS_CHAOS_EXPERIMENTS: Any = None
STUDIO_CAPABILITY: Any = None
subprocess: Any = None
TIME_CHAOS_EXPERIMENTS: Any = None
validate_and_resolve_selector: Any = None
ValidationSession: Any = None
VMSS_CAPABILITY: Any = None

def setup_studio(experiment_id, aks_context, namespace, deployment,
                 chaos_mode="one", chaos_value="",
                 container_name="", dns_pattern="",
                 volume_path="/data", http_port="80",
                 subscription_id="", resource_group="", aks_name="",
                 target_node="", label_key="", label_val="",
                 target_mode="", duration=60, time_offset="", location="", dry_run="false",
                 latency="500ms", jitter="100ms", correlation="50",
                 loss_percentage="25", rate="1mbps",
                  corrupt_percentage="50", duplicate_percentage="50",
                  io_delay="100ms", io_errno="5", io_percent="50",
                  chaos_mesh_version_action="", chaos_mesh_installed_version=""):
    """
    Step 1 — called by ChaosToolkit method[0].
    Resolves Azure details, sets up Studio target, saves state for later steps.
    """
    preview = _is_true(dry_run)
    ui      = PhaseUI(experiment_id)
    stale_state_path = _state_file(experiment_id)
    if os.path.exists(stale_state_path):
        os.unlink(stale_state_path)

    # ── Open ValidationSession — writes logs/experiment-id/<ts>/ ─────────────
    session = ValidationSession(experiment_id)
    session.start()
    session.log_event("setup", f"Starting: {experiment_id}" + (" (DRY RUN)" if preview else ""))

    with ui.phase("setup"):
        ui.step(f"Experiment: {experiment_id}" + (" (DRY RUN)" if preview else ""))

        # Auto-detect Azure details from az login if not provided
        ui.step("Resolving Azure subscription / resource group / cluster...")
        sub, rg, cluster = _resolve_azure_details(
            aks_context, subscription_id, resource_group, aks_name)
        ui.step(f"Cluster: {cluster}  |  RG: {rg}")
        session.log_event("setup", f"Resolved: sub={sub}  rg={rg}  cluster={cluster}")

        chaos_rg = _get_or_create_chaos_rg(sub, location or "eastus")
        ui.step(f"Chaos experiments RG: {chaos_rg}")
        session.log_event("setup", f"Chaos experiments RG: {chaos_rg}")

    # ── Confirmation gate — non-prod guardrail ────────────────────────────────
    # Shown before anything touches the cluster. Raising here aborts the run
    # cleanly with no fault injected.
    # Build a human-readable severity label for the confirmation summary
    _severity_label = {
        "aks-network-delay":       f"latency={latency}  jitter={jitter}  correlation={correlation}%",
        "aks-packet-loss":         f"loss={loss_percentage}%  correlation={correlation}%",
        "aks-bandwidth-limit":     f"rate={rate}",
        "aks-packet-corruption":   f"corrupt={corrupt_percentage}%  correlation={correlation}%",
        "aks-packet-duplication":  f"duplicate={duplicate_percentage}%  correlation={correlation}%",
        "aks-io-latency":          f"delay={io_delay}  percent={io_percent}%",
        "aks-io-errors":           f"errno={io_errno}  percent={io_percent}%",
    }.get(experiment_id, "")

    _confirm_destructive_action(
        experiment_id, sub, rg, cluster, location, namespace, deployment,
        duration, target_node, chaos_mode, chaos_value, dry_run=preview,
        fault_severity=_severity_label,
    )

    # Save state so run_experiment and cleanup can read it.
    # Each run gets its own PID-scoped file so concurrent runs never collide.
    state = {
        "experiment_id":  experiment_id,
        "aks_context":    aks_context,
        "namespace":      namespace,
        "deployment":     deployment,
        "chaos_mode":     chaos_mode,
        "chaos_value":    chaos_value,
        "container_name": container_name,
        "dns_pattern":    dns_pattern,
        "volume_path":    volume_path,
        "http_port":      http_port,
        "subscription_id": sub,
        "resource_group":  rg,
        "aks_name":        cluster,
        "location":        location,
        "target_node":     target_node,
        "label_key":       label_key,
        "label_val":       label_val,
        "target_mode":     target_mode,
        "duration":        int(duration),
        "time_offset":     time_offset,
        "dry_run":         preview,
        "chaos_rg":        chaos_rg,
        "_state_path":     _state_file(experiment_id),
        "_log_dir":        session.log_dir,
        "latency":            str(latency),
        "jitter":             str(jitter),
        "correlation":        str(correlation),
        "loss_percentage":    str(loss_percentage),
        "rate":               str(rate),
        "corrupt_percentage": str(corrupt_percentage),
        "duplicate_percentage": str(duplicate_percentage),
        "io_delay":           str(io_delay),
        "io_errno":           str(io_errno),
        "io_percent":         str(io_percent),
        "chaos_mesh_version_action": str(chaos_mesh_version_action),
        "chaos_mesh_installed_version": str(chaos_mesh_installed_version),
    }
    with open(state["_state_path"], "w") as f:
        json.dump(state, f)

    # Switch kubectl context. Routed through the shared Python-client
    # dispatcher (services.k8s_client.set_current_kube_context — a direct
    # kubeconfig YAML rewrite, since context switching is a local file
    # operation, not a cluster API call); falls back to real kubectl only
    # if that dispatcher path doesn't apply. We still record it as the
    # ambient context so the dispatcher-routed calls below (which don't
    # pass --context explicitly) target the right cluster.
    _kubectl("config", "use-context", aks_context)
    _ACTIVE_KCTX["context"] = aks_context

    # ── HTTPChaos: detect leftover setup from a previously aborted run ───────
    # If the operator aborted a previous run after setup but before cleanup,
    # the namespace label and securityContext patch are still in place.
    # Detect via a PID-less sentinel file written at setup and deleted at teardown.
    # Unlike the per-run state file (which includes PID), this persists across
    # process restarts so the next run reliably finds it.
    if experiment_id in HTTP_CHAOS_EXPERIMENTS and namespace and deployment:
        _sentinel_path = _http_chaos_sentinel(experiment_id, namespace, deployment)
        if os.path.exists(_sentinel_path):
            try:
                with open(_sentinel_path) as _sf:
                    _prev = json.load(_sf)
                with ui.phase("http-chaos-setup"):
                    ui.step("Detected leftover HTTPChaos setup from aborted run — cleaning up first")
                    _http_chaos_teardown(
                        experiment_id, aks_context, namespace, deployment,
                        _prev.get("_http_orig_allow_privilege_escalation", {}),
                        session=None,
                    )
                # Sentinel deleted inside _http_chaos_teardown after cleanup
            except (ValueError, KeyError, OSError):
                pass

    # ── HTTPChaos: label namespace + patch securityContext ───────────────────
    # nsexec requires allowPrivilegeEscalation on target pod containers.
    # Gatekeeper blocks it cluster-wide except namespaces labeled
    # chaos-experiments=enabled. Label first, then patch deployment, then
    # rolling restart so new pods start without the restriction before
    # chaos-daemon tries to inject. Original value saved to state for rollback.
    if experiment_id in HTTP_CHAOS_EXPERIMENTS and namespace and deployment:
        with ui.phase("http-chaos-setup"):
            ui.step(f"Labeling namespace {namespace} for HTTPChaos (chaos-experiments=enabled)")
            _kubectl("label", "namespace", namespace, "chaos-experiments=enabled",
                    "--overwrite", context=aks_context)
            if session:
                session.log_event("http-chaos-setup",
                    f"Namespace labeled: {namespace} chaos-experiments=enabled")

            # Snapshot existing allowPrivilegeEscalation values per container
            # so rollback restores exactly what was there, not a hardcoded false.
            r_dep = _kubectl("get", "deployment", deployment, "-n", namespace,
                             "-o", "json", context=aks_context)
            _orig_ape: dict[str, bool | None] = {}
            if r_dep.returncode == 0:
                try:
                    _dep_json = json.loads(r_dep.stdout)
                    for _c in _dep_json.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
                        _sc = _c.get("securityContext") or {}
                        _orig_ape[_c["name"]] = _sc.get("allowPrivilegeEscalation")  # None = not set
                except (ValueError, KeyError):
                    pass
            _save_state_field(state, "_http_orig_allow_privilege_escalation", _orig_ape)

            # Patch: remove allowPrivilegeEscalation=false from every container
            # that has it. Containers where it was not set are left untouched.
            _containers_patched = []
            if r_dep.returncode == 0:
                try:
                    _dep_json = json.loads(r_dep.stdout)
                    _containers = _dep_json.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
                    _patch_ops = []
                    for _i, _c in enumerate(_containers):
                        if (_c.get("securityContext") or {}).get("allowPrivilegeEscalation") is False:
                            _patch_ops.append({
                                "op": "remove",
                                "path": f"/spec/template/spec/containers/{_i}/securityContext/allowPrivilegeEscalation"
                            })
                            _containers_patched.append(_c["name"])
                    if _patch_ops:
                        ui.step(f"Removing allowPrivilegeEscalation=false from: {_containers_patched}")
                        _kubectl("patch", "deployment", deployment, "-n", namespace,
                                "--type=json", f"-p={json.dumps(_patch_ops)}", context=aks_context)
                        if session:
                            session.log_event("http-chaos-setup",
                                f"Patched containers: {_containers_patched}")

                        # Rolling restart so pods come up without restriction
                        ui.step(f"Rolling restart: {deployment}")
                        _kubectl("rollout", "restart", f"deployment/{deployment}", "-n", namespace,
                                context=aks_context)
                        _kubectl("rollout", "status", f"deployment/{deployment}", "-n", namespace,
                                "--timeout=120s", context=aks_context, timeout=130)
                        if session:
                            session.log_event("http-chaos-setup",
                                f"Rolling restart complete: {deployment}")
                    else:
                        ui.step("No allowPrivilegeEscalation=false found — no patch needed")
                except (ValueError, KeyError):
                    pass

    if experiment_id in HTTP_CHAOS_EXPERIMENTS and namespace and deployment:
        # Write PID-less sentinel so next run detects leftover if this run aborts
        _sentinel_path = _http_chaos_sentinel(experiment_id, namespace, deployment)
        try:
            with open(_sentinel_path, "w") as _sf:
                json.dump({
                    "_http_orig_allow_privilege_escalation": state.get(
                        "_http_orig_allow_privilege_escalation", {}
                    ),
                }, _sf)
        except OSError:
            pass

    # ── Pre-flight safety checks (serial guardrails) ─────────────────────────
    with ui.phase("pre-check"):
        if namespace and experiment_id not in KUBE_SYSTEM_EXPERIMENTS:
            ui.step(f"Checking protected namespace: {namespace}")
            check_protected_namespace(namespace)

        # Node experiments use dedicated node/VMSS checks below. Running the
        # generic workload profile as well produces false validation failures.
        run_workload_checks = experiment_id not in (
            NODE_KUBECTL_EXPERIMENTS | NODE_VMSS_EXPERIMENTS
        )
        _extended  = TIME_CHAOS_EXPERIMENTS | HTTP_CHAOS_EXPERIMENTS | DNS_CHAOS_EXPERIMENTS | IO_CHAOS_EXPERIMENTS
        _label_key = label_key if experiment_id in (POD_DISRUPTIVE_EXPERIMENTS | STRESS_CHAOS_EXPERIMENTS | NETWORK_CHAOS_EXPERIMENTS | _extended) else ""
        _label_val = label_val if experiment_id in (POD_DISRUPTIVE_EXPERIMENTS | STRESS_CHAOS_EXPERIMENTS | NETWORK_CHAOS_EXPERIMENTS | _extended) else ""

        session.log_event("pre-check", "Running parallel steady-state checks")
        _network_targeting = experiment_id in NETWORK_CHAOS_EXPERIMENTS
        _pod_pinning_capable = experiment_id in POD_PINNING_CAPABLE_EXPERIMENTS
        if run_workload_checks:
            try:
                run_parallel_steady_state(
                    aks_context,
                    namespace      = namespace  if experiment_id not in KUBE_SYSTEM_EXPERIMENTS else "",
                    deployment     = deployment if experiment_id not in KUBE_SYSTEM_EXPERIMENTS else "",
                    label_key      = _label_key,
                    label_val      = _label_val,
                    phase          = "pre-check",
                    session        = session,
                    experiment_id  = experiment_id,
                    container_name = container_name,
                    dns_pattern    = dns_pattern,
                    http_port      = http_port,
                    target_mode    = target_mode if _pod_pinning_capable else "",
                    exact_pod_name = (
                        deployment if _pod_pinning_capable and target_mode == "pod" else ""
                    ),
                    volume_path    = volume_path,
                )
                session.log_event("pre-check", "All pre-experiment checks passed")
                if experiment_id in IO_CHAOS_EXPERIMENTS:
                    # Reuse the pre-check's own measured baseline instead of
                    # re-probing separately later — a second, independent probe
                    # taken ~15-40s later (after capability registration) adds
                    # its own noise/jitter on top of an already-noisy metric,
                    # producing a confusing "Before fault" number in the final
                    # summary that doesn't match what the pre-check displayed.
                    import re as _re
                    _detail = str(
                        session._results.get("Baseline File I/O Timing", {}).get("detail", "")
                    )
                    _m = _re.search(r"round-trip = (\d+)ms", _detail)
                    if _m:
                        _save_state_field(state, "_io_baseline_ms", int(_m.group(1)))
            except RuntimeError as exc:
                session.log_event("pre-check", f"Pre-checks FAILED — operator override will be prompted: {exc}")
                _save_state_field(state, "_precheck_failures", str(exc))
        else:
            session.log_event("pre-check", "Using dedicated node/VMSS prechecks")

        # ── Selector-scope validation — catches the case where the naive label
        # selector above would ALSO match sibling Deployments sharing the same
        # labels (e.g. two Deployments both carrying app.kubernetes.io/instance=X).
        # Only runs for experiments that target pods via a label selector.
        if _label_key and _label_val and experiment_id not in KUBE_SYSTEM_EXPERIMENTS:
            ui.step("Validating selector scope (checking for label collisions with sibling resources)...")
            scope_result = validate_and_resolve_selector(
                aks_context, namespace, deployment, target_mode,
                _label_key, _label_val, ui=ui, session=session,
                exact_pod_targeting=_pod_pinning_capable,
            )
            if _pod_pinning_capable and scope_result.get("exact_pod_name"):
                _save_state_field(state, "exact_pod_name", scope_result["exact_pod_name"])
                ui.step(scope_result["warning"], live=True)
                # Pod-mode pinning only tightens the source-side selector
                # (spec.selector via fieldSelectors). Network Partition's
                # second target-side selector (spec.target.selector) is
                # untouched by exact_pod_name, so also persist any
                # label_selectors_map resolved alongside it — _build_spec()
                # uses this to scope spec.target.selector.labelSelectors to
                # just the exact pod's owning Deployment instead of the
                # naive selector that can match sibling Deployments.
                if scope_result.get("label_selectors_map"):
                    _save_state_field(state, "label_selectors_map", scope_result["label_selectors_map"])
            elif scope_result.get("label_selectors_map"):
                _save_state_field(state, "label_selectors_map", scope_result["label_selectors_map"])
                ui.step(f"Selector scope: {scope_result['warning']}", live=True)
            elif not scope_result.get("ok"):
                session.log_event("pre-check", f"Selector-scope validation FAILED: {scope_result.get('warning')}")
                if scope_result.get("hard_block"):
                    raise RuntimeError(scope_result["warning"])
                _save_state_field(
                    state, "_precheck_failures",
                    state.get("_precheck_failures", "") +
                    f"\nSelector-scope validation failed: {scope_result.get('warning')}"
                )
            else:
                ui.step("Selector scope OK — no label collision detected", live=True)

        # ── Node kubectl pre-checks — run in this phase so they appear alongside
        # the steady-state checks above, matching the pod experiment structure.
        if experiment_id in NODE_KUBECTL_EXPERIMENTS and target_node:
            if experiment_id == "aks-node-drain":
                ok, snapshot = _prechecks_node_drain(target_node, ui=ui, session=session, cluster=cluster)
            elif experiment_id == "aks-node-taint":
                ok, snapshot = _prechecks_node_taint(target_node, ui=ui, session=session, cluster=cluster)
            elif experiment_id in ("aks-node-cpu-stress", "aks-node-memory-pressure"):
                kind = "cpu" if "cpu" in experiment_id else "memory"
                ok, snapshot = _prechecks_node_stress(target_node, kind, ui=ui, session=session, cluster=cluster)
            else:
                ok, snapshot = True, {}
            _save_state_field(state, "_node_precheck_ok", ok)
            _save_state_field(state, "_node_precheck_snapshot", snapshot)
            if not ok:
                session.log_event("pre-check", f"Node pre-checks FAILED for {target_node}")
                _save_state_field(state, "_precheck_failures",
                                  state.get("_precheck_failures", "") +
                                  f"\nNode pre-checks failed for {target_node}")

        # ── VMSS node pre-checks (node-notready / zone-failure) —────────────
        # Resolve VMSS details here (read-only discovery) so full pre-checks
        # run in Phase 2 alongside the steady-state checks above.
        # Studio target registration still happens in Phase 3.
        elif experiment_id in NODE_VMSS_EXPERIMENTS and target_node:
            from chaosforge.providers.azure.components.aks.discovery import (
                AzureAKSDiscovery,
            )
            discovery  = AzureAKSDiscovery()
            node_rg    = _get_node_resource_group(sub, rg, cluster)
            target_nodes = [n.strip() for n in target_node.split(",") if n.strip()]
            if len(target_nodes) > 1:
                vmss_targets = []
                for tn in target_nodes:
                    vn, vi = discovery.get_vmss_instance_for_node(aks_context, tn, sub, node_rg)
                    if vn:
                        vmss_targets.append({"node": tn, "vmss_name": vn, "instance_id": vi})
                if not vmss_targets:
                    raise RuntimeError("Could not find VMSS instances for zone nodes.")
                state["node_rg"]      = node_rg
                state["vmss_targets"] = vmss_targets
                ok, snapshot = _prechecks_zone_failure(
                    vmss_targets, sub, node_rg, ui=ui, session=session, cluster=cluster)
            else:
                vmss_name, instance_id = discovery.get_vmss_instance_for_node(
                    aks_context, target_node, sub, node_rg)
                if not vmss_name:
                    raise RuntimeError(
                        f"Could not find VMSS instance for node '{target_node}'. "
                        "Ensure az login is active.")
                state["node_rg"]     = node_rg
                state["vmss_name"]   = vmss_name
                state["instance_id"] = instance_id
                ok, snapshot = _prechecks_node_notready(
                    target_node, sub, node_rg, vmss_name, instance_id, ui=ui, session=session, cluster=cluster)
            _save_state_field(state, "_node_precheck_ok", ok)
            _save_state_field(state, "_node_precheck_snapshot", snapshot)
            if not ok:
                _save_state_field(state, "_precheck_failures",
                                  state.get("_precheck_failures", "") +
                                  f"\nNode pre-checks failed for {target_node}")

        elif experiment_id in NODE_VMSS_EXPERIMENTS:
            _save_state_field(state, "_node_precheck_snapshot", {})
    # pre-check phase closes here — Studio registration is a separate phase below

    # ── Node kubectl experiments — Phase 3 target summary (no Studio needed) ──
    if experiment_id in NODE_KUBECTL_EXPERIMENTS:
        with ui.phase("experiment-setup"):
            fault_map = {
                "aks-node-drain":           ("kubectl drain", "evicts all non-DaemonSet pods, marks unschedulable"),
                "aks-node-taint":           ("kubectl taint", "adds NoExecute taint, evicts non-tolerating pods"),
                "aks-node-cpu-stress":      ("stress-ng pod", f"exhausts CPU on node for {int(duration)}s"),
                "aks-node-memory-pressure": ("stress-ng pod", f"exhausts memory on node for {int(duration)}s"),
                "aks-crashloop":            ("PodChaos loop", f"repeatedly kills target container for {int(duration)}s"),
            }
            engine, description = fault_map.get(experiment_id, ("kubectl", "direct node operation"))
            ui.step(f"Fault engine  : {engine}")
            ui.step(f"Target node   : {target_node}")
            ui.step(f"What it does  : {description}")
            ui.step("No Azure Chaos Studio target registration needed for this experiment type")
            if preview:
                ui.step("DRY RUN — no changes will be made")
            session.log_event("experiment-setup",
                              f"Node kubectl experiment — engine={engine}  node={target_node}")
            if experiment_id == "aks-crashloop" and not preview:
                _ensure_chaos_mesh_in_chaos_testing(
                    ui=ui,
                    session=session,
                    aks_context=aks_context,
                    action=chaos_mesh_version_action,
                    expected_installed_version=chaos_mesh_installed_version or None,
                )

    # Azure Chaos Studio target registration + experiment pre-creation — one phase block
    # Node kubectl and VMSS experiments don't need the Chaos Mesh Studio target
    if experiment_id not in NODE_KUBECTL_EXPERIMENTS and experiment_id not in NODE_VMSS_EXPERIMENTS:
        with ui.phase("experiment-setup"):
            if preview:
                ui.step("DRY RUN — skipping Azure Chaos Studio target registration", live=True)
            else:
                _setup_studio_target(
                    sub, rg, cluster, aks_context=aks_context, ui=ui, session=session,
                    chaos_mesh_version_action=chaos_mesh_version_action,
                    chaos_mesh_installed_version=chaos_mesh_installed_version,
                )
            session.log_event(
                "experiment-setup",
                "Studio target registration complete" + (" (DRY RUN)" if preview else ""),
            )

            # ── Pre-create the Studio experiment ARM resource ─────────────────
            # begin_create_or_update takes 10–20s and has no side effects until
            # begin_start is called, so doing it here moves that cost out of phase 4.
            # Only for Chaos Mesh Studio experiments (not node/VMSS paths).
            if not preview:
                _spec, json_spec, kind = _build_spec(experiment_id, state)
                capability_urn = STUDIO_CAPABILITY.get(kind)
                if capability_urn:
                    exp_name = _safe_name(experiment_id, state)
                    _save_state_field(state, "studio_experiment_name", exp_name)
                    _save_state_field(state, "_json_spec", json_spec)
                    _save_state_field(state, "_capability_urn", capability_urn)
                    ui.step(f"Pre-creating Studio experiment: {exp_name}")
                    session.log_event("experiment-setup", f"Pre-creating experiment ARM resource: {exp_name}")
                    _precreate_studio_experiment(
                        exp_name, json_spec, capability_urn,
                        sub, chaos_rg, cluster, state,
                        ui=ui, session=session,
                    )
                    _save_state_field(state, "_experiment_pre_created", True)
                    session.log_event("experiment-setup", f"Experiment ARM resource ready: {exp_name}")

    # ── VMSS experiments — Phase 3 target summary / Studio registration ────────
    if experiment_id in NODE_VMSS_EXPERIMENTS:
        with ui.phase("experiment-setup"):
            node_rg      = state.get("node_rg") or _get_node_resource_group(sub, rg, cluster)
            vmss_targets = state.get("vmss_targets")
            vmss_name    = state.get("vmss_name")
            vmss_label   = "(multi)" if vmss_targets else (vmss_name or target_node)
            if preview:
                ui.step("Fault engine  : VMSS fault via Azure Chaos Studio")
                ui.step(f"Target node   : {target_node}")
                ui.step(f"VMSS target   : {vmss_label}")
                ui.step("DRY RUN — skipping Azure Chaos Studio target registration")
                session.log_event("experiment-setup", f"VMSS dry run — target={vmss_label}")
            else:
                if vmss_targets:
                    for t in vmss_targets:
                        _setup_vmss_target(sub, node_rg, t["vmss_name"])
                elif vmss_name:
                    _setup_vmss_target(sub, node_rg, vmss_name)
                ui.step(f"Node '{target_node}' → VMSS '{vmss_label}' registered", live=True)
                session.log_event("experiment-setup", f"VMSS Studio target registered: {vmss_label}")

    session.log_event("setup", "Setup complete" + (" (DRY RUN)" if preview else ""))

    # Mark setup phase as done so run_experiment knows the state file is valid
    # and was written by this run (not stale from a prior PID collision).
    _save_state_field(state, "_setup_complete", True)


# ─── STEP 2: RUN ─────────────────────────────────────────────────────────────
def run_experiment(experiment_id, aks_context, namespace, deployment,
                   chaos_mode="one", chaos_value="",
                   container_name="", dns_pattern="",
                   volume_path="/data", http_port="80",
                   subscription_id="", resource_group="", aks_name="",
                   target_node="", label_key="", label_val="",
                   duration=60, dry_run="false",
                   latency="500ms", jitter="100ms", correlation="50",
                   loss_percentage="25", rate="1mbps",
                   corrupt_percentage="50", duplicate_percentage="50",
                   io_delay="100ms", io_errno="5", io_percent="50"):
    """
    Step 2 — called by ChaosToolkit method[1].
    Loads state, builds spec, routes to kubectl / VMSS Studio / Chaos Mesh Studio.
    """
    state = _load_state(experiment_id)

    # Guard: state file missing or from a different run — hard abort.
    if not state.get("_setup_complete"):
        raise RuntimeError(
            "setup_studio did not complete successfully (pre-checks may have failed). "
            "Refusing to inject fault. Check the pre-check output above for details."
        )

    # Pre-checks failed — ask the operator whether to override and proceed anyway.
    precheck_failures = state.get("_precheck_failures")
    if precheck_failures:
        _prompt_precheck_override(experiment_id, precheck_failures)

    sub      = state.get("subscription_id", subscription_id)
    rg       = state.get("resource_group", resource_group)
    chaos_rg = state.get("chaos_rg") or rg
    cluster  = state.get("aks_name", aks_name)
    node     = state.get("target_node", target_node)
    preview  = _is_true(state.get("dry_run", dry_run))

    ui = PhaseUI(experiment_id)

    # Reattach ValidationSession if setup wrote a log_dir into state
    session = _reopen_session(experiment_id, state)

    if preview:
        with ui.phase("experiment"):
            ui.step("DRY RUN — no fault will be injected")
            _print_dry_run_preview(experiment_id, node, state)
        return

    # notify_experiment_start(experiment_id, namespace, cluster)

    with ui.phase("experiment"):
        if session:
            session.log_event("experiment", f"Starting fault: {experiment_id}")

        # ── kubectl-based node experiments ───────────────────────────────────────
        if experiment_id == "aks-node-drain":
            ui.step(f"Draining node: {node}")
            _run_node_drain(node, state, ui=ui)
            if session:
                session.log_event("experiment", f"Node drain complete: {node}")
            return

        if experiment_id == "aks-node-taint":
            ui.step(f"Tainting node: {node}")
            _run_node_taint(node, state, ui=ui)
            if session:
                session.log_event("experiment", f"Node taint complete: {node}")
            return

        if experiment_id == "aks-node-cpu-stress":
            ui.step(f"Deploying CPU stress pod on node: {node}")
            _run_node_cpu_stress(node, state, ui=ui)
            if session:
                session.log_event("experiment", f"Node CPU stress complete: {node}")
            return

        if experiment_id == "aks-node-memory-pressure":
            ui.step(f"Deploying memory stress pod on node: {node}")
            _run_node_memory_pressure(node, state, ui=ui)
            if session:
                session.log_event("experiment", f"Node memory pressure complete: {node}")
            return

        if experiment_id == "aks-crashloop":
            ui.step("Forcing target pod into CrashLoopBackOff")
            _run_crashloop(state, ui=ui)
            if session:
                session.log_event("experiment", "Crashloop injection complete")
            return

        # ── VMSS Azure Chaos Studio experiments ──────────────────────────────────
        if experiment_id in NODE_VMSS_EXPERIMENTS:
            spec, _, kind = _build_spec(experiment_id, state)
            capability_urn = VMSS_CAPABILITY.get(kind)
            if not capability_urn:
                raise RuntimeError(f"No VMSS capability URN for kind: {kind}")
            exp_name = _safe_name(experiment_id, state)
            _save_state_field(state, "studio_experiment_name", exp_name)
            node_rg      = state.get("node_rg") or _get_node_resource_group(sub, rg, cluster)
            vmss_targets = state.get("vmss_targets")
            if vmss_targets:
                ui.step(f"Targeting {len(vmss_targets)} VMSS node(s) (zone failure)")
                _run_zone_failure(exp_name, spec, capability_urn, sub, node_rg, rg, cluster, vmss_targets, state, ui=ui, session=session)
            else:
                ui.step(f"Targeting VMSS node: {node}")
                _run_vmss_experiment(exp_name, spec, capability_urn, sub, node_rg, rg, cluster, node, state, ui=ui, session=session)
            return

        # ── Chaos Mesh via Azure Chaos Studio (default) ───────────────────────────
        spec, json_spec, kind = _build_spec(experiment_id, state)

        capability_urn = STUDIO_CAPABILITY.get(kind)
        if not capability_urn:
            ui.step(f"Kind '{kind}' not supported by Studio — applying direct Chaos Mesh")
            if session:
                session.log_event("experiment", f"Direct Chaos Mesh: kind={kind}")
            _apply_direct(spec, kind, experiment_id, state, ui=ui)
            return

        # Use name/spec/urn from setup if experiment was pre-created there;
        # otherwise generate them fresh (backward-compat / non-pre-created path).
        exp_name       = state.get("studio_experiment_name") or _safe_name(experiment_id, state)
        json_spec      = state.get("_json_spec") or json_spec
        capability_urn = state.get("_capability_urn") or capability_urn
        _save_state_field(state, "studio_experiment_name", exp_name)

        if state.get("_experiment_pre_created"):
            ui.step(f"Studio experiment pre-created in setup — starting: {exp_name}")
        else:
            ui.step(f"Creating Studio experiment: {exp_name}")
        _run_studio_experiment(exp_name, json_spec, capability_urn, sub, chaos_rg, cluster, state, ui=ui, session=session)



from . import lifecycle_cleanup as _lifecycle_cleanup

cleanup_experiment = _lifecycle_cleanup._LOCAL_EXPORTS["cleanup_experiment"]

_EXPORTED_FUNCTIONS = (
    "setup_studio",
    "run_experiment",
    "cleanup_experiment",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update(
    {name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS}
)
__all__ = list(_EXPORTED_FUNCTIONS)
