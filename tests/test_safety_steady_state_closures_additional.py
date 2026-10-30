import json
from subprocess import CompletedProcess
from unittest.mock import patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety,
)


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _checks(experiment_id, **kwargs):
    return safety.build_steady_state_checks(
        "ctx", "ns", "workload", "app", "demo", experiment_id, **kwargs,
    )


def test_system_pods_uses_aks_kube_proxy_label_when_upstream_label_is_empty():
    coredns = {"items": [{"metadata": {"name": "dns-1"}, "status": {
        "phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
    }}]}
    proxy = {"items": [{"metadata": {"name": "proxy-1"}, "status": {
        "phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
    }}]}
    responses = [_result(json.dumps(coredns)), _result(json.dumps({"items": []})), _result(json.dumps(proxy))]

    with patch.object(safety, "_kubectl", side_effect=responses):
        passed, detail = _checks("aks-cpu-stress")["System Pods (CoreDNS, kube-proxy)"]()

    assert passed is True
    assert "label=component=kube-proxy" in detail


def test_replica_floor_falls_back_to_a_ready_standalone_pod():
    pod = {"status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}
    with patch.object(safety, "_kubectl", side_effect=[_result(returncode=1), _result(json.dumps(pod))]):
        passed, detail = _checks("aks-container-kill")["Replica Floor (workload)"]()

    assert passed is True
    assert "phase=Running" in detail


def test_restart_stability_blocks_increasing_historical_restarts_without_waiting():
    initial = [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [
        {"name": "app", "restartCount": 2, "state": {}},
    ]}}]
    later = [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [
        {"name": "app", "restartCount": 3, "state": {}},
    ]}}]
    with patch.object(safety, "_list_pods", side_effect=[(initial, None), (later, None)]), \
         patch.object(safety.time, "sleep") as sleep:
        passed, detail = _checks("aks-container-kill")["Restart Stability"]()

    sleep.assert_called_once_with(30)
    assert passed is False
    assert "actively crashing" in detail


def test_container_exists_reports_matching_pod():
    pods = {"items": [{"metadata": {"name": "pod-a"}, "spec": {"containers": [{"name": "app"}, {"name": "sidecar"}]}}]}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        passed, detail = _checks("aks-container-kill", container_name="sidecar")["Container Exists (sidecar)"]()

    assert passed is True
    assert "pod-a" in detail


def test_cpu_steady_state_closures_capture_resources_metrics_and_target_node():
    pods = {"items": [{
        "metadata": {"name": "pod-a"},
        "spec": {"containers": [{"name": "app", "resources": {"requests": {"cpu": "100m"}, "limits": {"cpu": "500m"}}}]},
    }]}
    checks = _checks("aks-cpu-stress")
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        assert checks["CPU Requests & Limits"]()[0] is True
    with patch.object(safety, "_kubectl", return_value=_result("pod-a app 30m 64Mi\n")):
        assert "pod-a app" in checks["CPU Baseline (current usage)"]()[1]
    with patch.object(safety, "_kubectl", side_effect=[_result("node-a"), _result("node-a 800m 40% 1Gi 25%\n")]):
        passed, detail = checks["CPU Headroom (node)"]()

    assert passed is True
    assert "node-a 800m" in detail


def test_memory_steady_state_closures_report_resources_and_skip_missing_node_metrics():
    pods = {"items": [{
        "metadata": {"name": "pod-a"},
        "spec": {"containers": [{"name": "app", "resources": {"requests": {"memory": "64Mi"}, "limits": {"memory": "128Mi"}}}]},
    }]}
    checks = _checks("aks-memory-stress")
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        passed, detail = checks["Memory Requests & Limits"]()
    assert passed is True
    assert "requests.memory=64Mi" in detail

    with patch.object(safety, "_kubectl", side_effect=[_result("node-a"), _result(returncode=1)]):
        passed, detail = checks["Memory Headroom (node)"]()
    assert passed is True
    assert "unavailable" in detail


def test_pod_count_and_restart_stability_cover_empty_crashloop_and_stable_history():
    checks = _checks("aks-pod-kill")
    with patch.object(safety, "_list_pods", return_value=([], None)):
        passed, detail = checks["Pod Count (pre-fault)"]()
    assert passed is False
    assert "nothing to inject" in detail

    crashloop = [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [{
        "name": "app", "restartCount": 1,
        "state": {"waiting": {"reason": "CrashLoopBackOff"}},
    }]}}]
    with patch.object(safety, "_list_pods", return_value=(crashloop, None)):
        passed, detail = checks["Restart Stability"]()
    assert passed is False
    assert "CrashLoopBackOff" in detail

    stable = [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [{
        "name": "app", "restartCount": 2, "state": {},
    }]}}]
    with patch.object(safety, "_list_pods", side_effect=[(stable, None), (stable, None)]), \
         patch.object(safety.time, "sleep"):
        passed, detail = checks["Restart Stability"]()
    assert passed is True
    assert "historical, not actively crashing" in detail


def test_pod_stress_closures_preserve_advisory_failures_and_detect_oom_history():
    cpu_checks = _checks("aks-cpu-stress")
    with patch.object(safety, "_kubectl", return_value=_result(returncode=1)):
        assert cpu_checks["No OOMKilled Containers"]()[0] is True
        assert cpu_checks["CPU Requests & Limits"]()[0] is True
        assert cpu_checks["CPU Baseline (current usage)"]()[0] is True
        assert cpu_checks["CPU Headroom (node)"]()[0] is True

    memory_checks = _checks("aks-memory-stress")
    oom_pods = {"items": [{"metadata": {"name": "pod-a"}, "status": {
        "containerStatuses": [{
            "name": "app",
            "state": {"terminated": {"reason": "OOMKilled"}},
            "lastState": {"terminated": {"reason": "OOMKilled", "finishedAt": "now"}},
        }],
    }}]}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(oom_pods))):
        passed, detail = memory_checks["OOM History"]()
    assert passed is False
    assert "high risk" in detail


def test_pdb_closure_matches_network_target_labels_and_handles_unavailable_data():
    checks = _checks("aks-network-delay", target_mode="pod", exact_pod_name="pod-a")
    target = {"items": [{"metadata": {"labels": {"app": "demo", "tier": "api"}}}]}
    blocked_pdb = {"items": [{
        "metadata": {"name": "budget"},
        "spec": {"selector": {"matchExpressions": [{"key": "tier", "operator": "In", "values": ["api"]}]}},
        "status": {"disruptionsAllowed": 0, "currentHealthy": 1, "desiredHealthy": 1},
    }]}
    with patch.object(safety, "_kubectl", side_effect=[_result(json.dumps(target)), _result(json.dumps(blocked_pdb))]):
        passed, detail = checks["PodDisruptionBudget"]()
    assert passed is False
    assert "budget" in detail

    with patch.object(safety, "_kubectl", return_value=_result(returncode=1, stderr="forbidden")):
        passed, detail = checks["PodDisruptionBudget"]()
    assert passed is True
    assert "skipping PDB check" in detail


def test_container_and_node_metric_closures_report_invalid_or_missing_data():
    container_checks = _checks("aks-container-kill", container_name="missing")
    with patch.object(safety, "_kubectl", return_value=_result("not-json")):
        passed, detail = container_checks["Container Exists (missing)"]()
    assert passed is False
    assert "Could not parse pods" in detail

    memory_checks = _checks("aks-memory-stress")
    with patch.object(safety, "_kubectl", return_value=_result("not-json")):
        assert memory_checks["Memory Requests & Limits"]()[0] is True
        assert memory_checks["Memory Baseline (current usage)"]()[0] is True
        assert memory_checks["OOM History"]()[0] is True
