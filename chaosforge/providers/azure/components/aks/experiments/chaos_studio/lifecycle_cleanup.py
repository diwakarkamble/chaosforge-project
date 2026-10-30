"""Extracted AKS Chaos Studio operations."""

from typing import Any

from .execution_support import executor_compatible

_cleanup_crashloop: Any = None
_cleanup_stress_pod: Any = None
_http_chaos_teardown: Any = None
_is_true: Any = None
_kubectl: Any = None
_load_state: Any = None
_postchecks_node_drain: Any = None
_postchecks_node_notready: Any = None
_postchecks_node_stress: Any = None
_postchecks_node_taint: Any = None
_postchecks_zone_failure: Any = None
_print_net_impact_summary: Any = None
_print_network_outcome: Any = None
_print_io_impact_summary: Any = None
_probe_recovery_status: Any = None
_reopen_session: Any = None
_state_file: Any = None
_ui_warning: Any = None
build_post_experiment_checks: Any = None
console: Any = None
DNS_CHAOS_EXPERIMENTS: Any = None
HTTP_CHAOS_EXPERIMENTS: Any = None
IO_CHAOS_EXPERIMENTS: Any = None
KUBE_SYSTEM_EXPERIMENTS: Any = None
NETWORK_CHAOS_EXPERIMENTS: Any = None
os: Any = None
PhaseUI: Any = None
POD_CHAOS_EXPERIMENTS: Any = None
POD_PINNING_CAPABLE_EXPERIMENTS: Any = None
run_parallel_steady_state: Any = None
STRESS_CHAOS_EXPERIMENTS: Any = None
subprocess: Any = None
TIME_CHAOS_EXPERIMENTS: Any = None
ValidationSession: Any = None

def cleanup_experiment(experiment_id, aks_context, namespace, deployment,
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
    """Roll back Kubernetes changes and clean up experiment resources."""
    state      = _load_state(experiment_id)
    if not state:
        print("[AKS Chaos] Setup did not complete; no injected fault requires cleanup.")
        return
    node       = state.get("target_node", target_node)
    preview    = _is_true(state.get("dry_run", dry_run))
    state_path = state.get("_state_path") or _state_file(experiment_id)
    state.get("aks_name", aks_name)

    ui      = PhaseUI(experiment_id)
    session = _reopen_session(experiment_id, state)

    if preview:
        with ui.phase("rollback"):
            ui.step("DRY RUN — nothing was injected, no rollback needed")
        if session:
            session.log_event("rollback", "DRY RUN — skipping rollback")
            session.stop()
        if os.path.exists(state_path):
            os.unlink(state_path)
        return

    with ui.phase("rollback"):
        if session:
            session.log_event("rollback", f"Starting rollback: {experiment_id}")

        if experiment_id == "aks-node-drain":
            if node:
                ui.step(f"Uncordoning node: {node}")
                _kubectl("uncordon", node)
                if session:
                    session.log_event("rollback", f"Node uncordoned: {node}")

        elif experiment_id == "aks-node-taint":
            if node:
                ui.step(f"Removing chaos taint from node: {node}")
                _kubectl("taint", "nodes", node, "chaos=test:NoExecute-")
                if session:
                    session.log_event("rollback", f"Taint removed: {node}")

        elif experiment_id in ("aks-node-cpu-stress", "aks-node-memory-pressure"):
            ui.step("Cleaning up stress pod")
            _cleanup_stress_pod(experiment_id, node)
            if session:
                session.log_event("rollback", f"Stress pod cleaned up: {node}")

        elif experiment_id == "aks-crashloop":
            ui.step("Removing crashloop PodChaos")
            _cleanup_crashloop(state)
            if session:
                session.log_event("rollback", "Crashloop PodChaos removed")

        # Explicit deletion prevents stale Chaos Mesh resources from affecting
        # later runs when controller cleanup is delayed or incomplete.
        _MESH_CRD_KINDS = {
            "aks-dns-failure":         "dnschaos",
            "aks-http-delay":          "httpchaos",
            "aks-http-abort":          "httpchaos",
            "aks-clock-skew-forward":  "timechaos",
            "aks-clock-skew-backward": "timechaos",
            # Crashloop manages its uniquely named resources separately.
            "aks-pod-kill":            "podchaos",
            "aks-pod-failure":         "podchaos",
            "aks-container-kill":      "podchaos",
            "aks-coredns-kill":        "podchaos",
            "aks-kube-proxy-kill":     "podchaos",
            "aks-coredns-cpu":         "stresschaos",
            "aks-io-latency":          "iochaos",
            "aks-io-errors":           "iochaos",
        }
        _crd_kind = _MESH_CRD_KINDS.get(experiment_id)
        if _crd_kind:
            ui.step(f"Deleting {_crd_kind} CRD resources from chaos-testing")
            # Do not block on finalizers; cleanup failures are logged separately.
            try:
                r = _kubectl("delete", _crd_kind, "--all", "--wait=false",
                             "-n", "chaos-testing", context=aks_context, timeout=30)
                if session:
                    if r.returncode == 0:
                        session.log_event("rollback", f"{_crd_kind} CRD resources deleted")
                    else:
                        session.log_event("rollback",
                            f"{_crd_kind} delete returned non-zero: {r.stderr.strip()[:120]}")
            except subprocess.TimeoutExpired:
                ui.step(f"⚠ {_crd_kind} delete timed out — continuing (non-blocking cleanup)")
                if session:
                    session.log_event("rollback",
                        f"{_crd_kind} delete timed out after 30s — cleanup incomplete, "
                        "non-fatal")
            except Exception as _exc:
                ui.step(f"⚠ {_crd_kind} delete failed — continuing (non-blocking cleanup)")
                if session:
                    session.log_event("rollback", f"{_crd_kind} delete raised: {_exc}")

        # Retain the uniquely named Studio resource for audit and cost tracking.
        exp_name = state.get("studio_experiment_name")
        if exp_name and session:
            session.log_event("rollback", f"Studio resource retained: {exp_name}")

        # Network chaos experiments: Azure Studio cleanup can be slow or incomplete.
        # Explicitly delete all NetworkChaos resources so post-checks find a clean slate.
        # Wrapped in try/except — this is best-effort cleanup and must not fail
        # PHASE 5 › Rollback / the whole campaign if kubectl hangs or errors.
        if experiment_id in NETWORK_CHAOS_EXPERIMENTS:
            ctx = state.get("aks_context", aks_context)
            try:
                _kubectl("delete", "networkchaos", "--all", "-n", "chaos-testing",
                        "--request-timeout=15s", context=ctx, timeout=30)
                if session:
                    session.log_event("rollback", "NetworkChaos resources cleanup attempted")
            except subprocess.TimeoutExpired:
                if session:
                    session.log_event("rollback",
                        "networkchaos delete timed out after 30s — cleanup incomplete, "
                        "non-fatal")
            except Exception as _exc:
                if session:
                    session.log_event("rollback", f"networkchaos delete raised: {_exc}")

        # ── HTTPChaos: restore securityContext + remove namespace label ─────────
        if experiment_id in HTTP_CHAOS_EXPERIMENTS and namespace and deployment:
            ui.step(f"Restoring HTTPChaos setup: {deployment}")
            _http_chaos_teardown(
                experiment_id, aks_context, namespace, deployment,
                state.get("_http_orig_allow_privilege_escalation", {}),
                session=session,
            )
            # Wait for rollout to complete before post-checks run.
            # The teardown does a rolling restart to restore allowPrivilegeEscalation=false.
            # Spring Boot / large JVM images can take 90-120s to start — post-checks
            # running while pods are mid-restart flag probe failures that are not
            # chaos-induced. Rollout status blocks until all replicas are ready.
            ui.step(f"Waiting for rollout to complete before post-checks: {deployment}")
            _kubectl("rollout", "status", f"deployment/{deployment}", "-n", namespace,
                    "--timeout=180s", context=aks_context, timeout=190)
            if session:
                session.log_event("rollback",
                    f"Rollout complete — post-checks can now run cleanly: {deployment}")

        ui.step("Rollback actions complete")

    # ── Post-experiment validation (experiment-specific) ─────────────────────
    with ui.phase("post-check"):
        if session:
            session.log_event("post-check", "Running post-experiment checks")
        try:
            # ── Node kubectl post-checks — mirror pod structure: run here in
            # post-check phase with session logging, not inside rollback phase.
            if experiment_id == "aks-node-drain" and node:
                session.log_event("post-check", f"Running node drain post-checks: {node}")
                _postchecks_node_drain(node, state=state, ui=ui, session=session)
                session.log_event("post-check", "Node drain post-checks complete")

            elif experiment_id == "aks-node-taint" and node:
                session.log_event("post-check", f"Running node taint post-checks: {node}")
                _postchecks_node_taint(node, state=state, ui=ui, session=session)
                session.log_event("post-check", "Node taint post-checks complete")

            elif experiment_id in ("aks-node-cpu-stress", "aks-node-memory-pressure") and node:
                kind     = state.get("_stress_kind", "cpu" if "cpu" in experiment_id else "memory")
                snapshot = state.get("_stress_snapshot", {})
                session.log_event("post-check", f"Running node stress post-checks: {node} [{kind}]")
                _postchecks_node_stress(node, kind, snapshot, ui=ui, session=session)
                session.log_event("post-check", "Node stress post-checks complete")

            elif experiment_id == "aks-node-notready" and node:
                sub_s       = state.get("subscription_id", subscription_id)
                node_rg     = state.get("node_rg", "")
                vmss_name   = state.get("vmss_name", "")
                instance_id = state.get("instance_id", "")
                if vmss_name:
                    session.log_event("post-check", f"Running node notready post-checks: {node}")
                    _postchecks_node_notready(node, sub_s, node_rg, vmss_name, instance_id,
                                              state=state, ui=ui, session=session)
                    session.log_event("post-check", "Node notready post-checks complete")

            elif experiment_id == "aks-node-zone-failure":
                vmss_targets = state.get("vmss_targets", [])
                sub_s        = state.get("subscription_id", subscription_id)
                node_rg      = state.get("node_rg", "")
                snapshot     = state.get("_zone_snapshot", {})
                if vmss_targets:
                    session.log_event("post-check", "Running zone failure post-checks")
                    _postchecks_zone_failure(vmss_targets, sub_s, node_rg, snapshot,
                                             ui=ui, session=session)
                    session.log_event("post-check", "Zone failure post-checks complete")

            elif experiment_id in (POD_CHAOS_EXPERIMENTS | STRESS_CHAOS_EXPERIMENTS
                                    | NETWORK_CHAOS_EXPERIMENTS | TIME_CHAOS_EXPERIMENTS
                                    | HTTP_CHAOS_EXPERIMENTS | DNS_CHAOS_EXPERIMENTS
                                    | IO_CHAOS_EXPERIMENTS):
                post_checks = build_post_experiment_checks(
                    experiment_id, aks_context, namespace, deployment, label_key, label_val,
                    dns_pattern=state.get("dns_pattern", dns_pattern),
                    target_mode=(
                        state.get("target_mode", "")
                        if experiment_id in POD_PINNING_CAPABLE_EXPERIMENTS else ""
                    ),
                    exact_pod_name=(
                        state.get("exact_pod_name", "")
                        if experiment_id in POD_PINNING_CAPABLE_EXPERIMENTS else ""
                    ),
                    volume_path=(
                        state.get("volume_path", volume_path)
                        if experiment_id in IO_CHAOS_EXPERIMENTS else "/data"
                    ),
                    recovery_retry_count=5,
                    recovery_retry_interval_seconds=50,
                )
                # Advisory-only checks — failures warn but don't abort. Defined
                # before run_checks() so the live CLI display can mark these
                # distinctly (⚠, non-blocking) instead of a hard ✘ failure.
                _WARN_ONLY = {
                    "Pod Events (last 5m)",
                    "Probe Failures Stopped (post)",
                    "Circuit Breaker / DestinationRule (Advisory)",
                    "cert-manager ACME Issuer Domain (Advisory)",
                    "cert-manager Certificate Expiry Window",
                    "Node Time Sync (NTP/Chrony)",
                    "DNS Pattern Blast Radius",
                    # OOMKilled post-stress is an experiment finding, not a tool failure.
                    # Memory stress is designed to push containers to their limits — an
                    # OOMKill is a valid outcome that should be recorded, not block the run.
                    "No OOMKilled (post)",

                    # Throughput Restored is a single curl-based speed sample against
                    # a typically tiny response body (a few hundred bytes to a few KB).
                    # For payloads that small, TCP slow-start and per-request connection
                    # overhead dominate the timing — speed_download can read well below
                    # any real bandwidth cap's threshold even when the cap is genuinely
                    # gone. "tc-tbf Rule Removed" (checked separately, immediately above
                    # this one) is the authoritative, ground-truth signal — it reads the
                    # pod's actual kernel qdisc state directly, not a derived proxy
                    # measurement. A low reading here alongside a passing "tc-tbf Rule
                    # Removed" is noise, not evidence the cap is still active.
                    "Throughput Restored (KB/s)",
                }
                if session:
                    results = session.run_checks(post_checks, phase="post-check", print_live=True,
                                                  advisory_labels=_WARN_ONLY)
                else:
                    tmp = ValidationSession(f"{experiment_id}-post")
                    tmp.start()
                    try:
                        results = tmp.run_checks(post_checks, phase="post-check", print_live=True,
                                                  advisory_labels=_WARN_ONLY)
                    finally:
                        tmp.stop()
                failures   = [lbl for lbl, r in results.items() if not r.get("passed") and lbl not in _WARN_ONLY]
                warn_fails = [lbl for lbl, r in results.items() if not r.get("passed") and lbl in _WARN_ONLY]
                state["_probe_recovered"] = _probe_recovery_status(results)
                if experiment_id in NETWORK_CHAOS_EXPERIMENTS:
                    state["_network_post_failures"] = failures
                if experiment_id in IO_CHAOS_EXPERIMENTS:
                    # Pull the real post-rollback round-trip ms straight out of
                    # the post-check's own detail text so the final impact
                    # summary can show a genuine "after" number instead of a
                    # static message.
                    import re as _re
                    _detail = str(results.get("Residual I/O Fault Check", {}).get("detail", ""))
                    _m = _re.search(r"round-trip = (\d+)ms", _detail)
                    if _m:
                        state["_io_post_ms"] = int(_m.group(1))
                if warn_fails:
                    _ui_warning(f"Post-check advisory (non-blocking): {', '.join(warn_fails)}")
                if failures:
                    if experiment_id in NETWORK_CHAOS_EXPERIMENTS:
                        # These two printers are network-chaos-specific: the
                        # "Network chaos outcome" heading and the impact table
                        # only know how to build rows for the 6 network
                        # experiment IDs (retransmits, RTT, endpoints, etc.).
                        # Calling them for Pod/Stress/Time/HTTP/DNS/IO chaos
                        # produced a misleading "Network chaos outcome" label
                        # with a completely empty before/during/after table,
                        # since no matching row-building branch exists for
                        # those experiment types.
                        _print_network_outcome(
                            state.get("_fault_confirmed", False),
                            state.get("_net_pre_fault", {}),
                            state.get("_net_peak", {}),
                            failures,
                        )
                        _print_net_impact_summary(
                            experiment_id,
                            state.get("_net_pre_fault", {}),
                            state.get("_net_peak", {}),
                            int(state.get("duration", duration)),
                            state.get("_fault_confirmed", False),
                            state.get("_targeted_pods", []),
                            state.get("_probe_recovered"),
                        )
                    raise RuntimeError(f"Post-experiment checks failed: {failures}")

            elif experiment_id in KUBE_SYSTEM_EXPERIMENTS:
                # Cluster-plane (CoreDNS/kube-proxy) post-checks — bypass
                # build_post_experiment_checks's generic pod-recovery checks,
                # which assume an app-namespace selector (namespace/deployment
                # are intentionally blank here). Uses the dedicated kube-system
                # aware checks instead.
                from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
                    build_cluster_plane_chaos_post_checks,
                )
                post_checks = build_cluster_plane_chaos_post_checks(aks_context, experiment_id)
                if session:
                    results = session.run_checks(post_checks, phase="post-check", print_live=True)
                else:
                    tmp = ValidationSession(f"{experiment_id}-post")
                    tmp.start()
                    try:
                        results = tmp.run_checks(post_checks, phase="post-check", print_live=True)
                    finally:
                        tmp.stop()
                failures = [lbl for lbl, r in results.items() if not r.get("passed")]
                if failures:
                    raise RuntimeError(f"Post-experiment checks failed: {failures}")

            else:
                run_parallel_steady_state(
                    aks_context,
                    namespace  = namespace  if experiment_id not in KUBE_SYSTEM_EXPERIMENTS else "",
                    deployment = deployment if experiment_id not in KUBE_SYSTEM_EXPERIMENTS else "",
                    label_key  = label_key,
                    label_val  = label_val,
                    phase      = "post-check",
                    session    = session,
                )
            if session:
                session.log_event("post-check", "All post-experiment checks passed")
        except RuntimeError as exc:
            if session:
                session.log_event("post-check", f"FAILED: {exc}")
            raise

    # ── Network chaos: print before/during/after impact summary ──────────────
    if experiment_id in NETWORK_CHAOS_EXPERIMENTS:
        _pre  = state.get("_net_pre_fault", {})
        _peak = state.get("_net_peak", {})
        _confirmed = state.get("_fault_confirmed", False)
        _print_network_outcome(
            _confirmed, _pre, _peak, state.get("_network_post_failures", [])
        )
        _print_net_impact_summary(
            experiment_id, _pre, _peak,
            int(state.get("duration", duration)),
            _confirmed,
            state.get("_targeted_pods", []),
            state.get("_probe_recovered"),
        )

    # ── IOChaos: print before/during(worst)/after impact summary ─────────────
    if experiment_id in IO_CHAOS_EXPERIMENTS:
        _print_io_impact_summary(
            experiment_id,
            state.get("_io_pre_fault", {}),
            state.get("_io_peak", {}),
            int(state.get("duration", duration)),
            state.get("_fault_confirmed", False),
            state.get("_targeted_pods", []),
            state.get("_io_post_ms"),
        )

    console.print(
        f"\n  [dim]Audit trail:[/dim] Azure Portal → Chaos Studio → [bold]{experiment_id}[/bold]"
    )
    # notify_experiment_end(experiment_id, namespace, cluster)

    if session:
        console.print(f"  [dim]Validation logs:[/dim] {session.log_dir}")
        session.stop()

    if os.path.exists(state_path):
        os.unlink(state_path)




_EXPORTED_FUNCTIONS = (
    "cleanup_experiment",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update({name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS})
globals().update(_LOCAL_EXPORTS)
__all__ = list(_EXPORTED_FUNCTIONS)
