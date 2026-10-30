import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.interfaces.cli.interactive import azure_aks_service as aks
from chaosforge.interfaces.cli.interactive import platform_selector as platform
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.azure.components.aks import kubernetes as k8s
from chaosforge.providers.azure.components.aks.experiments.chaos_studio import executor
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import safety


def _result(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


@pytest.fixture(autouse=True)
def restore_context():
    original = vars(context).copy()
    yield
    vars(context).clear()
    vars(context).update(original)


def test_aks_fixed_mode_validation_and_single_container(monkeypatch):
    discovery = MagicMock()
    discovery.list_namespaces.return_value = ["ns"]
    discovery.list_deployments.return_value = ["api"]
    discovery.get_label_selector.return_value = ("app", "api")
    discovery.get_safe_label_selector.return_value = {"app": "api"}
    discovery.get_pod_count.return_value = 2
    discovery.list_containers.return_value = ["web"]
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(aks, "title", MagicMock())
    monkeypatch.setattr(aks, "console", MagicMock())
    monkeypatch.setattr(aks, "info", MagicMock())
    monkeypatch.setattr(aks, "error", MagicMock())
    monkeypatch.setattr(
        aks,
        "_pick",
        MagicMock(side_effect=["ns", "By Deployment", "api", "fixed  - exact", "fixed  - exact"]),
    )
    monkeypatch.setattr(aks, "prompt", MagicMock(side_effect=["bad", "3", "2", "n"]))
    context.aks_kube_context = "ctx"
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    context.aks_cluster_name = "cluster"

    values = aks._collect_aks_inputs({
        "name": "Experiment",
        "inputs": [
            {"name": "aks_context", "type": "azure_aks_cluster"},
            {"name": "namespace", "type": "azure_aks_namespace"},
            {"name": "deployment", "type": "azure_aks_deployment"},
            {"name": "container_name", "type": "azure_aks_container"},
            {"name": "chaos_mode", "type": "chaos_mode"},
            {"name": "chaos_value"},
        ],
    })

    assert values["container_name"] == "web"
    assert values["chaos_value"] == "2"
    assert aks.error.call_count == 2


def test_aks_pod_back_retries_target_mode_and_namespace(monkeypatch):
    discovery = MagicMock()
    discovery.list_namespaces.return_value = ["first", "second"]
    discovery.list_pods.return_value = ["pod-a"]
    discovery.get_pod_label.return_value = ("app", "api")
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(aks, "title", MagicMock())
    monkeypatch.setattr(aks, "console", MagicMock())
    monkeypatch.setattr(aks, "info", MagicMock())
    picks = MagicMock(side_effect=[
        "first", aks._BackStep(), "second", "By Pod", aks._BackStep(),
        "By Pod", "pod-a",
    ])
    monkeypatch.setattr(aks, "_pick", picks)
    monkeypatch.setattr(aks, "prompt", MagicMock(return_value="n"))

    values = aks._collect_aks_inputs({
        "name": "Pod",
        "inputs": [{"name": "namespace", "type": "azure_aks_namespace"}],
    })

    assert values["namespace"] == "second"
    assert values["deployment"] == "pod-a"
    assert values["target_mode"] == "pod"


def test_platform_kubectl_context_fallback_and_none_selection(monkeypatch):
    clusters = [{"name": "aks", "resourceGroup": "rg", "location": "eastus"}]
    runs = MagicMock(side_effect=[
        _result(json.dumps({"name": "Account"})),
        _result(json.dumps(clusters)),
        _result("aks-admin\n"),
        _result(),
    ])
    monkeypatch.setattr(platform.subprocess, "run", runs)
    monkeypatch.setattr(platform, "prompt", MagicMock(side_effect=["sub-12345678", "1", "0", "y"]))
    monkeypatch.setattr(platform, "console", MagicMock())
    monkeypatch.setattr(platform, "title", MagicMock())
    monkeypatch.setattr(platform, "info", MagicMock())
    monkeypatch.setattr(platform, "error", MagicMock())
    monkeypatch.setattr(platform, "_save_azure_cache", MagicMock())
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda *_: nullcontext()
    )
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.tables.menu", MagicMock())
    monkeypatch.setattr(k8s, "list_kube_contexts", MagicMock(return_value=[]))

    assert platform.PlatformSelector()._prompt_azure_details() is True
    assert context.aks_kube_context == "aks"
    assert all(call.args[0][:3] != ["kubectl", "config", "get-contexts"] for call in runs.call_args_list)


def test_kubernetes_remaining_api_exception_paths(monkeypatch, tmp_path):
    api = MagicMock()
    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = k8s.ApiException(status=500, reason="rollout denied")
    monkeypatch.setattr(k8s, "_get_api_client", MagicMock(return_value=api))
    monkeypatch.setattr(k8s.client, "AppsV1Api", MagicMock(return_value=apps))
    result = k8s._dispatch_rollout("status", ["deployment/api", "-n", "ns"], "ctx")
    assert result.stderr == "rollout denied"

    manifest = tmp_path / "pod.json"
    manifest.write_text('{"kind":"Pod","metadata":{"name":"p","namespace":"ns"}}')
    core = MagicMock()
    core.create_namespaced_pod.side_effect = k8s.ApiException(status=500, reason="create denied")
    monkeypatch.setattr(k8s.client, "CoreV1Api", MagicMock(return_value=core))
    assert k8s._dispatch_apply(["-f", str(manifest)], "ctx").stderr == "create denied"

    core = MagicMock()
    core.patch_node.side_effect = RuntimeError("transport")
    monkeypatch.setattr(k8s.client, "CoreV1Api", MagicMock(return_value=core))
    assert k8s._dispatch_cordon(False, ["node"], "ctx") is None

    monkeypatch.setattr(k8s, "set_current_kube_context", MagicMock(side_effect=OSError("bad")))
    assert k8s._dispatch_config(["use-context", "ctx"], "ctx") is None


def test_kubernetes_get_apply_and_drain_residual_paths(monkeypatch, tmp_path):
    api = MagicMock()
    api.sanitize_for_serialization.side_effect = lambda value: value
    core = MagicMock()
    core.read_namespaced_service.return_value = {"metadata": {"name": "svc"}}
    monkeypatch.setattr(k8s, "_get_api_client", MagicMock(return_value=api))
    monkeypatch.setattr(k8s.client, "CoreV1Api", MagicMock(return_value=core))
    assert k8s._dispatch_get("service", ["svc"], "ctx") is None

    manifest = tmp_path / "chaos.json"
    manifest.write_text('{"kind":"PodChaos","metadata":{"name":"f","namespace":"ns"}}')
    custom = MagicMock()
    custom.create_namespaced_custom_object.side_effect = k8s.ApiException(status=409)
    monkeypatch.setattr(k8s.client, "CustomObjectsApi", MagicMock(return_value=custom))
    assert k8s._dispatch_apply(["-f", str(manifest)], "ctx").returncode == 0
    custom.replace_namespaced_custom_object.assert_called_once()

    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="p", namespace="ns", owner_references=[]),
        status=SimpleNamespace(phase="Running"),
    )
    core = MagicMock()
    core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[pod])
    core.read_namespaced_pod.side_effect = k8s.ApiException(status=500)
    monkeypatch.setattr(k8s.client, "CoreV1Api", MagicMock(return_value=core))
    monkeypatch.setattr(k8s, "_drain_evict_pod", MagicMock(return_value=(True, "")))
    with patch("time.monotonic", side_effect=[0, 0, 0, 2]), patch("time.sleep"):
        result = k8s._dispatch_drain([
            "node", "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--timeout=1s"
        ], "ctx")
        assert result.returncode == 1
        assert "waiting for pod termination" in result.stderr


def test_safety_steady_state_residual_closures(monkeypatch):
    monkeypatch.setattr(safety, "_find_svc_name", MagicMock(return_value=("api", True)))
    pod = {
        "metadata": {"name": "p", "labels": {"app": "api"}},
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        "spec": {"containers": [{"name": "web", "resources": {}}]},
    }
    pdbs = {"items": [
        {"metadata": {"name": "other"}, "spec": {"selector": {"matchLabels": {"app": "other"}}}},
        {"metadata": {"name": "api"}, "spec": {"selector": {"matchLabels": {"app": "api"}}},
         "status": {"disruptionsAllowed": 1, "currentHealthy": 2, "desiredHealthy": 1}},
    ]}
    responses = {
        "deployment": _result(json.dumps({"spec": {"replicas": 2}, "status": {"readyReplicas": 2}})),
        "pdb": _result(json.dumps(pdbs)),
        "pods": _result(json.dumps({"items": [pod]})),
        "nodes": _result("", returncode=1),
        "top": _result("", returncode=1),
    }

    def kubectl(*args, **kwargs):
        return responses.get(args[1] if args and args[0] == "get" else args[0], _result())

    monkeypatch.setattr(safety, "_kubectl", kubectl)
    monkeypatch.setattr(safety, "_list_pods", MagicMock(return_value=([pod], None)))

    cpu = safety.build_steady_state_checks(
        "ctx", "ns", "api", "app", "api", "aks-cpu-stress", container_name="web"
    )
    assert cpu["PodDisruptionBudget"]()[0] is True
    assert cpu["Pod Count (pre-fault)"]()[0] is True
    assert cpu["No OOMKilled Containers"]()[0] is True
    assert cpu["CPU Requests & Limits"]()[0] is True
    assert cpu["CPU Baseline (current usage)"]()[0] is True
    assert cpu["CPU Headroom (node)"]()[0] is True

    memory = safety.build_steady_state_checks(
        "ctx", "ns", "api", "app", "api", "aks-memory-stress"
    )
    assert memory["Memory Requests & Limits"]()[0] is True
    assert memory["Memory Baseline (current usage)"]()[0] is True
    assert memory["Memory Headroom (node)"]()[0] is True
    assert memory["OOM History"]()[0] is True


def test_safety_query_failure_and_post_event_residuals(monkeypatch):
    failed = _result(returncode=1, stderr="unavailable")
    monkeypatch.setattr(safety, "_kubectl", MagicMock(return_value=failed))
    monkeypatch.setattr(safety, "_list_pods", MagicMock(return_value=(None, "pod query failed")))
    checks = safety.build_steady_state_checks(
        "ctx", "ns", "api", "app", "api", "aks-memory-stress"
    )
    assert checks["Pod Count (pre-fault)"]() == (False, "pod query failed")
    assert checks["No OOMKilled Containers"]()[0] is True
    assert checks["Memory Requests & Limits"]()[0] is True
    assert checks["Memory Baseline (current usage)"]()[0] is True
    assert checks["OOM History"]()[0] is True

    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    recent_bad = datetime.now(timezone.utc).isoformat()
    events = {"items": [
        {"type": "Normal", "reason": "Failed", "lastTimestamp": recent_bad},
        {"type": "Warning", "reason": "Failed", "lastTimestamp": old},
        {"type": "Warning", "reason": "Other", "lastTimestamp": "invalid", "message": "all good"},
    ]}
    def post_kubectl(*args, **kwargs):
        if args[:2] == ("get", "pod"):
            return _result(returncode=1)
        return _result(json.dumps(events))

    monkeypatch.setattr(safety, "_kubectl", post_kubectl)
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.kubernetes.get_pods",
        MagicMock(return_value=([], None)),
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.kubernetes.get_deployment",
        MagicMock(return_value=(None, "not found")),
    )
    post = safety.build_post_experiment_checks("aks-pod-kill", "ctx", "ns", "missing")
    assert post["Replica Count Restored"]()[0] is True
    assert post["Pod Events (last 5m)"]()[0] is True


def test_safety_post_oom_and_exact_pod_event_paths(monkeypatch):
    healthy = {
        "metadata": {"name": "pod", "labels": {"app": "api"}},
        "status": {"phase": "Running", "podIP": "10.0.0.2", "containerStatuses": []},
    }
    monkeypatch.setattr(safety, "_kubectl", MagicMock(return_value=_result(json.dumps({"items": []}))))
    monkeypatch.setattr(safety, "_find_svc_name", MagicMock(return_value=("api", True)))
    monkeypatch.setattr(safety, "_list_pods", MagicMock(return_value=([healthy], None)))
    stress = safety.build_post_experiment_checks("aks-cpu-stress", "ctx", "ns", "api")
    assert stress["No OOMKilled (post)"]()[0] is True

    exact = safety.build_post_experiment_checks(
        "aks-network-delay", "ctx", "ns", "pod", "app", "api",
        target_mode="pod", exact_pod_name="pod",
    )
    monkeypatch.setattr(safety, "_kubectl", MagicMock(return_value=_result(returncode=1, stderr="query failed")))
    if "Service Endpoints Restored" in exact:
        assert exact["Service Endpoints Restored"]()[0] is False
    if "Probe Failures Stopped (post)" in exact:
        assert exact["Probe Failures Stopped (post)"]()[0] is True


def test_executor_local_residual_helpers(monkeypatch, tmp_path):
    bad = tmp_path / f"aks_chaos_state_bad_{executor.os.getpid()}.json"
    bad.write_text("not-json")
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    assert executor._load_state() == {}

    monkeypatch.setattr(executor, "_kubectl", MagicMock(return_value=_result("chaos = NoExecute")))
    assert executor._node_has_chaos_taint("node") is True
    monkeypatch.setattr(executor, "_kubectl_json", MagicMock(return_value={"spec": {"taints": []}}))
    assert executor._node_taint_confirmed("node") is False
    monkeypatch.setattr(executor, "_kubectl_json", MagicMock(return_value=None))
    assert executor._resolve_node_stress_canary("node") is None

    assert "terminate/disrupt" in executor._destructive_warning("aks-crashloop")
    assert "VM Scale Set" in executor._destructive_warning("aks-node-notready")
    assert executor._get_node_stress_workload_status("node") is None


def test_executor_crashloop_invalid_restart_count(monkeypatch):
    state = {
        "namespace": "ns", "deployment": "pod", "label_key": "app", "label_val": "api",
        "duration": 1, "chaos_mode": "one", "experiment_id": "aks-crashloop",
    }
    calls = iter([
        _result("pod 1/1 Running 0"),
        _result(),
        _result("pod 1/1 Running invalid"),
    ])
    monkeypatch.setattr(executor, "_kubectl", MagicMock(side_effect=lambda *a, **k: next(calls, _result())))
    monkeypatch.setattr(executor.time, "time", MagicMock(side_effect=[0, 0, 0, 2]))
    monkeypatch.setattr(executor.time, "sleep", MagicMock())
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log.log_crashloop_event",
        MagicMock(),
    )
    monkeypatch.setattr(executor.os, "unlink", MagicMock())

    executor._run_crashloop(state)
