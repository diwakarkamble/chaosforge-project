from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)
from chaosforge.interfaces.cli.interactive import input_engine
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.aws.discovery import AWSDiscovery
from chaosforge.providers.azure.discovery import AzureResourceDiscovery


def test_workload_input_modes_and_chaos_value_validation(monkeypatch):
    context.region = "eu-west-1"
    monkeypatch.setattr(input_engine, "title", lambda _name: None)
    monkeypatch.setattr(input_engine, "menu", lambda *_args: None)
    errors = []
    monkeypatch.setattr(input_engine, "error", errors.append)
    monkeypatch.setattr(
        input_engine,
        "get_input",
        MagicMock(side_effect=["x", "1", "9", "3", "0", "2"]),
    )
    monkeypatch.setattr(input_engine.Validator, "validate", lambda *_args: (True, ""))

    result = input_engine.collect_inputs(
        {
            "id": "chaos-mesh-pod-kill",
            "name": "Pod Kill",
            "inputs": [
                {"name": "target_mode", "label": "Target mode"},
                {"name": "mode", "label": "Mode"},
                {"name": "chaos_value", "label": "Value"},
            ],
        }
    )

    assert result["target_mode"] == "deployment"
    assert result["mode"] == "fixed"
    assert result["chaos_value"] == "2"
    assert errors == [
        "Invalid Selection",
        "Invalid Selection",
        "Mode Value must be at least 1 for fixed mode.",
    ]


def test_workload_pod_mode_auto_sets_one_and_skips_unused_chaos_value(monkeypatch):
    context.region = "eu-west-1"
    monkeypatch.setattr(input_engine, "title", lambda _name: None)
    monkeypatch.setattr(input_engine, "menu", lambda *_args: None)
    monkeypatch.setattr(input_engine, "get_input", lambda _prompt: "2")

    result = input_engine.collect_inputs(
        {
            "id": "chaos-mesh-pod-kill",
            "name": "Pod Kill",
            "inputs": [
                {"name": "target_mode", "label": "Target mode"},
                {"name": "mode", "label": "Mode"},
                {"name": "chaos_value", "label": "Value"},
            ],
        }
    )

    assert result["target_mode"] == "pod"
    assert result["mode"] == "one"
    assert "chaos_value" not in result


def test_eks_context_helpers_resolve_direct_and_replicaset_owners(monkeypatch):
    discovery = AWSDiscovery("eu-west-1")
    monkeypatch.setattr(discovery, "_configure_eks_kubernetes_client", lambda _cluster: None)
    discovery.k8s_core_api = MagicMock()
    discovery.k8s_apps_api = MagicMock()
    discovery.k8s_core_api.read_namespaced_pod.return_value = SimpleNamespace(
        metadata=SimpleNamespace(
            labels={"app": "api"},
            owner_references=[SimpleNamespace(controller=True, kind="ReplicaSet", name="api-rs")],
        )
    )
    discovery.k8s_apps_api.read_namespaced_replica_set.return_value = SimpleNamespace(
        metadata=SimpleNamespace(
            owner_references=[SimpleNamespace(controller=True, kind="Deployment", name="api")]
        )
    )
    discovery.k8s_apps_api.read_namespaced_deployment.return_value = SimpleNamespace(
        spec=SimpleNamespace(selector=SimpleNamespace(match_labels={"app": "api"}))
    )

    assert discovery.get_eks_pod_context("cluster", "apps", "api-1") == {
        "labels": {"app": "api"},
        "owning_deployment": "api",
    }
    assert discovery.get_eks_deployment_context("cluster", "apps", "api") == {
        "labels": {"app": "api"}
    }


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (SimpleNamespace(returncode=1, stderr="forbidden", stdout=""), "forbidden"),
        (SimpleNamespace(returncode=0, stderr="", stdout="{}"), "invalid AKS cluster list"),
    ],
)
def test_azure_aks_cluster_discovery_rejects_cli_failures(monkeypatch, result, message):
    discovery = AzureResourceDiscovery("00000000-0000-0000-0000-000000000000")
    monkeypatch.setattr("chaosforge.providers.azure.discovery.subprocess.run", lambda *_a, **_k: result)

    with pytest.raises(RuntimeError, match=message):
        discovery.list_aks_cluster_names("rg")


def test_mapper_normalizes_scalar_clock_and_ignores_empty_reorder(tmp_path):
    definition = tmp_path / "time.json"
    definition.write_text(
        '{"chaos_mesh":{"kind":"TimeChaos","action":"time"},"configuration":{"clock":"CLOCK_REALTIME","offset":"1m"}}',
        encoding="utf-8",
    )
    manifest = ChaosMeshExperimentMapper().build_manifest(
        SimpleNamespace(id="time", json_file=str(definition), variables={})
    )
    assert manifest["spec"]["clockIds"] == ["CLOCK_REALTIME"]

    reorder = tmp_path / "reorder.json"
    reorder.write_text(
        '{"chaos_mesh":{"kind":"NetworkChaos","action":"reorder"},"configuration":{"reorder":{}}}',
        encoding="utf-8",
    )
    manifest = ChaosMeshExperimentMapper().build_manifest(
        SimpleNamespace(id="reorder", json_file=str(reorder), variables={})
    )
    assert manifest["spec"]["action"] == "netem"
    assert "delay" not in manifest["spec"]
