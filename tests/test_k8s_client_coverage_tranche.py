import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks import kubernetes as k8s


def _api(serialized):
    api = MagicMock()
    api.sanitize_for_serialization.return_value = serialized
    return api


def test_jsonpath_and_output_rendering_cover_supported_and_fallback_shapes():
    pod = {
        "metadata": {"name": "api"},
        "status": {"containerStatuses": [{"ready": True, "restartCount": 2}]},
        "spec": {"containers": [{"name": "main"}, {"name": "sidecar"}]},
    }
    assert k8s._jsonpath_get("{.spec.containers[?(@.name=='main')].name}", pod) == "main"
    assert k8s._jsonpath_get("{.spec.containers[99].name}", pod) == ""
    labeled = {"metadata": {"labels": {"app.name": "api"}}}
    assert k8s._jsonpath_get(r"{.metadata.labels.app\.name}", labeled) == "api"
    assert k8s._pod_table_line(pod) == "api\t1/1\tUnknown\t2\t<age>"
    assert k8s._custom_columns_get("NAME:.metadata.name,PHASE:.status.phase", [pod], False) == (
        "NAME PHASE\napi <none>"
    )
    assert k8s._custom_columns_get("broken", [pod], False) is None
    assert k8s._apply_output([pod], False, {"output": "json", "no_headers": False}).stdout == json.dumps({"items": [pod]})
    assert k8s._apply_output([pod], False, {"output": "custom-columns=NAME:.metadata.name", "no_headers": True}).stdout == "api"
    assert k8s._apply_output([pod], False, {"output": None, "no_headers": True}, k8s._pod_table_line).stdout.startswith("api\t")
    assert k8s._apply_output(labeled, True, {"output": r"jsonpath={.metadata.labels.app\.name}", "no_headers": False}).stdout == "api"


def test_parse_get_and_delete_arguments_reject_unsupported_flags_and_keep_supported_values():
    assert k8s._parse_get_args(["-n", "ns", "--all-namespaces", "-l", "a=b", "--field-selector", "x=y", "--no-headers", "pod"]) == {
        "name": "pod", "namespace": "ns", "all_namespaces": True, "selector": "a=b",
        "field_selector": "x=y", "output": None, "no_headers": True,
    }
    assert k8s._parse_get_args(["--watch"]) is None
    assert k8s._parse_delete_args(["pod", "-n", "ns", "--force", "--wait=false", "--request-timeout=1s", "--grace-period=5"])["grace_period_seconds"] == 5
    assert k8s._parse_delete_args(["--bogus"]) is None


@pytest.mark.parametrize(
    ("resource", "args", "method", "serialized"),
    [
        ("pods", ["-n", "ns", "-l", "app=x"], "list_namespaced_pod", {"items": []}),
        ("deployment", ["dep", "-n", "ns"], "read_namespaced_deployment", {"metadata": {"name": "dep"}}),
        ("replicasets", ["-n", "ns"], "list_namespaced_replica_set", {"items": []}),
        ("replicaset", ["rs", "-n", "ns"], "read_namespaced_replica_set", {"metadata": {"name": "rs"}}),
        ("nodes", ["node"], "read_node", {"metadata": {"name": "node"}}),
        ("services", ["-n", "ns"], "list_namespaced_service", {"items": []}),
    ],
)
def test_dispatch_get_handles_remaining_core_resource_shapes(resource, args, method, serialized):
    api, v1, apps = _api(serialized), MagicMock(), MagicMock()
    getattr(v1 if method in {"list_namespaced_pod", "read_node", "list_namespaced_service"} else apps, method).return_value = MagicMock()
    with patch.object(k8s, "_get_api_client", return_value=api), \
         patch.object(k8s.client, "CoreV1Api", return_value=v1), \
         patch.object(k8s.client, "AppsV1Api", return_value=apps):
        result = k8s._dispatch_get(resource, args, "ctx")
    assert result.returncode == 0
    assert getattr(v1 if method in {"list_namespaced_pod", "read_node", "list_namespaced_service"} else apps, method).called


def test_dispatch_get_chaos_namespaced_list_and_api_error():
    custom, v1 = MagicMock(), MagicMock()
    custom.list_namespaced_custom_object.return_value = {"items": [{"metadata": {"name": "fault"}}]}
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s.client, "CoreV1Api", return_value=v1), \
         patch.object(k8s.client, "CustomObjectsApi", return_value=custom):
        assert k8s._dispatch_get("podchaos", ["-n", "ns"], "ctx").returncode == 0
    v1.list_namespace.side_effect = k8s.ApiException(status=500, reason="unavailable")
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(k8s.client, "CoreV1Api", return_value=v1):
        result = k8s._dispatch_get("namespace", [], "ctx")
    assert result.returncode == 1 and "unavailable" in result.stderr


def test_mutating_dispatchers_cover_success_error_and_fallback_paths():
    api, custom, v1 = MagicMock(), MagicMock(), MagicMock()
    with patch.object(k8s, "_get_api_client", return_value=api), \
         patch.object(k8s.client, "CustomObjectsApi", return_value=custom), \
         patch.object(k8s.client, "CoreV1Api", return_value=v1):
        assert k8s._dispatch_delete("pod", ["p", "-n", "ns", "--grace-period=3"], "ctx").returncode == 0
        assert k8s._dispatch_patch("podchaos", ["p", "-n", "ns", "--type=application/json-patch+json", "-p=[]"], "ctx").returncode == 0
        assert k8s._dispatch_label("namespace", ["ns", "not-a-label"], "ctx") is None
    custom.patch_namespaced_custom_object.side_effect = k8s.ApiException(status=500, reason="denied")
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(k8s.client, "CustomObjectsApi", return_value=custom):
        assert k8s._dispatch_patch("podchaos", ["p", "-n", "ns", "--type=json", "-p=[]"], "ctx").stderr == "denied"
    v1.patch_node.side_effect = RuntimeError("broken")
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(k8s.client, "CoreV1Api", return_value=v1):
        assert k8s._dispatch_cordon(False, ["node"], "ctx") is None


def test_taint_and_exec_cover_api_error_and_generic_fallback():
    v1 = MagicMock()
    v1.read_node.side_effect = k8s.ApiException(status=404)
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(k8s.client, "CoreV1Api", return_value=v1):
        assert k8s._dispatch_taint(["nodes", "node", "key:NoSchedule"], "ctx").stderr == "not found"
    with patch.object(k8s, "_get_api_client", side_effect=RuntimeError("no config")):
        assert k8s._dispatch_exec(["pod", "-n", "ns", "--", "true"], "ctx") is None


def test_apply_replaces_chaos_manifest_and_returns_api_errors(tmp_path):
    manifest = {"kind": "NetworkChaos", "metadata": {"name": "fault", "namespace": "ns"}}
    path = tmp_path / "fault.json"
    path.write_text(json.dumps(manifest))
    custom = MagicMock()
    custom.create_namespaced_custom_object.side_effect = k8s.ApiException(status=409)
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(k8s.client, "CustomObjectsApi", return_value=custom):
        assert k8s._dispatch_apply(["-f", str(path)], "ctx").returncode == 0
    custom.create_namespaced_custom_object.side_effect = k8s.ApiException(status=403, reason="forbidden")
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(k8s.client, "CustomObjectsApi", return_value=custom):
        assert k8s._dispatch_apply(["-f", str(path)], "ctx").stderr == "forbidden"


def test_top_covers_container_and_single_node_metrics():
    custom, v1 = MagicMock(), MagicMock()
    custom.list_namespaced_custom_object.return_value = {"items": [{"metadata": {"name": "pod"}, "containers": [{"name": "app", "usage": {"cpu": "1m", "memory": "1Mi"}}]}]}
    node = SimpleNamespace(status=SimpleNamespace(allocatable={"cpu": "2", "memory": "2Gi"}))
    v1.read_node.return_value = node
    custom.get_cluster_custom_object.return_value = {"metadata": {"name": "node"}, "usage": {"cpu": "1", "memory": "1Gi"}}
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s.client, "CustomObjectsApi", return_value=custom), \
         patch.object(k8s.client, "CoreV1Api", return_value=v1):
        assert "app" in k8s._dispatch_top(["pods", "-n", "ns", "--containers"], "ctx").stdout
        assert "50%" in k8s._dispatch_top(["node", "node"], "ctx").stdout
    assert k8s._dispatch_top(["node"], "ctx") is None
    assert k8s._dispatch_top(["pods", "--bad"], "ctx") is None


@pytest.mark.parametrize(
    ("verb", "target"),
    [
        ("patch", "_dispatch_patch"), ("label", "_dispatch_label"), ("taint", "_dispatch_taint"),
        ("cordon", "_dispatch_cordon"), ("uncordon", "_dispatch_cordon"), ("rollout", "_dispatch_rollout"),
        ("create", "_dispatch_create"), ("apply", "_dispatch_apply"), ("drain", "_dispatch_drain"),
        ("config", "_dispatch_config"),
    ],
)
def test_dispatch_kubectl_routes_remaining_verbs(verb, target):
    with patch.object(k8s, target, return_value=k8s._ok()) as dispatched:
        k8s.dispatch_kubectl((verb, "thing"), "ctx")
    assert dispatched.called


def test_config_and_context_write_failures_fall_back(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("contexts:\n- name: ctx\n")
    with patch.object(k8s, "_kubeconfig_path", return_value=str(cfg)), patch("builtins.open", side_effect=OSError("readonly")):
        assert k8s.set_current_kube_context("ctx") is False
        assert k8s.delete_kube_context("ctx") is False
    with patch.object(k8s, "set_current_kube_context", side_effect=RuntimeError("bad")):
        assert k8s._dispatch_config(["use-context", "ctx"], "ctx") is None


def test_safe_fallback_guards_and_delete_client_failure():
    assert k8s._dispatch_exec(["pod", "-n", "ns", "not-separator", "true"], "ctx") is None
    assert k8s._dispatch_top([], "ctx") is None
    assert k8s._dispatch_drain([], "ctx") is None
    assert k8s._dispatch_drain(["node", "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--timeout=forever"], "ctx") is None
    custom = MagicMock()
    custom.delete_namespaced_custom_object.side_effect = RuntimeError("transport failed")
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(k8s.client, "CustomObjectsApi", return_value=custom):
        assert k8s._dispatch_delete("podchaos", ["fault", "-n", "ns"], "ctx") is None


def test_create_and_get_crd_non_not_found_errors_are_reported():
    v1 = MagicMock()
    v1.create_namespace.side_effect = k8s.ApiException(status=500, reason="denied")
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(k8s.client, "CoreV1Api", return_value=v1):
        assert k8s._dispatch_create("namespace", ["ns"], "ctx").stderr == "denied"
    ext = MagicMock()
    ext.read_custom_resource_definition.side_effect = k8s.ApiException(status=500, reason="unavailable")
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s.client, "ApiextensionsV1Api", return_value=ext):
        assert k8s._dispatch_get("crd", ["faults.example"], "ctx").stderr == "unavailable"


def test_python_client_handles_cluster_wide_resources_and_remaining_kinds():
    api = _api({"items": []})
    v1 = MagicMock()
    apps = MagicMock()
    policy = MagicMock()
    admission = MagicMock()
    custom = MagicMock()
    with patch.object(k8s, "_get_api_client", return_value=api), \
         patch.object(k8s.client, "CoreV1Api", return_value=v1), \
         patch.object(k8s.client, "AppsV1Api", return_value=apps), \
         patch.object(k8s.client, "PolicyV1Api", return_value=policy), \
         patch.object(k8s.client, "AdmissionregistrationV1Api", return_value=admission), \
         patch.object(k8s.client, "CustomObjectsApi", return_value=custom):
        assert k8s._dispatch_get("pods", ["--all-namespaces"], "ctx").returncode == 0
        assert k8s._dispatch_get("deployments", ["--all-namespaces"], "ctx").returncode == 0
        assert k8s._dispatch_get("pdb", ["--all-namespaces"], "ctx").returncode == 0
        assert k8s._dispatch_get("daemonsets", ["-n", "system"], "ctx").returncode == 0
        assert k8s._dispatch_get("statefulsets", ["-n", "app"], "ctx").returncode == 0
        assert k8s._dispatch_get("pv", [], "ctx").returncode == 0
        assert k8s._dispatch_get("mutatingwebhookconfiguration", [], "ctx").returncode == 0
        assert k8s._dispatch_get("certificates", ["-n", "app"], "ctx").returncode == 0

    v1.list_pod_for_all_namespaces.assert_called_once()
    apps.list_deployment_for_all_namespaces.assert_called_once()
    policy.list_pod_disruption_budget_for_all_namespaces.assert_called_once()
    apps.list_namespaced_daemon_set.assert_called_once()
    apps.list_namespaced_stateful_set.assert_called_once()
    v1.list_persistent_volume.assert_called_once()
    admission.list_mutating_webhook_configuration.assert_called_once()
    custom.list_namespaced_custom_object.assert_called_once_with(
        "cert-manager.io", "v1", "app", "certificates"
    )


def test_optional_kubectl_fallback_reports_missing_binary_and_timeout():
    with patch.object(k8s, "dispatch_kubectl", return_value=None), patch.object(
        k8s.subprocess, "run", side_effect=FileNotFoundError
    ):
        result = k8s.run_kubernetes_command(("version",), "ctx")
    assert result.returncode == 127
    assert "optional kubectl" in result.stderr

    with patch.object(k8s, "dispatch_kubectl", return_value=None), patch.object(
        k8s.subprocess,
        "run",
        side_effect=k8s.subprocess.TimeoutExpired(["kubectl"], 1),
    ):
        result = k8s.run_kubernetes_command(("version",), timeout=1)
    assert result.returncode == 124


def test_drain_fails_when_evicted_pods_do_not_terminate(monkeypatch):
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="api", namespace="app", owner_references=[]),
        status=SimpleNamespace(phase="Running"),
    )
    v1 = MagicMock()
    v1.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[pod])
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: MagicMock())
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda _: v1)
    monkeypatch.setattr(k8s, "_drain_evict_pod", lambda *_args, **_kwargs: (True, ""))
    clock = iter((0, 0, 2))
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    monkeypatch.setattr("time.sleep", lambda *_: None)

    result = k8s._dispatch_drain(
        ["node", "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--timeout=1s"],
        "ctx",
    )

    assert result.returncode == 1
    assert "waiting for pod termination" in result.stderr
