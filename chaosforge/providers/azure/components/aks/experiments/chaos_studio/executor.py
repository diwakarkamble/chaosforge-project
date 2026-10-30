"""
Azure AKS Chaos Actions
Called by ChaosToolkit via the chaos JSON experiment files.
Loads YAML templates from experiments/aks/chaos-yamls/,
builds jsonSpec, and executes via Azure Chaos Studio.
"""

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from chaosforge.common.azure_cli import azure_cli_command
from chaosforge.interfaces.cli.interactive.phase_ui import PhaseUI
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.status import warning as _ui_warning
from chaosforge.lifecycle.checks.kubernetes_chaos import (
    build_post_validation_checks as build_post_experiment_checks,
)
from chaosforge.lifecycle.checks.kubernetes_chaos import (
    observe_fault as verify_fault_active,
)
from chaosforge.lifecycle.checks.kubernetes_chaos import (
    run_pre_validation as run_parallel_steady_state,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.safety import (
    check_protected_namespace,
    validate_and_resolve_selector,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.validation_logger import (
    ValidationSession,
)

_COMPATIBILITY_GLOBALS = (
    PhaseUI,
    console,
    _ui_warning,
    build_post_experiment_checks,
    verify_fault_active,
    run_parallel_steady_state,
    check_protected_namespace,
    validate_and_resolve_selector,
    ValidationSession,
    datetime,
    time,
    timezone,
)

# from reporting.dd_notifier import notify_experiment_end, notify_experiment_start

# ─── PATHS ───────────────────────────────────────────────────────────────────
SPEC_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "specs"
)
TIME_OFFSET_PATTERN = re.compile(r"^[+-]?[1-9][0-9]*(?:s|m|h)$")


def _normalize_time_offset(experiment_id, value):
    if not TIME_OFFSET_PATTERN.fullmatch(value):
        return None
    if value[0] in "+-":
        if experiment_id == "aks-clock-skew-forward" and value[0] != "+":
            return None
        if experiment_id == "aks-clock-skew-backward" and value[0] != "-":
            return None
        return value
    sign = "-" if experiment_id == "aks-clock-skew-backward" else "+"
    return f"{sign}{value}"

# ─── CHAOS NAMESPACE ─────────────────────────────────────────────────────────
# Namespace used for Chaos Mesh installation and stress-ng pods.
# Azure Chaos Studio requires "chaos-testing" — do NOT change for Chaos Mesh experiments.
# Only stress-ng pod experiments (cpu-stress, memory-pressure) can use a different namespace.
CHAOS_NAMESPACE = "chaos-testing"

# ─── kubectl → Kubernetes Python client dispatch ────────────────────────────
# A number of helper functions below (_node_pod_count, _check_pdbs, etc.) call
# kubectl without an explicit --context, relying on whatever context
# `kubectl config use-context` last set as the ambient default (see the call
# at module scope below). _ACTIVE_KCTX mirrors that ambient context so those
# same call sites can be routed through the Python-client dispatcher too —
# it is updated every time `_kubectl("config", "use-context", ctx, ...)` runs.
_ACTIVE_KCTX = {"context": None}


def _kubectl(*args, context=None, timeout=None):
    """
    Run a kubectl-equivalent command. Tries the shared Python-client
    dispatcher (services.k8s_client.dispatch_kubectl) first — the same
    interception point used by actions/aks_safety_checks.py and
    actions/aks_extended_checks.py — and falls back to the real kubectl
    subprocess for anything the dispatcher doesn't recognise or that errors.

    If no explicit context is given, falls back to the last context set via
    `kubectl config use-context` (see _ACTIVE_KCTX above), matching the
    ambient-context behaviour these call sites already relied on.
    """
    from chaosforge.providers.azure.components.aks.kubernetes import (
        run_kubernetes_command,
    )

    return run_kubernetes_command(
        args,
        context or _ACTIVE_KCTX["context"],
        timeout=timeout,
    )


def _kubectl_json(args):
    """Run a kubectl command (argv list, first element "kubectl") and return
    parsed JSON output, or None on failure. `args` may omit -o json — it is
    appended automatically, same as the previous (buggy/undefined) helper
    this replaces was documented to do."""
    r = _kubectl(*args[1:], "-o", "json")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except (ValueError, TypeError):
        return None

# ─── EXPERIMENT → JSON SPEC FILE MAP ─────────────────────────────────────────
EXPERIMENT_SPECS = {
    "aks-pod-kill":                "01-pod-kill.json",
    "aks-pod-failure":             "02-pod-failure.json",
    "aks-container-kill":          "03-container-kill.json",
    "aks-crashloop":               "04-crashloop.json",
    "aks-node-drain":              "05-node-drain.json",
    "aks-node-taint":              "06-node-taint.json",
    "aks-node-notready":           "07-node-notready.json",
    "aks-node-cpu-stress":         "08-node-cpu-stress.json",
    "aks-node-memory-pressure":    "09-node-memory-pressure.json",
    "aks-node-zone-failure":       "10-zone-node-failure.json",
    "aks-network-delay":           "11-network-delay.json",
    "aks-packet-loss":             "12-packet-loss.json",
    "aks-bandwidth-limit":         "13-bandwidth-limit.json",
    "aks-packet-corruption":       "14-packet-corruption.json",
    "aks-packet-duplication":      "15-packet-duplication.json",
    "aks-network-partition":       "16-network-partition.json",
    "aks-cpu-stress":              "17-cpu-stress.json",
    "aks-memory-stress":           "18-memory-stress.json",
    "aks-dns-failure":             "19-dns-chaos.json",
    "aks-io-latency":              "20-io-latency.json",
    "aks-io-errors":               "21-io-errors.json",
    "aks-clock-skew-forward":      "22-clock-skew-forward.json",
    "aks-clock-skew-backward":     "23-clock-skew-backward.json",
    "aks-http-delay":              "24-http-delay.json",
    "aks-http-abort":              "25-http-abort.json",
    "aks-coredns-kill":            "26-coredns-kill.json",
    "aks-coredns-cpu":             "27-coredns-cpu-stress.json",
    "aks-kube-proxy-kill":         "28-kube-proxy-kill.json",
}

# Node-level experiments that use kubectl directly (no Chaos Mesh / Studio)
NODE_KUBECTL_EXPERIMENTS = {
    "aks-node-drain", "aks-node-taint",
    "aks-node-cpu-stress", "aks-node-memory-pressure",
    "aks-crashloop",
}

# Node-level experiments that target Azure VMSS via Studio (shutdown-based)
NODE_VMSS_EXPERIMENTS = {
    "aks-node-notready", "aks-node-zone-failure",
}

# ─── SAFETY GUARDRAILS ───────────────────────────────────────────────────────
# Experiments that directly terminate/restart pods — need replica-floor + PDB
# guardrails, since killing the last healthy replica causes an outage.
POD_DISRUPTIVE_EXPERIMENTS = {
    "aks-pod-kill", "aks-pod-failure", "aks-container-kill", "aks-crashloop",
}

# Deliberately target kube-system (CoreDNS / kube-proxy) — exempt from the
# protected-namespace guard, which otherwise blocks kube-system by default.
KUBE_SYSTEM_EXPERIMENTS = {
    "aks-coredns-kill", "aks-coredns-cpu", "aks-kube-proxy-kill",
}

# Pod-level chaos experiments — get experiment-specific pre/during/post checks
POD_CHAOS_EXPERIMENTS    = frozenset({"aks-pod-kill", "aks-pod-failure",
                                       "aks-container-kill", "aks-crashloop"})
STRESS_CHAOS_EXPERIMENTS = frozenset({"aks-cpu-stress", "aks-memory-stress"})

# Network chaos experiments — get network-specific pre/during/post checks
NETWORK_CHAOS_EXPERIMENTS = frozenset({"aks-network-delay", "aks-packet-loss", "aks-bandwidth-limit",
                                        "aks-packet-corruption", "aks-packet-duplication",
                                        "aks-network-partition"})

NODE_STRESS_CANARY_EXCLUDED_NAMESPACES = frozenset({
    "kube-system", "kube-public", "kube-node-lease",
    "chaos-testing", "chaos-mesh", "chaos-engine",
    "cert-manager", "azure-arc", "gatekeeper-system",
    "monitoring", "prometheus", "istio-system", "linkerd",
})

# Extended experiments — time/http/dns get their own pre/post checks via aks_extended_checks.py
TIME_CHAOS_EXPERIMENTS = frozenset({"aks-clock-skew-forward", "aks-clock-skew-backward"})
HTTP_CHAOS_EXPERIMENTS = frozenset({"aks-http-delay", "aks-http-abort"})
DNS_CHAOS_EXPERIMENTS  = frozenset({"aks-dns-failure"})

# IO chaos experiments (Disk I/O Latency 100ms, Disk I/O Errors EIO) — get
# their own dedicated pre/during/post checks via aks_extended_checks.py.
# Kept as its own standalone set (not merged into NETWORK_CHAOS_EXPERIMENTS or
# any other group) so adding it cannot change behavior for any other
# experiment type.
IO_CHAOS_EXPERIMENTS = frozenset({"aks-io-latency", "aks-io-errors"})

# Every experiment kind whose Chaos Mesh CRD has a standard top-level
# `selector` block (PodSelectorSpec) supporting fieldSelectors — i.e. every
# kind for which "By Pod" target mode can be pinned to the exact chosen pod
# rather than falling back to the deployment's label selector (which always
# also matches every sibling replica, since they share identical labels).
# aks-crashloop is included for consistency (it's also in
# POD_DISRUPTIVE_EXPERIMENTS) but never actually reaches _build_spec() — it
# has its own per-pod fieldSelectors-based manifest builder already.
POD_PINNING_CAPABLE_EXPERIMENTS = (
    POD_DISRUPTIVE_EXPERIMENTS | STRESS_CHAOS_EXPERIMENTS | NETWORK_CHAOS_EXPERIMENTS
    | TIME_CHAOS_EXPERIMENTS | HTTP_CHAOS_EXPERIMENTS | DNS_CHAOS_EXPERIMENTS | IO_CHAOS_EXPERIMENTS
)

# ─── VMSS STUDIO CAPABILITY URNs ─────────────────────────────────────────────
VMSS_CAPABILITY = {
    "VmssShutdown": "urn:csci:microsoft:virtualMachineScaleSet:shutdown/1.0",
}

# ─── STUDIO CAPABILITY URNs ──────────────────────────────────────────────────
STUDIO_CAPABILITY = {
    "PodChaos":     "urn:csci:microsoft:azureKubernetesServiceChaosMesh:podChaos/2.2",
    "NetworkChaos": "urn:csci:microsoft:azureKubernetesServiceChaosMesh:networkChaos/2.2",
    "StressChaos":  "urn:csci:microsoft:azureKubernetesServiceChaosMesh:stressChaos/2.2",
    "IOChaos":      "urn:csci:microsoft:azureKubernetesServiceChaosMesh:IOChaos/2.2",
    "TimeChaos":    "urn:csci:microsoft:azureKubernetesServiceChaosMesh:timeChaos/2.2",
    "HTTPChaos":    "urn:csci:microsoft:azureKubernetesServiceChaosMesh:httpChaos/2.2",
    "DNSChaos":     "urn:csci:microsoft:azureKubernetesServiceChaosMesh:dnsChaos/2.2",
}

def _http_chaos_teardown(experiment_id, aks_context, namespace, deployment,
                         orig_ape, session=None):
    """
    Reverse HTTPChaos setup: restore allowPrivilegeEscalation on each container
    that was patched, rolling restart, then remove namespace label.
    Safe to call multiple times — idempotent.
    """
    if not (namespace and deployment):
        return

    r_dep = _kubectl("get", "deployment", deployment, "-n", namespace,
                     "-o", "json", context=aks_context)
    if r_dep.returncode == 0:
        try:
            dep_json   = json.loads(r_dep.stdout)
            containers = dep_json.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            restore_ops = []
            for i, c in enumerate(containers):
                orig_val = orig_ape.get(c["name"])
                if orig_val is False or orig_val is None:
                    sc = c.get("securityContext") or {}
                    op = "replace" if "allowPrivilegeEscalation" in sc else "add"
                    restore_ops.append({
                        "op": op,
                        "path": f"/spec/template/spec/containers/{i}/securityContext/allowPrivilegeEscalation",
                        "value": False,
                    })
            if restore_ops:
                _kubectl("patch", "deployment", deployment, "-n", namespace,
                        "--type=json", f"-p={json.dumps(restore_ops)}", context=aks_context)
                _kubectl("rollout", "restart", f"deployment/{deployment}", "-n", namespace,
                        context=aks_context)
                _kubectl("rollout", "status", f"deployment/{deployment}", "-n", namespace,
                        "--timeout=120s", context=aks_context, timeout=130)
                if session:
                    session.log_event("rollback",
                        f"securityContext restored and pods hardened: {deployment}")
        except (ValueError, KeyError):
            pass

    _kubectl("label", "namespace", namespace, "chaos-experiments-", context=aks_context)
    if session:
        session.log_event("rollback",
            f"Namespace label removed: {namespace} chaos-experiments-")

    # Delete sentinel — teardown complete, next run starts clean
    _sentinel_path = _http_chaos_sentinel(experiment_id, namespace, deployment)
    try:
        os.unlink(_sentinel_path)
    except OSError:
        pass


def _state_file(experiment_id):
    """Return a per-experiment-run state file path so concurrent runs never share state.
    The epoch suffix matches the one used in _safe_name, keeping paths unique per run."""
    safe = re.sub(r'[^a-z0-9-]', '', experiment_id.lower())
    return os.path.join(tempfile.gettempdir(), f"aks_chaos_state_{safe}_{os.getpid()}.json")


def _http_chaos_sentinel(experiment_id, namespace, deployment):
    """PID-less sentinel file for HTTP chaos leftover detection.
    Written after setup completes, deleted after teardown completes.
    Unlike the per-run state file, this persists across process restarts so
    the next run can detect and clean up a previously aborted setup."""
    safe_exp = re.sub(r'[^a-z0-9-]', '', experiment_id.lower())
    safe_ns  = re.sub(r'[^a-z0-9-]', '', namespace.lower())
    safe_dep = re.sub(r'[^a-z0-9-]', '', deployment.lower())
    return os.path.join(
        tempfile.gettempdir(),
        f"aks_http_chaos_setup_{safe_exp}_{safe_ns}_{safe_dep}.json"
    )


def _is_true(value):
    """chaostoolkit passes --var values as strings — normalize truthy ones."""
    return str(value).strip().lower() in ("true", "1", "yes", "y")


# ─── CHAOS EXPERIMENTS RG CACHE ──────────────────────────────────────────────
# Per-process cache: subscription_id → dedicated chaos RG name.
# Avoids repeated az CLI calls when a campaign runs multiple experiments against
# the same subscription.
_CHAOS_RG_CACHE: dict[str, str] = {}


def _get_or_create_chaos_rg(sub: str, location: str) -> str:
    """
    Return (creating if absent) the dedicated ChaosForge experiments RG for
    this subscription.  Named chaosforge-experiments-<sub[:8]> — short, unique
    per subscription, stable across runs.

    Chaos Studio experiment ARM resources are placed here instead of the cluster
    RG so cluster infra and experiment artefacts stay cleanly separated.

    Note: the cluster RG is still used for:
      - chaos-studio-identity (managed identity)
      - AKS target/capability registration
    """
    if sub in _CHAOS_RG_CACHE:
        return _CHAOS_RG_CACHE[sub]

    rg_name = f"chaosforge-experiments-{sub[:8]}"

    r = subprocess.run(
        azure_cli_command("group", "show", "--name", rg_name, "--subscription", sub,
         "--query", "name", "-o", "tsv"),
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        subprocess.run(
            azure_cli_command("group", "create", "--name", rg_name,
             "--location", location or "eastus",
             "--subscription", sub,
             "--tags", "managed-by=chaosforge", "purpose=chaos-experiments"),
            capture_output=True, check=True,
        )

    _CHAOS_RG_CACHE[sub] = rg_name
    return rg_name


# ─── STEP 1: SETUP ───────────────────────────────────────────────────────────

from . import execution_support as _execution_support
from . import lifecycle_cleanup as _lifecycle_cleanup
from . import lifecycle_operations as _lifecycle_operations
from . import node_operations as _node_operations
from . import node_stress_execution as _node_stress_execution
from . import node_stress_operations as _node_stress_operations
from . import studio_execution as _studio_execution
from . import studio_runtime as _studio_runtime
from . import vmss_operations as _vmss_operations
from . import zone_operations as _zone_operations

_reopen_session = _execution_support._LOCAL_EXPORTS["_reopen_session"]
_delete_studio_experiment = _execution_support._LOCAL_EXPORTS["_delete_studio_experiment"]
_get_node_resource_group = _execution_support._LOCAL_EXPORTS["_get_node_resource_group"]
_load_state = _execution_support._LOCAL_EXPORTS["_load_state"]
_save_state_field = _execution_support._LOCAL_EXPORTS["_save_state_field"]
_print_dry_run_preview = _execution_support._LOCAL_EXPORTS["_print_dry_run_preview"]
_extract_net_metrics = _execution_support._LOCAL_EXPORTS["_extract_net_metrics"]
_capture_missing_net_baseline = _execution_support._LOCAL_EXPORTS["_capture_missing_net_baseline"]
_probe_recovery_status = _execution_support._LOCAL_EXPORTS["_probe_recovery_status"]
_print_network_outcome = _execution_support._LOCAL_EXPORTS["_print_network_outcome"]
_print_net_impact_summary = _execution_support._LOCAL_EXPORTS["_print_net_impact_summary"]
_print_io_impact_summary = _execution_support._LOCAL_EXPORTS["_print_io_impact_summary"]
_destructive_warning = _execution_support._LOCAL_EXPORTS["_destructive_warning"]
_prompt_precheck_override = _execution_support._LOCAL_EXPORTS["_prompt_precheck_override"]
_confirm_destructive_action = _execution_support._LOCAL_EXPORTS["_confirm_destructive_action"]
_resolve_azure_details = _execution_support._LOCAL_EXPORTS["_resolve_azure_details"]

_node_pod_count = _node_operations._LOCAL_EXPORTS["_node_pod_count"]
_node_is_ready = _node_operations._LOCAL_EXPORTS["_node_is_ready"]
_node_is_schedulable = _node_operations._LOCAL_EXPORTS["_node_is_schedulable"]
_check_pdbs = _node_operations._LOCAL_EXPORTS["_check_pdbs"]
_pending_pods_exist = _node_operations._LOCAL_EXPORTS["_pending_pods_exist"]
_get_node_names = _node_operations._LOCAL_EXPORTS["_get_node_names"]
_get_unhealthy_pods = _node_operations._LOCAL_EXPORTS["_get_unhealthy_pods"]
_get_deployment_readiness = _node_operations._LOCAL_EXPORTS["_get_deployment_readiness"]
_get_node_conditions = _node_operations._LOCAL_EXPORTS["_get_node_conditions"]
_prechecks_node_drain = _node_operations._LOCAL_EXPORTS["_prechecks_node_drain"]
_run_node_drain = _node_operations._LOCAL_EXPORTS["_run_node_drain"]
_postchecks_node_drain = _node_operations._LOCAL_EXPORTS["_postchecks_node_drain"]
_node_has_chaos_taint = _node_operations._LOCAL_EXPORTS["_node_has_chaos_taint"]
_node_taint_confirmed = _node_operations._LOCAL_EXPORTS["_node_taint_confirmed"]
_prechecks_node_taint = _node_operations._LOCAL_EXPORTS["_prechecks_node_taint"]
_run_node_taint = _node_operations._LOCAL_EXPORTS["_run_node_taint"]
_postchecks_node_taint = _node_operations._LOCAL_EXPORTS["_postchecks_node_taint"]
_stress_pod_name = _node_operations._LOCAL_EXPORTS["_stress_pod_name"]
_get_node_top = _node_operations._LOCAL_EXPORTS["_get_node_top"]
_get_pod_restart_counts = _node_operations._LOCAL_EXPORTS["_get_pod_restart_counts"]
_get_node_io_wait = _node_operations._LOCAL_EXPORTS["_get_node_io_wait"]
_get_node_stress_workload_status = _node_operations._LOCAL_EXPORTS["_get_node_stress_workload_status"]
_resolve_node_stress_canary = _node_operations._LOCAL_EXPORTS["_resolve_node_stress_canary"]
_is_missing_exec_command = _node_operations._LOCAL_EXPORTS["_is_missing_exec_command"]
_probe_node_stress_canary = _node_operations._LOCAL_EXPORTS["_probe_node_stress_canary"]
_record_node_stress_impact = _node_operations._LOCAL_EXPORTS["_record_node_stress_impact"]
_prechecks_node_stress = _node_operations._LOCAL_EXPORTS["_prechecks_node_stress"]
_postchecks_node_stress = _node_operations._LOCAL_EXPORTS["_postchecks_node_stress"]
_deploy_stress_pod = _node_operations._LOCAL_EXPORTS["_deploy_stress_pod"]
_run_node_cpu_stress = _node_operations._LOCAL_EXPORTS["_run_node_cpu_stress"]
_run_node_memory_pressure = _node_operations._LOCAL_EXPORTS["_run_node_memory_pressure"]
_cleanup_stress_pod = _node_operations._LOCAL_EXPORTS["_cleanup_stress_pod"]
_crashloop_podchaos_name = _node_operations._LOCAL_EXPORTS["_crashloop_podchaos_name"]
_resolve_target_pod = _node_operations._LOCAL_EXPORTS["_resolve_target_pod"]
_run_crashloop = _node_operations._LOCAL_EXPORTS["_run_crashloop"]
_cleanup_crashloop = _node_operations._LOCAL_EXPORTS["_cleanup_crashloop"]

_build_spec = _studio_execution._LOCAL_EXPORTS["_build_spec"]
_az_rest_put = _studio_execution._LOCAL_EXPORTS["_az_rest_put"]
_setup_studio_target = _studio_execution._LOCAL_EXPORTS["_setup_studio_target"]
_ensure_chaos_mesh_in_chaos_testing = _studio_execution._LOCAL_EXPORTS["_ensure_chaos_mesh_in_chaos_testing"]
_get_chaos_identity_id = _studio_execution._LOCAL_EXPORTS["_get_chaos_identity_id"]
_seconds_to_iso8601 = _studio_execution._LOCAL_EXPORTS["_seconds_to_iso8601"]
_build_studio_experiment_object = _studio_execution._LOCAL_EXPORTS["_build_studio_experiment_object"]
_precreate_studio_experiment = _studio_execution._LOCAL_EXPORTS["_precreate_studio_experiment"]
_target_selection_preview = _studio_execution._LOCAL_EXPORTS["_target_selection_preview"]
_extract_chaos_target_pods = _studio_execution._LOCAL_EXPORTS["_extract_chaos_target_pods"]
_read_chaos_target_pods = _studio_execution._LOCAL_EXPORTS["_read_chaos_target_pods"]
_read_restart_total = _studio_execution._LOCAL_EXPORTS["_read_restart_total"]
_read_io_baseline_ms = _studio_execution._LOCAL_EXPORTS["_read_io_baseline_ms"]
_run_studio_experiment = _studio_execution._LOCAL_EXPORTS["_run_studio_experiment"]
_get_experiment_failure_detail = _studio_execution._LOCAL_EXPORTS["_get_experiment_failure_detail"]

_get_vm_power_state = _vmss_operations._LOCAL_EXPORTS["_get_vm_power_state"]
_prechecks_node_notready = _vmss_operations._LOCAL_EXPORTS["_prechecks_node_notready"]
_postchecks_node_notready = _vmss_operations._LOCAL_EXPORTS["_postchecks_node_notready"]
_run_vmss_experiment = _vmss_operations._LOCAL_EXPORTS["_run_vmss_experiment"]
_prechecks_zone_failure = _vmss_operations._LOCAL_EXPORTS["_prechecks_zone_failure"]
_postchecks_zone_failure = _vmss_operations._LOCAL_EXPORTS["_postchecks_zone_failure"]
_run_zone_failure = _vmss_operations._LOCAL_EXPORTS["_run_zone_failure"]
_setup_vmss_target = _vmss_operations._LOCAL_EXPORTS["_setup_vmss_target"]
_apply_direct = _zone_operations._LOCAL_EXPORTS["_apply_direct"]
_live_wait = _zone_operations._LOCAL_EXPORTS["_live_wait"]
_safe_name = _zone_operations._LOCAL_EXPORTS["_safe_name"]

_run_studio_experiment = _studio_runtime._LOCAL_EXPORTS["_run_studio_experiment"]
_get_experiment_failure_detail = _studio_runtime._LOCAL_EXPORTS["_get_experiment_failure_detail"]

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
_deploy_stress_pod = _node_stress_execution._LOCAL_EXPORTS["_deploy_stress_pod"]
_run_node_cpu_stress = _node_stress_execution._LOCAL_EXPORTS["_run_node_cpu_stress"]
_run_node_memory_pressure = _node_stress_execution._LOCAL_EXPORTS["_run_node_memory_pressure"]
_cleanup_stress_pod = _node_stress_execution._LOCAL_EXPORTS["_cleanup_stress_pod"]
_crashloop_podchaos_name = _node_stress_execution._LOCAL_EXPORTS["_crashloop_podchaos_name"]
_resolve_target_pod = _node_stress_execution._LOCAL_EXPORTS["_resolve_target_pod"]
_run_crashloop = _node_stress_execution._LOCAL_EXPORTS["_run_crashloop"]
_cleanup_crashloop = _node_stress_execution._LOCAL_EXPORTS["_cleanup_crashloop"]
_run_zone_failure = _zone_operations._LOCAL_EXPORTS["_run_zone_failure"]

cleanup_experiment = _lifecycle_cleanup._LOCAL_EXPORTS["cleanup_experiment"]

setup_studio = _lifecycle_operations._LOCAL_EXPORTS["setup_studio"]
run_experiment = _lifecycle_operations._LOCAL_EXPORTS["run_experiment"]
cleanup_experiment = _lifecycle_operations._LOCAL_EXPORTS["cleanup_experiment"]
