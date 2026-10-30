import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety,
)


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _pre_checks(experiment_id="aks-cpu-stress", **kwargs):
    return safety.build_steady_state_checks(
        "ctx", "ns", "workload", "app", "demo", experiment_id, **kwargs,
    )


def _post_checks(experiment_id="aks-memory-stress", **kwargs):
    return safety.build_post_experiment_checks(
        experiment_id, "ctx", "ns", "workload", "app", "demo", **kwargs,
    )


def test_kubectl_uses_dispatcher_result_and_subprocess_fallback():
    dispatched = _result("from-client")
    with patch("chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl", return_value=dispatched):
        assert safety._kubectl("get", "pods", context="ctx") is dispatched

    with patch("chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl", side_effect=RuntimeError("offline")), \
         patch("chaosforge.providers.azure.components.aks.kubernetes.subprocess.run", return_value=_result("from-subprocess")) as run:
        assert safety._kubectl("get", "pods", context="ctx", timeout=7).stdout == "from-subprocess"
    assert run.call_args.args[0] == ["kubectl", "--request-timeout=15s", "--context", "ctx", "get", "pods"]
    assert run.call_args.kwargs["timeout"] == 7


def test_small_helpers_report_invalid_data_and_fallback_addresses():
    with patch.object(safety, "_kubectl", return_value=_result("not-json")):
        pods, error = safety._list_pods("ns", "app=demo", "ctx")
    assert pods is None
    assert "Could not parse pods" in error

    with patch.object(safety, "_kubectl", side_effect=[_result("not-json"), _result(returncode=1)]):
        assert safety._find_svc_name("ns", "app", "demo", "fallback", "ctx") == ("fallback", False)

    with patch.object(safety, "_kubectl", side_effect=[_result(returncode=1), _result(returncode=1)]):
        assert safety._np_partition_ping_target("ctx") == "10.0.0.10"


@pytest.mark.parametrize(
    ("selector", "labels"),
    [
        ({"matchExpressions": [{"key": "tier", "operator": "NotIn", "values": ["batch"]}]}, {"tier": "batch"}),
        ({"matchExpressions": [{"key": "tier", "operator": "DoesNotExist"}]}, {"tier": "api"}),
    ],
)
def test_label_selector_rejects_not_in_and_does_not_exist_mismatches(selector, labels):
    assert safety._label_selector_matches(selector, labels) is False


def test_pre_closures_cover_parse_failures_and_advisory_resource_paths():
    checks = _pre_checks("aks-cpu-stress")
    with patch.object(safety, "_kubectl", return_value=_result("not-json")):
        assert checks["Nodes Ready"]()[0] is False
        assert checks["Replica Floor (workload)"]()[0] is False
        assert checks["PodDisruptionBudget"]()[0] is True
        assert checks["No OOMKilled Containers"]()[0] is True
        assert checks["CPU Requests & Limits"]()[0] is True

    with patch.object(safety, "_kubectl", return_value=_result(returncode=1, stderr="denied")):
        assert checks["Container Exists (app)"]()[0] is False if "Container Exists (app)" in checks else True


def test_pre_closures_report_missing_container_and_resource_warnings():
    container_checks = _pre_checks("aks-container-kill", container_name="sidecar")
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps({"items": [{"metadata": {"name": "pod-a"}, "spec": {"containers": []}}]}))):
        passed, detail = container_checks["Container Exists (sidecar)"]()
    assert passed is False
    assert "not found" in detail

    cpu_checks = _pre_checks("aks-cpu-stress")
    pods = {"items": [{"metadata": {"name": "pod-a"}, "spec": {"containers": [{"name": "app", "resources": {}}]}}]}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        _, detail = cpu_checks["CPU Requests & Limits"]()
    assert "no CPU request" in detail
    assert "no CPU limit" in detail

    memory_checks = _pre_checks("aks-memory-stress")
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        _, detail = memory_checks["Memory Requests & Limits"]()
    assert "no memory request" in detail
    assert "no memory limit" in detail


def test_preflight_closures_handle_malformed_system_and_pdb_api_responses():
    checks = _pre_checks("aks-network-delay")
    with patch.object(safety, "_kubectl", return_value=_result("not-json")):
        passed, detail = checks["System Pods (CoreDNS, kube-proxy)"]()
    assert passed is False
    assert "NOT Ready" in detail

    with patch.object(safety, "_kubectl", side_effect=[_result(json.dumps({"items": []})), _result("not-json")]):
        passed, detail = checks["PodDisruptionBudget"]()
    assert passed is True
    assert "Could not parse PDB list" in detail

    with patch.object(safety, "_kubectl", side_effect=[_result(json.dumps({"items": []})), _result(returncode=1)]):
        passed, detail = checks["PodDisruptionBudget"]()
    assert passed is True
    assert "No PDB API available" in detail


def test_restart_and_oom_preflight_closures_cover_safe_failure_and_risk_paths():
    pod_checks = _pre_checks("aks-container-kill")
    with patch.object(safety, "_list_pods", return_value=(None, "forbidden")):
        passed, detail = pod_checks["Restart Stability"]()
    assert passed is True
    assert "skipping restart check" in detail

    clean = [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [{"name": "app", "restartCount": 0, "state": {}}]}}]
    with patch.object(safety, "_list_pods", return_value=(clean, None)):
        passed, detail = pod_checks["Restart Stability"]()
    assert passed is True
    assert "restarts > 0: none" in detail

    stress_checks = _pre_checks("aks-cpu-stress")
    pods = {"items": [{"metadata": {"name": "pod-a"}, "status": {"containerStatuses": [{
        "name": "app", "lastState": {"terminated": {"reason": "OOMKilled"}},
    }]}}]}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))):
        passed, detail = stress_checks["No OOMKilled Containers"]()
    assert passed is False
    assert "unsafe to stress" in detail


def test_node_metric_closures_handle_target_rows_and_empty_node_lookup():
    cpu_checks = _pre_checks("aks-cpu-stress")
    with patch.object(safety, "_kubectl", side_effect=[_result("node-a"), _result("node-b 10m 1% 1Mi 1%")]):
        _, detail = cpu_checks["CPU Headroom (node)"]()
    assert "target node rows not found" in detail

    memory_checks = _pre_checks("aks-memory-stress")
    with patch.object(safety, "_kubectl", return_value=_result(returncode=1)):
        _, detail = memory_checks["Memory Headroom (node)"]()
    assert "Could not determine node" in detail

    with patch.object(safety, "_kubectl", side_effect=[_result("node-a"), _result("node-a 20m 2% 64Mi 6%")]):
        passed, detail = memory_checks["Memory Headroom (node)"]()
    assert passed is True
    assert "node-a 20m" in detail


def test_network_annotation_and_live_pod_selection_preserve_target_accounting():
    result = {"message": "pods healthy | container restarts: 4", "net_rows": [("Container restarts", "4", "old")]}
    annotated = safety._annotate_network_result(result, ["target 1/1 Running", "control 0/1 Pending"], ["target", "missing"], 2)
    assert "targeted ready: 1/2" in annotated["message"]
    assert "targeted pod(s) absent: missing" in annotated["message"]
    assert annotated["net_rows"][0][2] == "baseline=2; new during fault=2"
    assert safety._select_live_probe_pod(["control 1/1 Running", "target 1/1 Running"], ["target"]) == "target"
    assert safety._select_live_probe_pod([], ["target"]) is None


def test_verify_fault_active_uses_multilabel_selector_and_reports_unready_dns_pods():
    with patch.object(safety, "_kubectl", return_value=_result("pod-a 1/1 Running 0\n")) as kubectl:
        safety.verify_fault_active("aks-unknown", "ctx", "ns", "dep", label_selectors_map={"app": "demo", "tier": "api"})
    assert "app=demo,tier=api" in kubectl.call_args.args

    dnschaos = {"items": [{"metadata": {"uid": "unready"}, "status": {"conditions": []}}]}

    def dns_response(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _result("pod-a 0/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any("patterns" in value for value in args):
            return _result("")
        return _result(json.dumps(dnschaos))

    with patch.object(safety, "_kubectl", side_effect=dns_response):
        result = safety.verify_fault_active("aks-dns-failure", "ctx", "ns-unready", "dep", "app", "demo")
    assert result["severity"] == "WARNING"
    assert "1 pod(s) NotReady" in result["message"]


def test_post_closures_cover_python_client_errors_and_exact_pod_recovery_paths():
    checks = _post_checks("aks-pod-kill")
    with patch("chaosforge.providers.azure.components.aks.kubernetes.get_pods", return_value=(None, "forbidden")):
        assert checks["Pod Recovery"]() == (False, "forbidden")
        assert checks["Containers Ready"]() == (False, "forbidden")
        assert checks["No CrashLoop"]() == (False, "forbidden")

    exact = _post_checks("aks-network-delay", target_mode="pod", exact_pod_name="pod-a")
    pods = {"items": [{"metadata": {"name": "pod-a"}, "status": {"podIP": "10.0.0.8"}}]}
    with patch.object(safety, "_kubectl", return_value=_result(json.dumps(pods))), \
         patch.object(safety, "_find_svc_name", return_value=("", False)):
        passed, detail = exact["Service Endpoints Restored"]()
    assert passed is True
    assert "not applicable" in detail

    with patch.object(safety, "_kubectl", side_effect=[_result(json.dumps(pods)), _result(returncode=1, stderr="forbidden")]), \
         patch.object(safety, "_find_svc_name", return_value=("svc", True)):
        assert exact["Service Endpoints Restored"]()[0] is False


@pytest.mark.parametrize(
    ("experiment_id", "builder"),
    [
        ("aks-clock-skew-forward", "build_time_chaos_post_checks"),
        ("aks-http-delay", "build_http_chaos_post_checks"),
        ("aks-dns-failure", "build_dns_chaos_post_checks"),
        ("aks-io-latency", "build_io_chaos_post_checks"),
        ("aks-coredns-kill", "build_cluster_plane_chaos_post_checks"),
    ],
)
def test_post_factories_merge_extended_closures(experiment_id, builder):
    path = "chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended."
    with patch(path + builder, return_value={"Extended": lambda: (True, "ok")}):
        assert "Extended" in _post_checks(experiment_id)
