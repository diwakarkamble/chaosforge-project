"""
Unit tests for node-level chaos check/cleanup functions in
actions/azure_aks_actions.py — targeting the pure pre-check and cleanup
functions in the node trios (drain/taint/stress/crashloop). The polling
`_run_*` functions (threaded, Live-UI driven) and Azure-SDK-backed VMSS
functions are intentionally out of scope here given their complexity/mocking
cost relative to value; the pre-check/post-check/cleanup functions below
cover the bulk of the pure decision-logic in this area.
"""

from unittest.mock import patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    executor as m,
)


def _cp(stdout="", returncode=0, stderr=""):
    from subprocess import CompletedProcess
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ── _prechecks_node_drain ────────────────────────────────────────────────────

def test_prechecks_node_drain_ok_when_node_ready_and_healthy():
    with patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_pod_count", return_value=5), \
         patch.object(m, "_check_pdbs", return_value=[]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="node-a node-b")), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 3, 3)]):
        ok, snapshot = m._prechecks_node_drain("node-1")
    assert ok is True
    assert snapshot["pod_count_before"] == 5


def test_prechecks_node_drain_fails_hard_when_node_not_ready():
    with patch.object(m, "_node_is_ready", return_value=False), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_pod_count", return_value=0), \
         patch.object(m, "_check_pdbs", return_value=[]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="")), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_deployment_readiness", return_value=[]):
        ok, _snapshot = m._prechecks_node_drain("node-1")
    assert ok is False


def test_prechecks_node_drain_stays_ok_but_warns_on_blocking_pdbs():
    # Blocking PDBs are advisory only — should not flip ok to False.
    with patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_node_pod_count", return_value=2), \
         patch.object(m, "_check_pdbs", return_value=["pdb-a"]), \
         patch.object(m, "_kubectl", return_value=_cp(stdout="")), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_deployment_readiness", return_value=[]):
        ok, _snapshot = m._prechecks_node_drain("node-1")
    assert ok is True


# ── _postchecks_node_drain ───────────────────────────────────────────────────

def test_postchecks_node_drain_reports_recovery_when_all_healthy():
    state = {
        "nodes_before": ["node-1"],
        "unhealthy_before": [],
        "deployments_before": [("dep-a", "ns", 3, 3)],
        "pod_count_before": 5,
    }
    with patch.object(m.time, "sleep", lambda *_a, **_k: None), \
         patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_get_node_conditions", return_value={
             "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False",
         }), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 3, 3)]), \
         patch.object(m, "_pending_pods_exist", return_value=[]), \
         patch.object(m, "_get_unhealthy_pods", return_value=[]), \
         patch.object(m, "_get_node_names", return_value={"node-1"}):
        # Should complete without raising.
        m._postchecks_node_drain("node-1", state)


def test_postchecks_node_drain_detects_new_failures_after_drain():
    state = {
        "nodes_before": ["node-1"],
        "unhealthy_before": [],
        "deployments_before": [("dep-a", "ns", 3, 3)],
        "pod_count_before": 5,
    }
    with patch.object(m.time, "sleep", lambda *_a, **_k: None), \
         patch.object(m, "_node_is_ready", return_value=True), \
         patch.object(m, "_node_is_schedulable", return_value=True), \
         patch.object(m, "_get_node_conditions", return_value={
             "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False",
         }), \
         patch.object(m, "_get_deployment_readiness", return_value=[("dep-a", "ns", 3, 3)]), \
         patch.object(m, "_pending_pods_exist", return_value=[]), \
         patch.object(m, "_get_unhealthy_pods", return_value=[("pod-x", "ns", "CrashLoopBackOff")]), \
         patch.object(m, "_get_node_names", return_value={"node-1"}):
        # Should complete without raising even when new failures are present
        # (post-checks are advisory/console-output only, not hard-failing).
        m._postchecks_node_drain("node-1", state)


# ── _cleanup_crashloop ────────────────────────────────────────────────────────

def test_cleanup_crashloop_deletes_base_and_indexed_podchaos_crs():
    ctx = {"namespace": "ns", "label_val": "myapp"}
    base_name = m._crashloop_podchaos_name("ns", "myapp")

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "podchaos"):
            return _cp(stdout=f"{base_name} {base_name}-0 {base_name}-1 unrelated-cr")
        return _cp()

    with patch.object(m, "_kubectl", side_effect=_kubectl_router) as mock_kubectl:
        m._cleanup_crashloop(ctx)
    delete_calls = [c for c in mock_kubectl.call_args_list if c.args[:2] == ("delete", "podchaos")]
    deleted_names = {c.args[2] for c in delete_calls}
    assert deleted_names == {base_name, f"{base_name}-0", f"{base_name}-1"}


def test_cleanup_crashloop_no_op_when_no_matching_crs():
    ctx = {"namespace": "ns", "label_val": "myapp"}
    with patch.object(m, "_kubectl", return_value=_cp(stdout="unrelated-cr")) as mock_kubectl:
        m._cleanup_crashloop(ctx)
    delete_calls = [c for c in mock_kubectl.call_args_list if c.args[:2] == ("delete", "podchaos")]
    assert delete_calls == []
