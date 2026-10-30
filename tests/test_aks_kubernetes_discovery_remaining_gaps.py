import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.providers.azure.components.aks import discovery
from chaosforge.providers.azure.components.aks import kubernetes as k8s


def _result(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def test_kubernetes_fallback_prefixes_options_and_handles_parser_edges(monkeypatch):
    monkeypatch.setattr(k8s, "dispatch_kubectl", lambda *_: None)
    run = MagicMock(return_value=_result("ok"))
    monkeypatch.setattr(k8s.subprocess, "run", run)

    assert k8s.run_kubernetes_command(
        ["get", "pods"], "ctx", request_timeout="10s", prefix_options=True
    ).stdout == "ok"
    assert k8s.run_kubernetes_command(
        ["get", "pods"], "ctx", request_timeout="10s"
    ).stdout == "ok"
    assert run.call_args_list[0].args[0] == [
        "kubectl", "--request-timeout=10s", "--context", "ctx", "get", "pods"
    ]
    assert run.call_args_list[1].args[0] == [
        "kubectl", "get", "pods", "--request-timeout=10s", "--context", "ctx"
    ]
    assert k8s._resolve_path_steps(".") == []
    assert k8s._apply_index([[{"name": "api"}]], '?(@.name=="worker")') == []


@pytest.mark.parametrize(
    ("resource", "args"),
    [
        ("pods", ["api"]),
        ("pods", []),
        ("deployment", ["api"]),
        ("deployment", []),
        ("daemonset", ["agents"]),
        ("daemonset", []),
        ("replicaset", []),
        ("service", ["api"]),
        ("service", []),
        ("endpoints", ["api"]),
        ("pdb", []),
        ("certificate", []),
        ("events", []),
        ("crd", ["widgets", "-o", "json"]),
        ("podchaos", ["fault"]),
        ("podchaos", []),
    ],
)
def test_get_dispatcher_rejects_unscoped_resource_shapes(resource, args):
    assert k8s._dispatch_get(resource, args, "ctx") is None


@pytest.mark.parametrize(
    ("resource", "args"),
    [
        ("pods", ["-o", "json"]),
        ("deployment", ["-o", "json"]),
        ("daemonset", ["-o", "json"]),
        ("daemonset", ["agents"]),
        ("daemonset", ["agents", "-o", "json"]),
        ("service", ["-o", "json"]),
        ("endpoints", ["api"]),
        ("certificate", ["-o", "json"]),
        ("events", ["-o", "json"]),
        ("podchaos", ["-o", "json"]),
        ("podchaos", ["fault"]),
    ],
)
def test_get_dispatcher_rejects_namespace_required_resource_without_namespace(monkeypatch, resource, args):
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: MagicMock())

    assert k8s._dispatch_get(resource, args, "ctx") is None


def test_get_dispatcher_rejects_crd_with_output_after_api_client_setup(monkeypatch):
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: MagicMock())
    monkeypatch.setattr(k8s.client, "CoreV1Api", MagicMock())

    assert k8s._dispatch_get("crd", ["widgets", "-o", "json"], "ctx") is None


def test_get_dispatcher_reads_named_pod(monkeypatch):
    api = MagicMock()
    api.sanitize_for_serialization.return_value = {"metadata": {"name": "api"}}
    core = MagicMock()
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: api)
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda _: core)

    result = k8s._dispatch_get("pod", ["api", "-n", "apps", "-o", "json"], "ctx")

    assert json.loads(result.stdout) == {"metadata": {"name": "api"}}
    core.read_namespaced_pod.assert_called_once_with("api", "apps")


def test_mutation_dispatcher_remaining_guards_and_errors(monkeypatch):
    assert k8s._dispatch_delete("pod", ["-n", "apps"], "ctx") is None
    assert k8s._dispatch_patch("node", ["worker", "extra"], "ctx") is None
    assert k8s._dispatch_patch("node", ["worker", "-p=[]"], "ctx") is None
    assert k8s._dispatch_patch("deployment", ["api", "--type=json", "-p=[]"], "ctx") is None
    assert k8s._dispatch_label("namespace", ["apps", "a=b", "--overwrite", "c=d"], "ctx") is None
    assert k8s._dispatch_taint(["nodes", "worker"], "ctx") is None

    core = MagicMock()
    core.patch_namespace.side_effect = k8s.ApiException(status=500, reason="denied")
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: MagicMock())
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda _: core)
    assert k8s._dispatch_label("namespace", ["apps", "a=b"], "ctx").stderr == "denied"
    core.read_node.side_effect = RuntimeError("offline")
    assert k8s._dispatch_taint(["nodes", "worker", "spot:NoSchedule"], "ctx") is None
    core.patch_node.side_effect = k8s.ApiException(status=404)
    assert k8s._dispatch_cordon(False, ["worker"], "ctx").stderr == "not found"


def test_rollout_and_apply_remaining_error_paths(monkeypatch, tmp_path):
    apps = MagicMock()
    apps.patch_namespaced_deployment.side_effect = k8s.ApiException(status=500, reason="denied")
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: MagicMock())
    monkeypatch.setattr(k8s.client, "AppsV1Api", lambda _: apps)
    assert k8s._dispatch_rollout("restart", ["deployment/api", "-n", "apps"], "ctx").stderr == "denied"
    assert k8s._dispatch_rollout("restart", ["deployment/api", "-n", "apps", "--timeout=bad"], "ctx").stderr == "denied"
    assert k8s._dispatch_rollout("restart", ["deployment/api", "-n", "apps", "--watch"], "ctx") is None

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"kind": "Pod", "metadata": {"name": "api"}}')
    assert k8s._dispatch_apply(["-f", str(invalid)], "ctx") is None
    pod = tmp_path / "pod.json"
    pod.write_text('{"kind": "Pod", "metadata": {"name": "api", "namespace": "apps"}}')
    core = MagicMock()
    core.create_namespaced_pod.side_effect = k8s.ApiException(status=403, reason="forbidden")
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda _: core)
    assert k8s._dispatch_apply(["-f", str(pod)], "ctx").stderr == "forbidden"


def test_drain_reports_api_errors_and_waits_for_transient_pods(monkeypatch):
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="api", namespace="apps", owner_references=[]),
        status=SimpleNamespace(phase="Running"),
    )
    core = MagicMock()
    evict_pod = k8s._drain_evict_pod
    core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[pod])
    core.read_namespaced_pod.side_effect = [None, k8s.ApiException(status=404)]
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: MagicMock())
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda _: core)
    monkeypatch.setattr(k8s, "_drain_evict_pod", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("time.monotonic", lambda: 0)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    assert k8s._dispatch_drain(
        ["worker", "--ignore-daemonsets", "--delete-emptydir-data", "--force"], "ctx"
    ).returncode == 0

    core.patch_node.side_effect = k8s.ApiException(status=500, reason="cordon denied")
    assert k8s._dispatch_drain(
        ["worker", "--ignore-daemonsets", "--delete-emptydir-data", "--force"], "ctx"
    ).stderr == "cordon denied"
    core.create_namespaced_pod_eviction.side_effect = k8s.ApiException(status=500, reason="eviction denied")
    assert evict_pod(core, pod, None) == (False, "eviction denied")


def test_drain_retries_pods_that_remain_after_a_non_not_found_read_error(monkeypatch):
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="api", namespace="apps", owner_references=[]),
        status=SimpleNamespace(phase="Running"),
    )
    core = MagicMock()
    core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[pod])
    core.read_namespaced_pod.side_effect = [
        k8s.ApiException(status=500, reason="temporarily unavailable"),
        k8s.ApiException(status=404),
    ]
    monkeypatch.setattr(k8s, "_get_api_client", lambda _: MagicMock())
    monkeypatch.setattr(k8s.client, "CoreV1Api", lambda _: core)
    monkeypatch.setattr(k8s, "_drain_evict_pod", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr("time.monotonic", lambda: 0)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    result = k8s._dispatch_drain(
        ["worker", "--ignore-daemonsets", "--delete-emptydir-data", "--force"], "ctx"
    )

    assert result.returncode == 0
    assert core.read_namespaced_pod.call_count == 2


def test_discovery_remaining_blank_and_selector_paths(monkeypatch):
    service = discovery.AzureAKSDiscovery()
    monkeypatch.setattr(discovery, "_kubectl", lambda *_args, **_kwargs: _result("\n\t\nworker\t\n"))
    assert service.list_nodes("ctx") == ["worker"]

    deployment = {
        "spec": {"selector": {"matchLabels": {"app": "api"}}},
        "metadata": {"labels": {}},
    }
    replica_sets = {
        "items": [
            {"metadata": {"name": "other"}, "spec": {"replicas": 1}},
            {
                "metadata": {
                    "name": "api-old",
                    "creationTimestamp": "2025-01-01T00:00:00Z",
                    "ownerReferences": [{"kind": "Deployment", "name": "api"}],
                    "labels": {},
                },
                "spec": {"replicas": 0},
            },
        ]
    }
    kubectl_json = MagicMock(side_effect=[deployment, replica_sets])
    monkeypatch.setattr(discovery, "_kubectl_json", kubectl_json)
    assert service.get_safe_label_selector("ctx", "apps", "api") == {"app": "api"}


def test_discovery_skips_blank_node_rows_between_workers(monkeypatch):
    service = discovery.AzureAKSDiscovery()
    monkeypatch.setattr(
        discovery,
        "_kubectl",
        lambda *_args, **_kwargs: _result("worker-a\t[]\n\nworker-b\t[]\n"),
    )

    assert service.list_nodes("ctx") == ["worker-a", "worker-b"]


def test_discovery_ownership_handles_empty_and_unresolvable_payloads(monkeypatch):
    service = discovery.AzureAKSDiscovery()
    monkeypatch.setattr(discovery, "_kubectl", lambda *_args, **_kwargs: _result("\t\nworker\t"))
    assert service.list_nodes("ctx") == ["worker"]

    monkeypatch.setattr(discovery, "_kubectl_json", lambda *_args, **_kwargs: {})
    assert service.get_owned_pod_names("ctx", "apps", "api") == []

    pod = {"metadata": {"ownerReferences": [{"kind": "ReplicaSet", "name": "api-rs"}]}}
    monkeypatch.setattr(discovery, "_kubectl_json", MagicMock(side_effect=[pod, {}]))
    assert service.get_deployment_for_pod("ctx", "apps", "api-pod") is None
