import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli.interactive import azure_redis_menu as redis_menu
from chaosforge.interfaces.cli.interactive import platform_selector as platform
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.azure.components.aks import discovery
from chaosforge.providers.azure.components.aks import kubernetes as k8s


def _result(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


@pytest.fixture(autouse=True)
def restore_context():
    original = vars(context).copy()
    original_client_cache = k8s._client_cache.copy()
    yield
    vars(context).clear()
    vars(context).update(original)
    k8s._client_cache.clear()
    k8s._client_cache.update(original_client_cache)


def test_api_client_uses_cache_populated_while_waiting_for_lock(monkeypatch):
    cached = MagicMock()

    class PopulatingLock:
        def __enter__(self):
            k8s._client_cache["ctx"] = cached

        def __exit__(self, *_args):
            return False

    k8s._client_cache.clear()
    monkeypatch.setattr(k8s, "_lock", PopulatingLock())

    assert k8s._get_api_client("ctx") is cached


def test_kubectl_fallback_reports_os_error(monkeypatch):
    monkeypatch.setattr(k8s, "dispatch_kubectl", MagicMock(return_value=None))
    monkeypatch.setattr(k8s.subprocess, "run", MagicMock(side_effect=OSError("not executable")))

    result = k8s.run_kubernetes_command(["version"], context="ctx")

    assert result.returncode == 126
    assert result.stderr == "Could not execute kubectl fallback: not executable"


def test_jsonpath_and_custom_columns_reject_partial_expressions():
    payload = {"items": [{"metadata": {"name": "pod"}}]}

    assert k8s._jsonpath_get('{range .items[*]}{.metadata.name}trailing{end}', payload) is None
    assert k8s._custom_columns_get("NAME:.metadata[name", payload["items"], False) is None
    assert k8s._apply_output(
        payload["items"],
        False,
        {"output": "jsonpath={.items[invalid]}", "no_headers": False},
    ) is None


def test_get_dispatches_remaining_namespaced_and_cluster_resources(monkeypatch):
    api = MagicMock()
    api.sanitize_for_serialization.side_effect = lambda value: value
    core = MagicMock()
    apps = MagicMock()
    admission = MagicMock()
    apps.list_namespaced_deployment.return_value = {"items": [{"metadata": {"name": "api"}}]}
    apps.read_namespaced_daemon_set.return_value = {"metadata": {"name": "agents"}}
    core.read_persistent_volume.return_value = {"metadata": {"name": "data"}}
    admission.read_mutating_webhook_configuration.return_value = {
        "metadata": {"name": "policy"}
    }
    monkeypatch.setattr(k8s, "_get_api_client", MagicMock(return_value=api))
    monkeypatch.setattr(k8s.client, "CoreV1Api", MagicMock(return_value=core))
    monkeypatch.setattr(k8s.client, "AppsV1Api", MagicMock(return_value=apps))
    monkeypatch.setattr(
        k8s.client, "AdmissionregistrationV1Api", MagicMock(return_value=admission)
    )

    deployment = k8s._dispatch_get("deployments", ["-n", "apps", "-o", "json"], "ctx")
    daemonset = k8s._dispatch_get("daemonset", ["agents", "-n", "system"], "ctx")
    volume = k8s._dispatch_get("pv", ["data", "-o", "json"], "ctx")
    webhook = k8s._dispatch_get("mutatingwebhookconfiguration", ["policy"], "ctx")

    assert json.loads(deployment.stdout)["items"][0]["metadata"]["name"] == "api"
    assert daemonset.returncode == volume.returncode == webhook.returncode == 0
    apps.list_namespaced_deployment.assert_called_once_with("apps", label_selector=None)
    apps.read_namespaced_daemon_set.assert_called_once_with("agents", "system")


@pytest.mark.parametrize(
    ("resource", "args"),
    [
        ("pods", []),
        ("daemonset", ["agents"]),
        ("daemonsets", []),
        ("endpoints", ["api"]),
        ("certificate", []),
        ("crd", ["widgets.example.com", "-o", "json"]),
        ("podchaos", []),
    ],
)
def test_get_requires_scope_or_supported_output(resource, args):
    assert k8s._dispatch_get(resource, args, "ctx") is None


def test_mutation_dispatchers_fall_back_on_unexpected_client_failures(monkeypatch, tmp_path):
    api = MagicMock()
    core = MagicMock()
    core.read_node.side_effect = RuntimeError("transport closed")
    monkeypatch.setattr(k8s, "_get_api_client", MagicMock(return_value=api))
    monkeypatch.setattr(k8s.client, "CoreV1Api", MagicMock(return_value=core))

    assert k8s._dispatch_taint(["nodes", "worker", "spot=true:NoSchedule"], "ctx") is None

    manifest = tmp_path / "pod.json"
    manifest.write_text('{"kind":"Pod","metadata":{"name":"p","namespace":"ns"}}')
    core.create_namespaced_pod.side_effect = RuntimeError("connection reset")
    assert k8s._dispatch_apply(["-f", str(manifest)], "ctx") is None

    core.patch_node.side_effect = RuntimeError("connection reset")
    assert k8s._dispatch_drain(
        ["worker", "--ignore-daemonsets", "--delete-emptydir-data", "--force"], "ctx"
    ) is None


def test_rollout_handles_unknown_subcommand_and_api_failures(monkeypatch):
    apps = MagicMock()
    monkeypatch.setattr(k8s, "_get_api_client", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(k8s.client, "AppsV1Api", MagicMock(return_value=apps))

    assert k8s._dispatch_rollout("pause", ["deployment/api", "-n", "apps"], "ctx") is None

    apps.read_namespaced_deployment.side_effect = k8s.ApiException(status=404)
    assert k8s._dispatch_rollout(
        "status", ["deployment/api", "-n", "apps"], "ctx"
    ).stderr == "not found"

    apps.read_namespaced_deployment.side_effect = RuntimeError("transport closed")
    assert k8s._dispatch_rollout("status", ["deployment/api", "-n", "apps"], "ctx") is None


def test_top_accepts_no_headers_but_requires_resource_scope(monkeypatch):
    custom = MagicMock()
    custom.list_namespaced_custom_object.return_value = {"items": []}
    monkeypatch.setattr(k8s, "_get_api_client", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(k8s.client, "CustomObjectsApi", MagicMock(return_value=custom))

    assert k8s._dispatch_top(["pods", "-n", "apps", "--no-headers"], "ctx").returncode == 0
    assert k8s._dispatch_top(["pods", "--no-headers"], "ctx") is None
    assert k8s._dispatch_top(["node", "--no-headers"], "ctx") is None


def test_discovery_falls_back_without_azure_cli_and_filters_blank_nodes(monkeypatch):
    service = discovery.AzureAKSDiscovery()
    monkeypatch.setattr(k8s, "list_kube_contexts", lambda: ["local", "arn:aws:eks:x", "gke_x"])
    monkeypatch.setattr(discovery.subprocess, "run", MagicMock(side_effect=OSError("missing")))

    assert service.list_contexts() == ["local"]

    monkeypatch.setattr(
        discovery,
        "_kubectl",
        MagicMock(return_value=_result("\nworker-a\t[]\n")),
    )
    assert service.list_nodes("ctx") == ["worker-a"]


def test_discovery_ownership_and_selector_best_effort_fallbacks(monkeypatch):
    service = discovery.AzureAKSDiscovery()
    pod = {"metadata": {"ownerReferences": [{"kind": "ReplicaSet", "name": "api-rs"}]}}
    replica_set_without_deployment = {"metadata": {"ownerReferences": [{"kind": "Job"}]}}
    monkeypatch.setattr(
        discovery, "_kubectl_json", MagicMock(side_effect=[pod, replica_set_without_deployment])
    )
    assert service.get_deployment_for_pod("ctx", "apps", "api-pod") is None

    deployment = {
        "spec": {
            "selector": {"matchLabels": {"app": "api"}},
            "template": {"metadata": {"labels": {"app": "api", "role": "frontend"}}},
        }
    }
    monkeypatch.setattr(
        discovery,
        "_kubectl_json",
        MagicMock(side_effect=[deployment, RuntimeError("replicasets unavailable")]),
    )
    assert service.get_safe_label_selector("ctx", "apps", "api") == {
        "app": "api",
        "role": "frontend",
    }


def test_platform_selects_azure_and_loads_resolved_cached_context(monkeypatch):
    selector = platform.PlatformSelector()
    cache = {
        "subscription_id": "Engineering",
        "account_name": "Account",
        "resource_group": "rg",
        "cluster_name": "aks",
        "location": "eastus",
        "kube_context": "aks-admin",
    }
    monkeypatch.setattr(platform, "prompt", MagicMock(return_value="2"))
    monkeypatch.setattr(platform, "title", MagicMock())
    monkeypatch.setattr(platform, "console", MagicMock())
    monkeypatch.setattr(platform, "_load_azure_cache", MagicMock(return_value=cache))
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.resolve_subscription_id",
        MagicMock(return_value="00000000-0000-0000-0000-000000000001"),
    )

    assert selector.select() == "azure"
    assert context.azure_subscription == "00000000-0000-0000-0000-000000000001"
    assert context.azure_resource_group == "rg"
    assert context.aks_kube_context == "aks-admin"


def test_platform_ignores_cached_context_when_subscription_cannot_be_resolved(monkeypatch):
    context.azure_subscription = "unchanged"
    monkeypatch.setattr(
        platform,
        "_load_azure_cache",
        MagicMock(return_value={
            "subscription_id": "missing",
            "resource_group": "rg",
            "cluster_name": "aks",
        }),
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.resolve_subscription_id",
        MagicMock(side_effect=RuntimeError("ambiguous")),
    )

    platform.PlatformSelector()._load_cached_azure_context()

    assert context.azure_subscription == "unchanged"


@pytest.mark.parametrize("choice", ["0", "m"])
def test_redis_menu_navigation(monkeypatch, choice):
    monkeypatch.setattr(redis_menu, "_ensure_azure_context", lambda: True)
    monkeypatch.setattr(redis_menu, "get_experiments", lambda _service: [])
    monkeypatch.setattr(redis_menu, "prompt", MagicMock(return_value=choice))
    monkeypatch.setattr(redis_menu, "console", MagicMock())
    monkeypatch.setattr(redis_menu, "section", MagicMock())

    if choice == "m":
        with pytest.raises(BackToMainMenu):
            redis_menu.redis_experiment_menu()
    else:
        assert redis_menu.redis_experiment_menu() is None


@pytest.mark.parametrize(
    ("method", "expected_message"),
    [
        ("list_resource_groups", "Could not discover Azure resource groups"),
        ("list_redis_caches", "Could not discover Azure Cache for Redis instances"),
    ],
)
def test_redis_discovery_errors_are_reported(monkeypatch, method, expected_message):
    client = MagicMock()
    getattr(client, method).side_effect = RuntimeError("Azure unavailable")
    monkeypatch.setattr(redis_menu, "AzureResourceDiscovery", MagicMock(return_value=client))
    monkeypatch.setattr(redis_menu, "error", MagicMock())
    monkeypatch.setattr(
        redis_menu,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Account",
        },
    )
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"

    result = (
        redis_menu._ensure_azure_context()
        if method == "list_resource_groups"
        else redis_menu._select_redis_cache()
    )

    assert not result
    assert expected_message in redis_menu.error.call_args.args[0]


def test_redis_empty_and_invalid_dynamic_selections(monkeypatch):
    client = MagicMock()
    client.list_resource_groups.return_value = []
    client.list_redis_caches.return_value = [{"id": "cache", "name": "orders"}]
    monkeypatch.setattr(redis_menu, "AzureResourceDiscovery", MagicMock(return_value=client))
    monkeypatch.setattr(redis_menu, "error", MagicMock())
    monkeypatch.setattr(redis_menu, "info", MagicMock())
    monkeypatch.setattr(redis_menu, "prompt", MagicMock(return_value="bad"))
    monkeypatch.setattr(
        redis_menu,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Account",
        },
    )

    assert redis_menu._ensure_azure_context() is False
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    assert redis_menu._select_redis_cache() is None

    client.list_redis_caches.return_value = []
    assert redis_menu._select_redis_cache() is None
    assert "No Azure Cache" in redis_menu.info.call_args.args[0]


def test_redis_menu_retries_invalid_experiment_then_aborts_failed_cache_selection(monkeypatch):
    metadata = {
        "name": "Flush",
        "inputs": [{"name": "cache", "type": "azure_redis_cache"}],
    }
    monkeypatch.setattr(redis_menu, "_ensure_azure_context", lambda: True)
    monkeypatch.setattr(redis_menu, "get_experiments", lambda _service: [metadata])
    monkeypatch.setattr(redis_menu, "prompt", MagicMock(side_effect=["bad", "1", "0"]))
    monkeypatch.setattr(redis_menu, "_select_redis_cache", MagicMock(return_value=None))
    monkeypatch.setattr(redis_menu, "build_experiment", MagicMock())
    monkeypatch.setattr(redis_menu, "error", MagicMock())
    monkeypatch.setattr(redis_menu, "console", MagicMock())
    monkeypatch.setattr(redis_menu, "section", MagicMock())

    redis_menu.redis_experiment_menu()

    redis_menu.error.assert_called_once_with("Invalid Selection")
    redis_menu.build_experiment.assert_not_called()
