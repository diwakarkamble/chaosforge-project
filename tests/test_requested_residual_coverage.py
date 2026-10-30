"""Residual coverage for CLI, lifecycle, validation, and Chaos Mesh helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.application.campaigns import manager
from chaosforge.application.services import registry
from chaosforge.application.validation.input import Validator
from chaosforge.application.validation.yaml import YAMLValidationError, YAMLValidator
from chaosforge.engines.chaos_mesh.chaos_mesh_manifest_builder import (
    ChaosMeshManifestBuilder,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_target_resolver import (
    ChaosMeshTargetResolver,
)
from chaosforge.interfaces.cli import main as cli
from chaosforge.lifecycle.checks import kubernetes_chaos
from chaosforge.lifecycle.lifecycle_runner import LifecycleRunner
from chaosforge.models.execution import ExecutionContext


def test_cli_schema_failure_and_missing_region(monkeypatch, capsys):
    report_error = MagicMock()
    monkeypatch.setattr(cli, "error", report_error)
    monkeypatch.setattr(cli, "load_yaml", lambda _path: {})
    monkeypatch.setattr(
        cli,
        "YAMLValidator",
        lambda: SimpleNamespace(
            validate=lambda _data: {"valid": False, "errors": ["bad schema"]}
        ),
    )

    assert cli.load_and_validate_yaml_campaign("bad.yaml") is None
    assert "bad schema" in capsys.readouterr().out

    campaign = SimpleNamespace(experiments=[])
    monkeypatch.setattr(
        cli,
        "YAMLValidator",
        lambda: SimpleNamespace(validate=lambda _data: {"valid": True}),
    )
    monkeypatch.setattr(cli, "build_campaign", lambda _data: campaign)
    monkeypatch.setattr(
        cli,
        "ExperimentValidationService",
        lambda: SimpleNamespace(
            validate_campaign=lambda _campaign: {"valid": True, "experiments": []}
        ),
    )

    assert cli.load_and_validate_yaml_campaign("no-region.yaml") is None
    assert "No aws_region" in capsys.readouterr().out


def test_cli_import_read_error_and_export_default_name(monkeypatch, tmp_path):
    source = tmp_path / "campaign.yaml"
    source.write_text("campaign: test", encoding="utf-8")
    read_bytes = cli.Path.read_bytes
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value=str(source)))
    monkeypatch.setattr(cli, "pause", MagicMock())
    monkeypatch.setattr(cli, "error", MagicMock())
    monkeypatch.setattr(cli.context, "cloud", "aws")
    monkeypatch.setattr(cli.context, "region", "eu-west-1")
    monkeypatch.setattr(
        cli,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "label": "AWS", "name": "Test"}),
    )
    monkeypatch.setattr(cli.Path, "read_bytes", MagicMock(side_effect=OSError("denied")))

    cli.import_yaml_campaign()

    cli.error.assert_called_with("Failed to read YAML campaign: denied")
    monkeypatch.setattr(cli.Path, "read_bytes", read_bytes)

    experiment = SimpleNamespace()
    monkeypatch.setattr(cli.campaign, "name", "My unsafe / campaign")
    monkeypatch.setattr(cli.campaign, "experiments", [experiment])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value=""))
    monkeypatch.setattr(cli, "success", MagicMock())
    monkeypatch.setattr(
        cli.campaign_yaml_service, "export_bytes", MagicMock(return_value=b"campaign: ok\n")
    )

    path = cli.export_campaign_yaml()

    assert path == cli.Path("My-unsafe-campaign.yaml")
    assert (tmp_path / path).read_bytes() == b"campaign: ok\n"


def test_cli_execute_and_plan_residual_returns(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", MagicMock(return_value=None))
    assert cli.execute_yaml_campaign("invalid.yaml") == 1

    campaign = SimpleNamespace()
    monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", MagicMock(return_value=campaign))
    monkeypatch.setattr(
        cli,
        "PlanService",
        lambda: SimpleNamespace(plan_campaign=lambda _campaign: SimpleNamespace(executable=False)),
    )
    monkeypatch.setattr(cli, "error", MagicMock())
    assert cli.execute_yaml_campaign("blocked.yaml") == 1

    plan = SimpleNamespace(executable=True)
    monkeypatch.setattr(
        cli, "PlanService", lambda: SimpleNamespace(plan_campaign=lambda _campaign: plan)
    )
    monkeypatch.setattr(cli, "display_campaign_plan", MagicMock())
    execute = MagicMock()
    monkeypatch.setattr(cli, "execute_lifecycle_campaign", execute)
    monkeypatch.setattr(cli.campaign_history, "start_execution", MagicMock(return_value="execution"))
    monkeypatch.setattr(cli.campaign_history, "finish_execution", MagicMock())
    assert cli.execute_yaml_campaign("non-interactive.yaml") == 0
    execute.assert_called_once()
    assert "cancelled by user" not in capsys.readouterr().out.lower()

    monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", MagicMock(return_value=None))
    assert cli.plan_yaml_campaign("invalid.yaml") == 1
    monkeypatch.setattr(
        cli, "load_and_validate_yaml_campaign", MagicMock(side_effect=RuntimeError("planner broke"))
    )
    assert cli.plan_yaml_campaign("broken.yaml") == 1
    cli.error.assert_called_with("Planning error: planner broke")


def test_cli_azure_confirmation_reprompts(monkeypatch):
    monkeypatch.setattr(cli.context, "azure_subscription", "sub")
    monkeypatch.setattr(cli.context, "azure_resource_group", "rg")
    monkeypatch.setattr(cli.context, "aks_cluster_name", "aks")
    monkeypatch.setattr(cli.context, "aks_kube_context", "ctx")
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="n"))
    monkeypatch.setattr(cli, "console", MagicMock())
    selector = MagicMock()
    selector._prompt_azure_details.return_value = False
    monkeypatch.setattr(cli, "PlatformSelector", MagicMock(return_value=selector))

    assert cli._confirm_azure_details() is False
    selector._prompt_azure_details.assert_called_once_with()


def test_kubernetes_facade_delegates_to_safety_module(monkeypatch):
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
        safety,
    )

    steady = MagicMock(return_value={"steady": object()})
    run = MagicMock(return_value={"passed": True})
    observe = MagicMock(return_value={"severity": "CHAOS"})
    post = MagicMock(return_value={"post": object()})
    monkeypatch.setattr(safety, "build_steady_state_checks", steady)
    monkeypatch.setattr(safety, "run_parallel_steady_state", run)
    monkeypatch.setattr(safety, "verify_fault_active", observe)
    monkeypatch.setattr(safety, "build_post_experiment_checks", post)

    assert kubernetes_chaos.build_pre_validation_checks(namespace="ns") == steady.return_value
    assert kubernetes_chaos.run_pre_validation("ctx", timeout=1) == run.return_value
    assert kubernetes_chaos.observe_fault("fault", "ctx") == observe.return_value
    assert kubernetes_chaos.build_post_validation_checks("fault") == post.return_value
    assert kubernetes_chaos.equivalent_aks_experiment("aks-pod-kill") == "aks-pod-kill"


def test_shared_validation_capture_failure_and_display(monkeypatch):
    experiment = SimpleNamespace(id="chaos-mesh-pod-kill", variables={})
    check = kubernetes_chaos.SharedChaosMeshValidationCheck(SimpleNamespace(), experiment)
    monkeypatch.setattr(
        kubernetes_chaos,
        "build_pre_validation_checks",
        lambda **_kwargs: {"pods": lambda: (False, "not ready")},
    )

    with pytest.raises(RuntimeError, match="pods"):
        check.capture({})

    assert check.build_execution_display({})["Observed"] == "Fault not observed"


def _execution_context(execution_id="execution"):
    return ExecutionContext(
        execution_id=execution_id,
        experiment_id="experiment",
        service="eks",
        experiment_name="Experiment",
    )


def test_lifecycle_runner_merges_execution_context_and_recovery_failure(monkeypatch):
    check = MagicMock()
    resolver = MagicMock()
    resolver.resolve.return_value = check
    dispatcher = MagicMock()
    dispatched = _execution_context("dispatched")
    dispatched.recovery = {"cleanup": "complete"}
    dispatched.logs = ["engine log"]
    dispatcher.execute.return_value = dispatched
    lifecycle = MagicMock()
    context = _execution_context()
    lifecycle.create_context.return_value = context
    lifecycle.run_precheck.return_value = True
    lifecycle.validate.return_value = True
    lifecycle.validate_recovery.return_value = False
    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator",
        MagicMock(return_value=lifecycle),
    )
    monkeypatch.setattr(
        LifecycleRunner,
        "_complete_with_evidence",
        MagicMock(return_value=context),
    )
    experiment = SimpleNamespace(
        id="experiment",
        service="eks",
        name="Experiment",
        variables={},
        status="SUCCESS",
        error_message="",
    )

    result = LifecycleRunner(MagicMock(), resolver, dispatcher=dispatcher).execute(experiment)

    assert result.recovery == {"cleanup": "complete"}
    assert result.logs == ["engine log"]
    assert experiment.status == "FAILED"
    assert experiment.error_message == "Recovery validation failed."


def test_lifecycle_runner_report_helpers_cover_fallbacks():
    runner = LifecycleRunner(MagicMock(), MagicMock())
    assert runner._format_resource({}) == "-"
    assert runner._format_resource({"namespace": "default", "duration": "5s"}) == "-"
    assert runner._build_execution_display(
        SimpleNamespace(build_execution_display=MagicMock(side_effect=RuntimeError("bad"))), {}
    ) == {}


def test_replace_campaign_copies_all_fields_and_experiment_list():
    experiments = [object(), object()]
    source = SimpleNamespace(
        name="Replacement",
        continue_on_failure=True,
        cloud_provider="azure",
        experiments=experiments,
    )

    result = manager.replace_campaign(source)

    assert result is manager.get_campaign("azure")
    assert result is not manager.campaign
    assert (result.name, result.continue_on_failure, result.cloud_provider) == (
        "Replacement",
        True,
        "azure",
    )
    assert result.experiments == experiments
    assert result.experiments is not experiments


def test_registry_routes_remaining_facades(monkeypatch):
    add_aks = MagicMock()
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.add_aks_experiment", add_aks
    )
    add_generic = MagicMock()
    monkeypatch.setattr(registry, "add_generic", add_generic)

    registry.execute_experiment("aks-pod-kill", {"pod": "one"})
    registry.execute_experiment("azure-redis-reboot", {"cache": "one"})
    registry.execute_experiment("chaos-mesh-pod-kill", {"pod": "one"})

    add_aks.assert_called_once_with("aks-pod-kill")
    assert add_generic.call_args_list[0].args[0] == "azure_redis"
    assert add_generic.call_args_list[1].args[0] == "chaos_mesh"


def test_target_resolver_remaining_validation_and_lookup_paths():
    discovery = MagicMock()
    discovery.list_eks_namespaces.return_value = [{"name": "default"}]
    discovery.list_eks_deployments.return_value = []
    discovery.list_eks_nodes.return_value = []
    resolver = ChaosMeshTargetResolver(discovery)

    with pytest.raises(ValueError, match="cluster"):
        resolver.resolve_namespace("", "default")
    with pytest.raises(ValueError, match="namespace"):
        resolver.resolve_namespace("cluster", "")
    with pytest.raises(ValueError, match="deployment"):
        resolver.resolve_deployment("cluster", "default", "")
    with pytest.raises(ValueError, match="pod"):
        resolver.resolve_pod("cluster", "default", "")
    with pytest.raises(ValueError, match="node"):
        resolver.resolve_node("cluster", "")
    with pytest.raises(LookupError, match="Deployment"):
        resolver.resolve_deployment("cluster", "default", "missing")
    with pytest.raises(LookupError, match="Node"):
        resolver.resolve_node("cluster", "missing")
    assert resolver.pod_selector(namespace="default", pod="pod") == {
        "namespaces": ["default"],
        "pods": {"default": ["pod"]},
    }


class _ChangingTemplates(list):
    """Return valid templates for entry lookup, then malformed ones for validation."""

    def __init__(self, second):
        super().__init__([{"name": "entry", "templateType": "Serial"}])
        self.second = second
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return iter(list.__iter__(self) if self.iterations == 1 else self.second)


def test_manifest_builder_small_optional_and_error_gaps():
    builder = ChaosMeshManifestBuilder()
    pod = builder.build_pod_chaos(
        "pod", "pod-kill", "fixed", value="2", container_names=["app"], grace_period=0
    )
    assert pod["spec"] | {} == {
        "action": "pod-kill",
        "mode": "fixed",
        "selector": {},
        "value": "2",
        "containerNames": ["app"],
        "gracePeriod": 0,
    }
    assert builder.build_dns_chaos("dns", "error", "all", value="NXDOMAIN")["spec"][
        "value"
    ] == "NXDOMAIN"
    with pytest.raises(ValueError, match="Unsupported IOChaos"):
        builder.build_io_chaos("io", "bad", "one", "/data")
    assert builder.build_stress_chaos("stress", "one", {"cpu": {}}, value="2")["spec"][
        "value"
    ] == "2"


@pytest.mark.parametrize(
    ("action", "kwargs", "message"),
    [
        ("return", {"class_name": "Main", "method": "run"}, "requires value"),
        ("exception", {"class_name": "Main", "method": "run"}, "requires exception"),
        ("stress", {}, "requires cpu_count"),
        ("stress", {"mem_type": "native"}, "heap"),
        ("ruleData", {}, "requires rule_data"),
    ],
)
def test_manifest_builder_jvm_missing_action_arguments(action, kwargs, message):
    with pytest.raises(ValueError, match=message):
        ChaosMeshManifestBuilder().build_jvm_chaos(
            "jvm", action, "one", selector={"labelSelectors": {"app": "api"}}, **kwargs
        )


def test_manifest_builder_workflow_malformed_template_gaps():
    builder = ChaosMeshManifestBuilder()
    with pytest.raises(TypeError, match="dictionaries"):
        builder.build_workflow("workflow", "entry", _ChangingTemplates(["invalid"]))
    with pytest.raises(ValueError, match="requires a name"):
        builder.build_workflow(
            "workflow",
            "entry",
            _ChangingTemplates([{"templateType": "Serial"}]),
        )


def test_input_validator_boolean_residual_branches():
    assert Validator.validate({"type": "boolean"}, True) == (True, "")
    assert Validator.validate({"type": "boolean"}, " YES ") == (True, "")
    assert Validator.validate({"type": "boolean"}, "perhaps") == (
        False,
        "Enter true or false.",
    )


def test_yaml_validator_residual_type_and_required_branches():
    validation_error = YAMLValidationError("campaign.name", "is invalid")
    assert str(validation_error) == "campaign.name: is invalid"

    assert YAMLValidator().validate([])["errors"] == [
        "Root YAML document must be a mapping/object."
    ]
    result = YAMLValidator().validate(
        {
            "campaign": [],
            "cloud": "aws",
            "experiments": [
                "invalid",
                {"service": 1, "experiment": 2},
                {"service": "lambda", "experiment": " ", "variables": {}},
            ],
        }
    )

    assert result["valid"] is False
    assert result["errors"] == [
        "campaign: must be a mapping/object.",
        "cloud: must be a mapping/object.",
        "experiments[0]: must be a mapping/object.",
        "experiments[1].service: must be a string.",
        "experiments[1].experiment: must be a string.",
        "experiments[1].variables: is required.",
        "experiments[2].experiment: must not be empty.",
    ]


def test_yaml_validator_cloud_provider_non_string_and_empty_experiments():
    non_string = YAMLValidator().validate(
        {"cloud": {"provider": 1}, "experiments": []}
    )
    assert non_string["errors"] == [
        "cloud.provider: must be a string.",
        "experiments: must contain at least one experiment.",
    ]
    no_provider = YAMLValidator().validate(
        {
            "cloud": {},
            "template": True,
            "experiments": [
                {"service": "lambda", "experiment": "memory", "variables": {}}
            ],
        }
    )
    assert no_provider["valid"] is True
