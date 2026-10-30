"""Focused coverage for previously untested executor failure and empty-result paths."""

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import executor


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_kubernetes_query_helpers_handle_empty_results_and_filter_records():
    daemon = {
        "metadata": {"name": "daemon", "namespace": "kube", "ownerReferences": [{"kind": "DaemonSet"}]},
        "status": {"phase": "Running", "containerStatuses": [{"restartCount": 9}]},
    }
    crashloop = {
        "metadata": {"name": "api", "namespace": "app"},
        "status": {
            "phase": "Running",
            "containerStatuses": [{"restartCount": 2, "state": {"waiting": {"reason": "OOMKilled"}}}],
        },
    }
    deployment = {
        "metadata": {"name": "api", "namespace": "app"},
        "spec": {"replicas": 2},
        "status": {"readyReplicas": 1},
    }
    pdb = {"metadata": {"name": "protect-api"}, "status": {"disruptionsAllowed": 0}}

    with patch.object(executor, "_kubectl_json", side_effect=[None, {"items": [pdb]}, None, {"items": [daemon, crashloop]}, None, {"items": [deployment]}, None]):
        assert executor._node_pod_count("node-a") == 0
        assert executor._check_pdbs("app") == ["protect-api"]
        assert executor._pending_pods_exist() == []
        assert executor._get_unhealthy_pods() == [("api", "app", "OOMKilled")]
        assert executor._get_deployment_readiness() == []
        assert executor._get_deployment_readiness() == [("api", "app", 1, 2)]
        assert executor._get_node_conditions("node-a") == {}


def test_stress_helpers_cover_invalid_metrics_empty_data_and_during_fault_flags():
    with patch.object(executor, "_kubectl", side_effect=[_result(returncode=1), _result("node-a 10m")]):
        assert executor._get_node_top("node-a") is None
        assert executor._get_node_top("node-a") is None

    with patch.object(executor, "_kubectl_json", side_effect=[None, None, None]):
        assert executor._get_pod_restart_counts("node-a") == {}
        assert executor._get_node_stress_workload_status("node-a") is None
        assert executor._resolve_node_stress_canary("node-a") is None

    snapshot = {}
    executor._record_node_stress_impact(
        snapshot,
        canary_probe={"summary": "dns failed", "dns_status": "failed"},
        node_conditions={"DiskPressure": "True", "MemoryPressure": "True", "PIDPressure": "True"},
        iowait_pct=4.5,
    )
    assert snapshot["canary_dns_failures"] == 1
    assert snapshot["disk_pressure_fired"] is True
    assert snapshot["mem_pressure_fired"] is True
    assert snapshot["pid_pressure_fired"] is True
    assert snapshot["max_iowait_pct_during"] == 4.5


def test_node_stress_precheck_aborts_before_cluster_mutations():
    session = MagicMock()
    with patch.object(executor, "_get_node_conditions", return_value={"Ready": "False"}):
        ok, snapshot = executor._prechecks_node_stress("node-a", "cpu", session=session)

    assert (ok, snapshot) == (False, {})
    session.log_event.assert_any_call("pre-check", "Node node-a not Ready — aborting")


def test_deploy_stress_pod_rejects_terminal_failed_phase(monkeypatch, tmp_path):
    manifest_path = tmp_path / "stress.json"

    class Temp:
        name = str(manifest_path)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, value):
            manifest_path.write_text(value)
            return len(value)

    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", lambda **_kwargs: Temp())
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    with patch.object(executor, "_kubectl", side_effect=[_result(), _result(), _result("Unknown")]):
        with pytest.raises(RuntimeError, match="phase=Unknown"):
            executor._deploy_stress_pod("stress", {"kind": "Pod"})

    assert not manifest_path.exists()


def test_crashloop_rejects_empty_selector_and_apply_failure(monkeypatch, tmp_path):
    with patch.object(executor, "_kubectl", return_value=_result()):
        with pytest.raises(RuntimeError, match="No running pods found"):
            executor._run_crashloop({"namespace": "app", "label_val": "api"})

    manifest_path = tmp_path / "crashloop.json"

    class Temp:
        name = str(manifest_path)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, value):
            manifest_path.write_text(value)
            return len(value)

    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", lambda **_kwargs: Temp())
    monkeypatch.setattr(executor.time, "time", lambda: 0)
    with patch.object(executor, "_kubectl", side_effect=[_result("api-1"), _result(), _result(returncode=1, stderr="denied")]):
        with pytest.raises(RuntimeError, match="Failed to apply PodChaos for api-1: denied"):
            executor._run_crashloop({"namespace": "app", "label_val": "api", "duration": 1})

    assert not manifest_path.exists()
