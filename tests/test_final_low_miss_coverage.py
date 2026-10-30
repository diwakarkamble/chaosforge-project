from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import ChaosMeshExperimentMapper
from chaosforge.engines.chaos_mesh.chaos_mesh_runner import ChaosMeshRunner
from chaosforge.engines.chaos_mesh.chaos_mesh_target_resolver import ChaosMeshTargetResolver
from chaosforge.engines.chaos_mesh.target_contract import bind_workload_target_contract
from chaosforge.interfaces.cli.interactive import input_engine
from chaosforge.interfaces.web.forms import normalize_values
from chaosforge.lifecycle.checks.aws_adapters import APIGatewayStageAdapter
from chaosforge.lifecycle.checks.kubernetes_chaos import SharedChaosMeshValidationCheck
from chaosforge.lifecycle.lifecycle_runner import LifecycleRunner
from chaosforge.providers.aws.discovery import AWSDiscovery
from chaosforge.providers.azure.discovery import AzureResourceDiscovery


def test_api_gateway_stage_requires_api_and_stage():
    with pytest.raises(ValueError, match="API Gateway and Stage"):
        APIGatewayStageAdapter().capture({"aws_region": "eu-west-1"})


def test_kubernetes_check_stops_validation_session_after_failed_precheck(monkeypatch):
    check = SharedChaosMeshValidationCheck(MagicMock(), SimpleNamespace(id="chaos-mesh-pod-kill"))
    check.validation_id = "aks-pod-kill"
    session = MagicMock()
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.validation_logger.ValidationSession",
        MagicMock(return_value=session),
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.build_pre_validation_checks",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.run_validation_checks",
        lambda *_args, **_kwargs: {"passed": False, "checks": {"ready": {"passed": False}}},
    )

    with pytest.raises(RuntimeError, match="ready"):
        check.capture({"eks_cluster": "cluster", "namespace": "apps", "pod": "api"})

    session.stop.assert_called_once_with()
    assert check.validation_session is None


def test_kubernetes_check_marks_deleted_eks_pod_in_runtime_sample(monkeypatch):
    check = SharedChaosMeshValidationCheck(MagicMock(), SimpleNamespace(id="chaos-mesh-pod-kill"))
    check.validation_id = "aks-pod-kill"
    check.runtime_validation = {"samples": [], "fault_observed": False, "passed": False}
    check.discovery.eks_pod_exists.return_value = False
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.observe_fault",
        lambda *_args, **_kwargs: {"severity": "INFO"},
    )

    sample = check.observe_during(
        {"eks_cluster": "cluster", "namespace": "apps", "pod": "api"},
        {},
        {"status": {}},
    )

    assert sample["pod_deleted"] is True
    assert check.runtime_validation["passed"] is True


def test_runner_uses_eks_discovery_client_for_eks_workloads():
    discovery = MagicMock(k8s_custom_api="custom", k8s_api_client="api")
    client = MagicMock()
    mapper = MagicMock()
    mapper.build_manifest.return_value = {"kind": "PodChaos", "metadata": {"name": "fault"}}
    client.create.return_value = {"status": {"experiment": {"desiredPhase": "Finished"}}}
    runner = ChaosMeshRunner(client=client, mapper=mapper, discovery=discovery)

    runner.execute(SimpleNamespace(variables={"eks_cluster": "cluster", "wait_for_completion": False}))

    discovery._configure_eks_kubernetes_client.assert_called_once_with("cluster")
    assert client.custom_objects_api == "custom"
    assert client._api_client == "api"


def test_target_contract_creates_missing_pod_field():
    experiment = {
        "id": "chaos-mesh-pod-kill",
        "inputs": [{"name": "namespace", "label": "Namespace", "type": "text"}],
    }

    result = bind_workload_target_contract(experiment)

    assert next(field for field in result["inputs"] if field["name"] == "pod")["resource_type"] == "eks-pod"


def test_input_engine_skips_hidden_field_and_reprompts_invalid_chaos_values(monkeypatch):
    answers = iter(["invalid", "0", "101", "25"])
    messages = []
    monkeypatch.setattr(input_engine, "get_input", lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(input_engine, "error", messages.append)
    monkeypatch.setattr(input_engine, "title", lambda *_args: None)

    result = input_engine.collect_inputs(
        {
            "name": "Mode",
            "inputs": [
                {"name": "hidden", "label": "Hidden", "visible_when": {"mode": "other"}},
                {"name": "chaos_value", "label": "Value", "type": "text"},
            ],
        },
        prefill={"mode": "fixed-percent"},
    )

    assert result["chaos_value"] == "25"
    assert any("whole number" in message for message in messages)
    assert any("between 1 and 100" in message for message in messages)


@pytest.mark.parametrize(
    ("mode", "value", "message"),
    [("fixed", "zero", "whole number"), ("fixed", "0", "at least 1")],
)
def test_web_forms_reject_invalid_fixed_chaos_values(mode, value, message):
    _, errors = normalize_values(
        [
            {"name": "chaos_mode", "type": "text", "required": False},
            {"name": "chaos_value", "type": "text", "required": False},
        ],
        {"chaos_mode": mode, "chaos_value": value},
    )

    assert message in errors["chaos_value"]


def test_aws_discovery_reports_missing_pod_and_reraises_other_api_errors(monkeypatch):
    discovery = AWSDiscovery("eu-west-1")
    discovery._configure_eks_kubernetes_client = MagicMock()
    from kubernetes.client.exceptions import ApiException

    missing = ApiException(status=404)
    discovery.k8s_core_api = MagicMock()
    discovery.k8s_core_api.read_namespaced_pod.side_effect = missing
    assert discovery.eks_pod_exists("cluster", "apps", "api") is False

    denied = ApiException(status=403)
    discovery.k8s_core_api.read_namespaced_pod.side_effect = denied
    with pytest.raises(ApiException) as error:
        discovery.eks_pod_exists("cluster", "apps", "api")
    assert error.value is denied
    discovery.k8s_core_api.read_namespaced_pod.side_effect = None
    assert discovery.eks_pod_exists("cluster", "apps", "api") is True


@pytest.mark.parametrize("side_effect", [FileNotFoundError(), __import__("subprocess").SubprocessError()])
def test_azure_discovery_translates_aks_cli_errors(monkeypatch, side_effect):
    discovery = AzureResourceDiscovery("subscription")
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.subprocess.run",
        MagicMock(side_effect=side_effect),
    )

    with pytest.raises(RuntimeError, match="Could not load AKS clusters"):
        discovery.list_aks_cluster_names("group")


def test_azure_discovery_rejects_invalid_aks_cli_json(monkeypatch):
    discovery = AzureResourceDiscovery("subscription")
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )
    with pytest.raises(RuntimeError, match="invalid AKS cluster list"):
        discovery.list_aks_cluster_names("group")


def test_target_resolver_reads_deployment_selector():
    discovery = MagicMock()
    discovery.list_eks_namespaces.return_value = [{"name": "apps"}]
    discovery.list_eks_deployments.return_value = [{"name": "api"}]
    discovery.k8s_apps_api.read_namespaced_deployment.return_value = SimpleNamespace(
        spec=SimpleNamespace(selector=SimpleNamespace(match_labels={"app": "api"}))
    )
    resolver = ChaosMeshTargetResolver(discovery)
    assert resolver.deployment_selector("cluster", "apps", "api") == {"app": "api"}


@pytest.mark.parametrize("action, key", [("loss", "loss"), ("duplicate", "duplicate"), ("corrupt", "corrupt")])
def test_mapper_adds_network_correlation_to_scalar_faults(tmp_path, action, key):
    path = tmp_path / f"{action}.json"
    path.write_text(
        f'{{"chaos_mesh":{{"kind":"NetworkChaos","action":"{action}"}},"configuration":{{"{key}":"5","correlation":25}}}}',
        encoding="utf-8",
    )
    manifest = ChaosMeshExperimentMapper().build_manifest(
        SimpleNamespace(id=action, json_file=str(path), variables={})
    )
    assert manifest["spec"][key]["correlation"] == "25"


def test_lifecycle_runner_builds_eks_pod_context(monkeypatch):
    discovery = MagicMock()
    discovery.get_eks_pod_context.return_value = {"label_key": "app", "label_value": "api"}
    monkeypatch.setattr("chaosforge.providers.aws.discovery.AWSDiscovery", MagicMock(return_value=discovery))
    runner = LifecycleRunner(MagicMock(), MagicMock())
    experiment = SimpleNamespace(
        id="chaos-mesh-pod-kill",
        variables={"eks_cluster": "cluster", "namespace": "apps", "pod": "api"},
    )

    target = runner._build_target(experiment)

    assert target["target_mode"] == "pod"
    assert experiment.variables["label_key"] == "app"
