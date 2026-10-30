from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.common.console_encoding import configure_windows_output
from chaosforge.interfaces.cli.interactive import azure_aks_service, input_engine
from chaosforge.interfaces.web import app as web_app
from chaosforge.providers.aws.discovery import AWSDiscovery
from chaosforge.providers.azure.components.aks.target_contract import (
    WORKLOAD_EXPERIMENTS,
    bind_workload_target_contract,
)


def test_windows_console_configuration_only_reconfigures_windows_streams():
    first = MagicMock()
    unsupported = MagicMock()
    unsupported.reconfigure.side_effect = AttributeError

    configure_windows_output([first, unsupported], windows="nt")
    configure_windows_output([first], windows="posix")

    first.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
    unsupported.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")


def test_aks_target_contract_leaves_non_workloads_and_bound_workloads_unchanged():
    non_workload = {"id": "aks-node-failure", "inputs": []}
    already_bound = {"id": next(iter(WORKLOAD_EXPERIMENTS)), "inputs": [{"name": "target_mode"}]}

    assert bind_workload_target_contract(non_workload) is non_workload
    assert bind_workload_target_contract(already_bound) is already_bound


def test_aks_target_contract_inserts_conditional_targets_after_namespace():
    experiment = {
        "id": next(iter(WORKLOAD_EXPERIMENTS)),
        "inputs": [
            {"name": "aks_context"},
            {"name": "namespace"},
            {"name": "deployment", "required": True},
        ],
    }

    bound = bind_workload_target_contract(experiment)

    assert [field["name"] for field in bound["inputs"]] == [
        "aks_context", "namespace", "target_mode", "deployment", "pod"
    ]
    assert bound["inputs"][3]["required"] is False
    assert bound["inputs"][4]["visible_when"] == {"target_mode": "pod"}


def test_aks_cli_skips_target_fields_that_do_not_match_target_mode(monkeypatch):
    discovery = MagicMock()
    monkeypatch.setattr(azure_aks_service, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(azure_aks_service, "title", lambda *_: None)
    monkeypatch.setattr(azure_aks_service, "_pick", lambda _title, _items: "apps")
    answers = iter(["pod", "api-1", "one", "n"])
    monkeypatch.setattr(azure_aks_service, "prompt", lambda *_: next(answers))

    # Select fields directly, avoiding discovery-only target handlers.
    result = azure_aks_service._collect_aks_inputs(
        {
            "name": "Conditional",
            "inputs": [
                {"name": "target_mode", "label": "Mode", "type": "text"},
                {"name": "deployment", "label": "Deployment", "visible_when": {"target_mode": "deployment"}},
                {"name": "pod", "label": "Pod", "visible_when": {"target_mode": "pod"}},
                {"name": "mode", "label": "Mode", "type": "text"},
            ],
        }
    )

    assert result == {
        "target_mode": "pod",
        "pod": "api-1",
        "mode": "one",
        "dry_run": "false",
    }


def test_input_engine_passes_pod_or_deployment_context_to_eks_container_selector(monkeypatch):
    selector = MagicMock()
    selector.select_child.return_value = {"name": "api"}
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", lambda *_: None)
    metadata = {
        "name": "Container",
        "inputs": [
            {
                "name": "namespace",
                "label": "Namespace",
                "type": "aws_resource",
                "resource_type": "eks-namespace",
            },
            {
                "name": "container_name",
                "label": "Container",
                "type": "aws_resource",
                "resource_type": "eks-container",
                "parent": "namespace",
            },
        ],
    }

    result = input_engine.collect_inputs(
        metadata,
        prefill={"eks_cluster": "cluster", "namespace": "apps", "pod": "api-1"},
    )

    assert result["container_name"] == "api"
    selector.select_child.assert_called_once_with(
        "eks-namespace", ("cluster", "apps", {"pod": "api-1", "deployment": ""}), "eks-container"
    )


def test_input_engine_pod_target_sets_context_and_single_pod_mode(monkeypatch):
    selector = MagicMock()
    selector.select_child.return_value = {"name": "api-1"}
    selector.discovery.get_eks_pod_context.return_value = {
        "labels": {"app": "api"},
        "owning_deployment": "orders",
    }
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", lambda *_: None)

    result = input_engine.collect_inputs(
        {
            "id": "chaos-mesh-pod-kill",
            "name": "Pod target",
            "inputs": [
                {"name": "namespace", "label": "Namespace", "type": "aws_resource", "resource_type": "eks-namespace"},
                {"name": "pod", "label": "Pod", "type": "aws_resource", "resource_type": "eks-pod", "parent": "namespace"},
                {"name": "mode", "label": "Mode"},
            ],
        },
        prefill={"eks_cluster": "cluster", "namespace": "apps"},
    )

    assert result["mode"] == "one"
    assert result["target_mode"] == "pod"
    assert result["labels"] == {"app": "api"}
    assert result["owning_deployment"] == "orders"


def test_input_engine_deployment_target_sets_labels_and_replica_count(monkeypatch):
    selector = MagicMock()
    selector.select_child.return_value = {"name": "orders", "replicas": 3}
    selector.discovery.get_eks_deployment_context.return_value = {"labels": {"app": "orders"}}
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", lambda *_: None)

    result = input_engine.collect_inputs(
        {
            "id": "chaos-mesh-pod-kill",
            "name": "Deployment target",
            "inputs": [
                {"name": "namespace", "label": "Namespace", "type": "aws_resource", "resource_type": "eks-namespace"},
                {"name": "deployment", "label": "Deployment", "type": "aws_resource", "resource_type": "eks-deployment", "parent": "namespace"},
            ],
        },
        prefill={"eks_cluster": "cluster", "namespace": "apps"},
    )

    assert result["labels"] == {"app": "orders"}
    assert result["owning_deployment"] == "orders"
    assert result["original_replicas"] == 3


def test_eks_container_discovery_uses_exact_pod_or_deployment_pods(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")
    discovery._configure_eks_kubernetes_client = MagicMock()
    discovery.k8s_core_api = MagicMock()
    discovery.k8s_apps_api = MagicMock()
    def pod(*names):
        return SimpleNamespace(
            spec=SimpleNamespace(containers=[SimpleNamespace(name=name) for name in names])
        )
    discovery.k8s_core_api.read_namespaced_pod.return_value = pod("sidecar", "app")
    discovery.k8s_apps_api.read_namespaced_deployment.return_value = SimpleNamespace(
        spec=SimpleNamespace(selector=SimpleNamespace(match_labels={"app": "orders"}))
    )
    discovery.k8s_core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[pod("app", "metrics")])

    assert discovery.list_eks_containers("cluster", "apps", pod_name="pod-1") == [
        {"name": "app"}, {"name": "sidecar"}
    ]
    assert discovery.list_eks_containers("cluster", "apps", deployment="orders") == [
        {"name": "app"}, {"name": "metrics"}
    ]
    discovery.k8s_core_api.list_namespaced_pod.assert_called_once_with(
        namespace="apps", label_selector="app=orders"
    )


def test_eks_context_methods_cover_direct_and_replicaset_owners():
    discovery = AWSDiscovery("eu-central-1")
    discovery._configure_eks_kubernetes_client = MagicMock()
    discovery.k8s_core_api = MagicMock()
    discovery.k8s_apps_api = MagicMock()
    direct = SimpleNamespace(
        metadata=SimpleNamespace(
            labels=None,
            owner_references=[SimpleNamespace(controller=True, kind="Deployment", name="orders")],
        )
    )
    replica_set = SimpleNamespace(
        metadata=SimpleNamespace(
            labels={"app": "api"},
            owner_references=[SimpleNamespace(controller=True, kind="ReplicaSet", name="orders-abc")],
        )
    )
    discovery.k8s_core_api.read_namespaced_pod.side_effect = [direct, replica_set]
    discovery.k8s_apps_api.read_namespaced_replica_set.return_value = SimpleNamespace(
        metadata=SimpleNamespace(
            owner_references=[SimpleNamespace(controller=True, kind="Deployment", name="orders")]
        )
    )
    discovery.k8s_apps_api.read_namespaced_deployment.return_value = SimpleNamespace(
        spec=SimpleNamespace(selector=SimpleNamespace(match_labels=None))
    )

    assert discovery.get_eks_pod_context("cluster", "apps", "direct") == {
        "labels": {}, "owning_deployment": "orders"
    }
    assert discovery.get_eks_pod_context("cluster", "apps", "replica") == {
        "labels": {"app": "api"}, "owning_deployment": "orders"
    }
    assert discovery.get_eks_deployment_context("cluster", "apps", "orders") == {"labels": {}}


@pytest.fixture
def web_client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


def test_aks_pod_resource_api_and_post_normalize_single_pod(web_client, monkeypatch):
    discovery = MagicMock()
    discovery.list_pods.return_value = ["api-1"]
    discovery.get_pod_label.return_value = ("app", "api")
    discovery.get_deployment_for_pod.return_value = "orders"
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_: {"authenticated": True, "subscription_id": "sub"})
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: SimpleNamespace(campaign_id="campaign-1"))

    assert web_client.get(
        "/api/azure/aks/resources/azure_aks_pod?context=cluster&namespace=apps"
    ).get_json() == [{"id": "api-1", "name": "api-1"}]

    response = web_client.post(
        "/experiment/aks/aks-pod-kill",
        data={"resource_group": "rg", "aks_context": "cluster", "namespace": "apps", "target_mode": "pod", "pod": "api-1"},
    )

    assert response.status_code == 302
    values = add.call_args.args[2]
    assert values["deployment"] == "api-1"
    assert values["owning_deployment"] == "orders"
    assert (values["chaos_mode"], values["chaos_value"]) == ("one", "")
    discovery.get_label_selector.assert_not_called()


@pytest.mark.parametrize(
    ("target_mode", "target", "expected"),
    [
        ("pod", "api-1", {"mode": "one", "labels": {"app": "api"}, "owning_deployment": "orders"}),
        ("deployment", "orders", {"labels": {"app": "orders"}, "owning_deployment": "orders"}),
    ],
)
def test_chaos_mesh_post_binds_eks_target_context(web_client, monkeypatch, target_mode, target, expected):
    discovery = MagicMock()
    discovery.get_eks_pod_context.return_value = {
        "labels": {"app": "api"}, "owning_deployment": "orders"
    }
    discovery.get_eks_deployment_context.return_value = {"labels": {"app": "orders"}}
    add = MagicMock()
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: SimpleNamespace(campaign_id="campaign-1"))
    monkeypatch.setattr(
        web_app,
        "load_metadata",
        lambda _service: {
            "service": "chaos_mesh",
            "experiments": [{
                "id": "chaos-mesh-pod-kill",
                "name": "Pod Kill",
                "inputs": [
                    {"name": "aws_region", "label": "Region", "type": "aws_region", "default": "eu-central-1"},
                    {"name": "eks_cluster", "label": "Cluster", "required": True},
                    {"name": "namespace", "label": "Namespace", "required": True},
                    {"name": "target_mode", "label": "Target mode", "required": True},
                    {"name": "pod", "label": "Pod", "visible_when": {"target_mode": "pod"}, "required": True},
                    {"name": "deployment", "label": "Deployment", "visible_when": {"target_mode": "deployment"}, "required": True},
                ],
            }],
        },
    )
    data = {
        "eks_cluster": "cluster",
        "namespace": "apps",
        "target_mode": target_mode,
        target_mode: target,
    }

    response = web_client.post("/experiment/chaos_mesh/chaos-mesh-pod-kill", data=data)

    assert response.status_code == 302
    values = add.call_args.args[2]
    for key, value in expected.items():
        assert values[key] == value


def test_aks_discovery_endpoint_wrappers_and_invalid_resource_type(web_client, monkeypatch):
    discovery = MagicMock()
    discovery.list_contexts.return_value = ["cluster"]
    discovery.list_namespaces.return_value = ["apps"]
    discovery.list_deployments.return_value = ["orders"]
    discovery.list_nodes.return_value = ["node-1"]
    discovery.list_zones.return_value = ["1"]
    discovery.list_containers.return_value = ["api"]
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))

    assert web_client.get("/api/azure/aks/contexts").get_json() == [{"id": "cluster", "name": "cluster"}]
    assert web_client.get("/api/azure/aks/namespaces/cluster").get_json() == [{"id": "apps", "name": "apps"}]
    assert web_client.get("/api/azure/aks/deployments/cluster/apps").get_json() == [{"id": "orders", "name": "orders"}]
    assert web_client.get("/api/azure/aks/nodes/cluster").get_json() == [{"id": "node-1", "name": "node-1"}]
    assert web_client.get("/api/azure/aks/zones/cluster").get_json() == [{"id": "1", "name": "1"}]
    assert web_client.get("/api/azure/aks/containers/cluster/apps/orders").get_json() == [{"id": "api", "name": "api"}]
    invalid = web_client.get("/api/azure/aks/resources/unknown")
    assert invalid.status_code == 400
    assert invalid.get_json() == {"error": "Unsupported AKS resource type"}
