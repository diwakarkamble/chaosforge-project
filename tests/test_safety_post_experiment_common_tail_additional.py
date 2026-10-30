import json
from datetime import datetime, timezone
from subprocess import CompletedProcess
from unittest.mock import patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety,
)


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _checks(experiment_id="aks-memory-stress", **kwargs):
    return safety.build_post_experiment_checks(
        experiment_id, "ctx", "ns", "workload", "app", "demo", **kwargs,
    )


def test_common_post_checks_pass_for_healthy_pods_and_restored_replicas():
    pods = {"items": [{"metadata": {"name": "pod-a"}, "status": {
        "phase": "Running", "containerStatuses": [{"name": "app", "ready": True, "state": {}}],
    }}]}
    deployment = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2, "availableReplicas": 2}}
    checks = _checks()
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        assert checks["Pod Recovery"]()[0] is True
        assert checks["Containers Ready"]()[0] is True
        assert checks["No CrashLoop"]()[0] is True
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(deployment))):
        assert checks["Replica Count Restored"]()[0] is True


def test_replica_post_check_accepts_a_running_standalone_pod_when_deployment_is_missing():
    checks = _checks("aks-container-kill")
    with patch.object(safety, "_kubectl", side_effect=[_result(returncode=1), _result("Running")]):
        passed, detail = checks["Replica Count Restored"]()

    assert passed is True
    assert "standalone pod" in detail


def test_common_post_event_check_flags_recent_crashloop_warning():
    event = {"type": "Warning", "lastTimestamp": datetime.now(timezone.utc).isoformat(),
             "reason": "BackOff", "message": "CrashLoopBackOff", "involvedObject": {"name": "pod-a"}}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps({"items": [event]}))):
        passed, detail = _checks("aks-container-kill")["Pod Events (last 5m)"]()

    assert passed is False
    assert "pod-a: BackOff" in detail


def test_stress_post_check_detects_an_oomkilled_container():
    pods = {"items": [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [{
        "name": "app", "lastState": {"terminated": {"reason": "OOMKilled"}},
    }]}}]}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        passed, detail = _checks()["No OOMKilled (post)"]()

    assert passed is False
    assert "pod-a/app" in detail


def test_exact_network_pod_post_check_requires_its_ip_in_service_endpoints():
    pods = {"items": [{"metadata": {"name": "pod-a"}, "status": {"podIP": "10.0.0.8"}}]}
    endpoints = {"subsets": [{"addresses": [{"ip": "10.0.0.9"}]}]}
    checks = _checks("aks-network-delay", target_mode="pod", exact_pod_name="pod-a")
    with patch.object(safety, "_kubectl", side_effect=[_result(json.dumps(pods)), _result(json.dumps(endpoints))]), \
         patch.object(safety, "_find_svc_name", return_value=("svc-a", True)):
        passed, detail = checks["Service Endpoints Restored"]()

    assert passed is False
    assert "not a ready Service endpoint" in detail


def test_exact_network_pod_probe_check_ignores_events_for_other_pods():
    event = {"involvedObject": {"name": "pod-b"}, "lastTimestamp": datetime.now(timezone.utc).isoformat(),
             "message": "Readiness probe failed"}
    checks = _checks("aks-network-delay", target_mode="pod", exact_pod_name="pod-a")
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps({"items": [event]}))):
        passed, detail = checks["Probe Failures Stopped (post)"]()

    assert passed is True
    assert "No recent probe failures" in detail


def test_common_post_checks_report_empty_or_unhealthy_workloads_and_advisory_event_errors():
    checks = _checks("aks-container-kill")
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps({"items": []}))):
        passed, detail = checks["Pod Recovery"]()
    assert passed is False
    assert "No pods found" in detail

    not_ready = {"items": [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [{
        "name": "app", "ready": False,
    }]}}]}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(not_ready))):
        passed, detail = checks["Containers Ready"]()
    assert passed is False
    assert "pod-a/app" in detail

    with patch.object(safety, "_kubectl", return_value=_result(returncode=1, stderr="forbidden")):
        passed, detail = checks["Pod Events (last 5m)"]()
    assert passed is True
    assert "non-fatal" in detail


def test_post_replica_and_stress_checks_handle_non_running_pods_and_invalid_json():
    checks = _checks("aks-memory-stress")
    with patch.object(safety, "_kubectl", side_effect=[_result(returncode=1), _result("Pending")]):
        passed, detail = checks["Replica Count Restored"]()
    assert passed is False
    assert "expected Running" in detail

    with patch.object(safety, "_kubectl", return_value=_result("not-json")):
        passed, detail = checks["No OOMKilled (post)"]()
    assert passed is False
    assert "Could not parse pods" in detail


def test_exact_network_post_checks_handle_missing_target_and_recent_target_event():
    checks = _checks("aks-network-delay", target_mode="pod", exact_pod_name="pod-a")
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps({"items": []}))):
        passed, detail = checks["Service Endpoints Restored"]()
    assert passed is False
    assert "found 0 matching pods" in detail

    event = {"involvedObject": {"name": "pod-a"}, "lastTimestamp": datetime.now(timezone.utc).isoformat(),
             "message": "Readiness probe failed"}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps({"items": [event]}))):
        passed, detail = checks["Probe Failures Stopped (post)"]()
    assert passed is False
    assert "Readiness probe failed" in detail
