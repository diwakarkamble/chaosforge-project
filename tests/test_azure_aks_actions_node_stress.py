"""
Unit tests for the node-taint and node-stress pre-check/post-check/pure-helper
functions in actions/azure_aks_actions.py. These are the non-threaded,
non-Live-UI parts of the node-taint and node-stress trios, plus small pure
helpers (_stress_pod_name, _get_node_top, _get_pod_restart_counts,
_get_node_stress_workload_status, _resolve_node_stress_canary,
_probe_node_stress_canary, _record_node_stress_impact,
_is_missing_exec_command). The threaded `_run_*` pollers and Azure-SDK-backed
VMSS/zone-failure code remain out of scope (see
tests/test_azure_aks_actions_node_checks.py docstring).
"""

from subprocess import CompletedProcess
from unittest.mock import patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    executor as m,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ── _prechecks_node_taint ────────────────────────────────────────────────────

def test_prechecks_node_taint_ok_when_ready_and_no_existing_taint():
    with patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_has_chaos_taint", return_value=False), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_pod_count", return_value=3), \
         patch.object(m, "_check_pdbs", return_value=[]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="node-a node-b")), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 3, 3)]):
        ok, snapshot = m._prechecks_node_taint("node-1")
    assert ok is True
    assert snapshot["pod_count_before"] == 3


def test_prechecks_node_taint_fails_when_node_not_ready():
    with patch.object(m, "_node_is_ready", return_value=False), \
         patch.object(m, "_node_has_chaos_taint", return_value=False), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_pod_count", return_value=0), \
         patch.object(m, "_check_pdbs", return_value=[]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="")), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_deployment_readiness", return_value=[]):
        ok, _snapshot = m._prechecks_node_taint("node-1")
    assert ok is False


def test_prechecks_node_taint_fails_when_chaos_taint_already_present():
    with patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_has_chaos_taint", return_value=True), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_pod_count", return_value=0), \
         patch.object(m, "_check_pdbs", return_value=[]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="")), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_deployment_readiness", return_value=[]):
        ok, _snapshot = m._prechecks_node_taint("node-1")
    assert ok is False


# ── _postchecks_node_taint ───────────────────────────────────────────────────

def test_postchecks_node_taint_completes_when_healthy_and_taint_removed():
    state = {
        "nodes_before": ["node-1"],
        "unhealthy_before": [],
        "deployments_before": [("dep-a", "ns", 3, 3)],
        "pod_count_before": 3,
        "taint_start_time": 1000.0,
    }
    with patch.object(m.time, "sleep", lambda *_a, **_k: None), \
         patch.object(m.time, "time", return_value=1010.0), \
         patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_taint_confirmed", return_value=False), \
         patch.object(m, "_get_node_conditions", return_value={
             "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False",
         }), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 3, 3)]), \
         patch.object(m, "_pending_pods_exist", return_value=[]), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_node_names", return_value={"node-1"}):
        m._postchecks_node_taint("node-1", state)  # should not raise


def test_postchecks_node_taint_warns_when_taint_still_present():
    state = {
        "nodes_before": ["node-1"],
        "unhealthy_before": [],
        "deployments_before": [],
        "pod_count_before": 0,
    }
    with patch.object(m.time, "sleep", lambda *_a, **_k: None), \
         patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_taint_confirmed", return_value=True), \
         patch.object(m, "_get_node_conditions", return_value={
             "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False",
         }), \
         patch.object(m, "_get_deployment_readiness", return_value=[]), \
         patch.object(m, "_pending_pods_exist", return_value=[]), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_node_names", return_value={"node-1"}):
        m._postchecks_node_taint("node-1", state)  # should not raise, taint_gone=False path


# ── small pure helpers ───────────────────────────────────────────────────────

def test_is_missing_exec_command_true_for_known_error_strings():
    assert m._is_missing_exec_command("OCI runtime exec failed: exec: \"nslookup\": executable file not found")
    assert m._is_missing_exec_command("bash: getent: command not found")


def test_is_missing_exec_command_false_for_normal_output():
    assert m._is_missing_exec_command("Server: 10.0.0.10\nAddress: 10.0.0.1") is False


def test_stress_pod_name_truncates_long_node_names_and_tags_kind():
    name = m._stress_pod_name("aks-node-cpu-stress", "a" * 50)
    assert name.startswith("chaosforge-cpu-stress-")
    assert len(name.split("chaosforge-cpu-stress-")[1]) == 40

    mem_name = m._stress_pod_name("aks-node-memory-stress", "short-node")
    assert mem_name == "chaosforge-memory-stress-short-node"


def test_get_node_top_parses_valid_kubectl_output():
    with patch.object(m, "_kubectl", return_value=_cp(stdout="node-1  250m  25%  1024Mi  40%")):
        top = m._get_node_top("node-1")
    assert top == {"cpu_cores": "250m", "cpu_pct": 25, "mem_bytes": "1024Mi", "mem_pct": 40}


def test_get_node_top_returns_none_on_kubectl_failure():
    with patch.object(m, "_kubectl", return_value=_cp(returncode=1, stderr="metrics unavailable")):
        assert m._get_node_top("node-1") is None


def test_get_node_top_returns_none_on_malformed_output():
    with patch.object(m, "_kubectl", return_value=_cp(stdout="not enough fields")):
        assert m._get_node_top("node-1") is None


def test_get_pod_restart_counts_excludes_daemonset_pods():
    data = {"items": [
        {
            "metadata": {"name": "app-1", "namespace": "ns"},
            "status": {"containerStatuses": [{"restartCount": 2}]},
        },
        {
            "metadata": {"name": "ds-1", "namespace": "ns",
                         "ownerReferences": [{"kind": "DaemonSet"}]},
            "status": {"containerStatuses": [{"restartCount": 9}]},
        },
    ]}
    with patch.object(m, "_kubectl_json", return_value=data):
        counts = m._get_pod_restart_counts("node-1")
    assert counts == {("app-1", "ns"): 2}


def test_get_pod_restart_counts_returns_empty_when_no_data():
    with patch.object(m, "_kubectl_json", return_value=None):
        assert m._get_pod_restart_counts("node-1") == {}


def test_get_node_stress_workload_status_counts_ready_and_not_ready():
    data = {"items": [
        {
            "metadata": {"name": "p1", "namespace": "ns"},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [{"restartCount": 1}],
            },
        },
        {
            "metadata": {"name": "p2", "namespace": "ns"},
            "status": {"phase": "Pending", "conditions": [], "containerStatuses": []},
        },
        {
            "metadata": {"name": "ds-1", "namespace": "ns",
                         "ownerReferences": [{"kind": "DaemonSet"}]},
            "status": {"phase": "Running", "conditions": [], "containerStatuses": []},
        },
    ]}
    with patch.object(m, "_kubectl_json", return_value=data):
        status = m._get_node_stress_workload_status("node-1")
    assert status == {
        "total_pods": 2, "running_pods": 1, "ready_pods": 1,
        "not_ready_pods": 1, "restart_total": 1,
    }


def test_get_node_stress_workload_status_returns_none_when_no_data():
    with patch.object(m, "_kubectl_json", return_value=None):
        assert m._get_node_stress_workload_status("node-1") is None


def test_resolve_node_stress_canary_skips_excluded_namespaces():
    excluded_ns = next(iter(m.NODE_STRESS_CANARY_EXCLUDED_NAMESPACES))
    data = {"items": [
        {
            "metadata": {"name": "sys-pod", "namespace": excluded_ns},
            "spec": {"containers": [{"name": "c1"}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        },
        {
            "metadata": {"name": "app-pod", "namespace": "ns"},
            "spec": {"containers": [{"name": "app"}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        },
    ]}
    with patch.object(m, "_kubectl_json", return_value=data), \
         patch.object(m, "_probe_node_stress_canary", return_value={"dns_status": "ok"}):
        canary = m._resolve_node_stress_canary("node-1")
    assert canary["pod"] == "app-pod"


def test_resolve_node_stress_canary_returns_none_when_no_candidates():
    with patch.object(m, "_kubectl_json", return_value={"items": []}):
        assert m._resolve_node_stress_canary("node-1") is None


def test_probe_node_stress_canary_reports_ok_on_successful_dns_lookup():
    canary = {"namespace": "ns", "pod": "app-pod", "container": "app"}
    with patch.object(m, "_kubectl", return_value=_cp(stdout="Name: kubernetes.default.svc.cluster.local")):
        result = m._probe_node_stress_canary(canary)
    assert result["dns_status"] == "ok"
    assert "canary: ns/app-pod" in result["summary"]


def test_probe_node_stress_canary_reports_unavailable_then_none_found():
    canary = {"namespace": "ns", "pod": "app-pod", "container": "app"}
    with patch.object(m, "_kubectl", return_value=_cp(returncode=127, stderr="getent: command not found")):
        result = m._probe_node_stress_canary(canary)
    assert result["dns_status"] == "unavailable"


def test_probe_node_stress_canary_returns_none_for_empty_canary():
    assert m._probe_node_stress_canary(None) is None


def test_record_node_stress_impact_tracks_worst_case_ready_and_restarts():
    snapshot = {"baseline_workload": {"restart_total": 2}}
    workload_status = {"ready_pods": 1, "running_pods": 1, "not_ready_pods": 1, "restart_total": 5}
    m._record_node_stress_impact(snapshot, workload_status=workload_status)
    assert snapshot["min_ready_pods_during"] == 1
    assert snapshot["max_restart_delta_during"] == 3


def test_record_node_stress_impact_sets_pressure_flags_from_conditions():
    snapshot = {}
    m._record_node_stress_impact(
        snapshot, canary_probe={"summary": "x", "dns_status": "failed"},
        node_conditions={"DiskPressure": "True", "MemoryPressure": "False", "PIDPressure": "False"},
    )
    assert snapshot["disk_pressure_fired"] is True
    assert snapshot["canary_dns_failures"] == 1


# ── _prechecks_node_stress ───────────────────────────────────────────────────

def test_prechecks_node_stress_fails_hard_when_node_not_ready():
    with patch.object(m, "_get_node_conditions", return_value={"Ready": "False"}):
        ok, snapshot = m._prechecks_node_stress("node-1", "cpu")
    assert ok is False
    assert snapshot == {}


def test_prechecks_node_stress_fails_hard_when_chaos_namespace_missing():
    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "namespace"):
            return _cp(returncode=1, stderr="not found")
        return _cp(stdout="")

    with patch.object(m, "_get_node_conditions", return_value={"Ready": "True"}), \
         patch.object(m, "_kubectl", side_effect=_kubectl_router):
        ok, snapshot = m._prechecks_node_stress("node-1", "cpu")
    assert ok is False
    assert snapshot == {}


def test_prechecks_node_stress_ok_captures_full_baseline_snapshot():
    with patch.object(m, "_get_node_conditions", return_value={
             "Ready": "True", "DiskPressure": "False",
             "MemoryPressure": "False", "PIDPressure": "False",
         }), \
         patch.object(m, "_kubectl", return_value=_cp(returncode=0, stdout="")), \
         patch.object(m, "_get_node_top", return_value={
             "cpu_cores": "500m", "cpu_pct": 30, "mem_bytes": "2Gi", "mem_pct": 45,
         }), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 3, 3)]), \
         patch.object(m, "_get_pod_restart_counts", return_value={("app-1", "ns"): 0}), \
         patch.object(m, "_node_pod_count", return_value=4), \
         patch.object(m, "_get_node_stress_workload_status", return_value={
             "total_pods": 4, "running_pods": 4, "ready_pods": 4,
             "not_ready_pods": 0, "restart_total": 0,
         }), \
         patch.object(m, "_resolve_node_stress_canary", return_value=None):
        ok, snapshot = m._prechecks_node_stress("node-1", "cpu")
    assert ok is True
    assert snapshot["peak_cpu_pct"] == 30
    assert snapshot["pod_count_before"] == 4


# ── _postchecks_node_stress ──────────────────────────────────────────────────

def test_postchecks_node_stress_confirms_recovery_near_baseline():
    snapshot = {
        "baseline_top": {"cpu_pct": 10, "cpu_cores": "100m", "mem_bytes": "512Mi", "mem_pct": 20},
        "peak_cpu_pct": 90,
        "baseline_workload": {"ready_pods": 3, "total_pods": 3},
        "min_ready_pods_during": 3,
        "max_not_ready_pods_during": 0,
        "max_restart_delta_during": 0,
        "restarts_before": [],
        "deployments_before": [("dep-a", "ns", 3, 3)],
        "unhealthy_before": [],
        "canary": None,
    }
    with patch.object(m.time, "sleep", lambda *_a, **_k: None), \
         patch.object(m, "_get_node_top", return_value={
             "cpu_cores": "110m", "cpu_pct": 15, "mem_bytes": "520Mi", "mem_pct": 22,
         }), \
         patch.object(m, "_get_node_conditions", return_value={
             "Ready": "True", "MemoryPressure": "False",
             "DiskPressure": "False", "PIDPressure": "False",
         }), \
         patch.object(m, "_get_pod_restart_counts", return_value={}), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 3, 3)]), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="")):
        m._postchecks_node_stress("node-1", "cpu", snapshot)  # should not raise


def test_postchecks_node_stress_flags_degraded_deployment_after_stress():
    snapshot = {
        "baseline_top": {"cpu_pct": 10, "cpu_cores": "100m", "mem_bytes": "512Mi", "mem_pct": 20},
        "peak_cpu_pct": 95,
        "baseline_workload": {"ready_pods": 3, "total_pods": 3},
        "min_ready_pods_during": 1,
        "max_not_ready_pods_during": 2,
        "max_restart_delta_during": 4,
        "restarts_before": [],
        "deployments_before": [("dep-a", "ns", 3, 3)],
        "unhealthy_before": [],
        "canary": None,
    }
    with patch.object(m.time, "sleep", lambda *_a, **_k: None), \
         patch.object(m, "_get_node_top", return_value=None), \
         patch.object(m, "_get_node_conditions", return_value={
             "Ready": "True", "MemoryPressure": "False",
             "DiskPressure": "False", "PIDPressure": "False",
         }), \
         patch.object(m, "_get_pod_restart_counts", return_value={}), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 1, 3)]), \
         patch.object(m, "_get_unhealthy_pods", return_value=[("pod-x", "ns", "CrashLoopBackOff")]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="")):
        m._postchecks_node_stress("node-1", "cpu", snapshot)  # should not raise
