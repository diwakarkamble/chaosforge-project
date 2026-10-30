import json
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, mock_open

import pytest

from chaosforge.application.services import planning
from chaosforge.common.azure_cli import azure_cli_command
from chaosforge.interfaces.cli.interactive import azure_redis_menu, input_engine, platform_selector
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.session import context
from chaosforge.models.planning import PlanResult


@pytest.fixture(autouse=True)
def restore_cli_context():
    original = vars(context).copy()
    yield
    vars(context).clear()
    vars(context).update(original)


def experiment(**overrides):
    values = {
        "id": "exp",
        "service": "svc",
        "name": "Experiment",
        "engine": "Chaos Toolkit",
        "variables": {"aws_region": "us-east-1"},
        "json_file": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def metadata(definition=None):
    definition = definition or {"id": "exp", "inputs": []}
    return {"experiments": [definition]}


def test_planner_campaign_and_early_blockers(monkeypatch):
    service = planning.PlanService(discovery_factory=MagicMock())

    assert service.plan_campaign(None).blockers == ["No campaign supplied."]
    assert service.plan_experiment(None).blockers == ["No experiment supplied."]

    monkeypatch.setattr(planning, "load_metadata", lambda _: None)
    missing_metadata = service.plan_experiment(experiment())
    assert missing_metadata.experiments[0]["status"] == "BLOCKED"
    assert "Metadata not found" in missing_metadata.blockers[0]

    monkeypatch.setattr(planning, "load_metadata", lambda _: {"experiments": []})
    missing_definition = service.plan_experiment(experiment())
    assert missing_definition.experiments[0]["status"] == "BLOCKED"
    assert "was not found" in missing_definition.blockers[0]


def test_planner_campaign_aggregates_impact_duration_and_default_region(monkeypatch):
    definition = {
        "id": "exp",
        "description": "safe description",
        "inputs": [{"name": "aws_region", "default": "eu-west-1"}],
    }
    monkeypatch.setattr(planning, "load_metadata", lambda _: metadata(definition))
    factory = MagicMock(return_value=MagicMock())
    service = planning.PlanService(discovery_factory=factory)
    campaign = SimpleNamespace(
        experiments=[
            experiment(variables={"duration_seconds": "12"}),
            experiment(variables={"duration": "not-a-number"}),
        ]
    )

    result = service.plan_campaign(campaign)

    assert result.executable is True
    assert result.duration["estimated_seconds"] == 12
    assert result.impact["capacity"]["selected_resources"] == 2
    assert result.impact["capacity"]["by_service"] == {"svc": 2}
    assert factory.call_args_list[0].args == ("eu-west-1",)


def test_planner_blocks_without_region_or_targets(monkeypatch):
    monkeypatch.setattr(planning, "load_metadata", lambda _: metadata())
    no_region = planning.PlanService().plan_experiment(experiment(variables={}))
    assert no_region.experiments[0]["status"] == "BLOCKED"
    assert "does not specify an AWS region" in no_region.blockers[0]

    service = planning.PlanService(discovery_factory=lambda _: MagicMock())
    monkeypatch.setattr(service, "_resolve_targets", lambda *_: [])
    no_targets = service.plan_experiment(experiment())
    assert no_targets.experiments[0]["status"] == "BLOCKED"
    assert "No targets could be resolved" in no_targets.blockers[0]


def test_planner_chaos_mesh_preflight_requirements_and_warning(monkeypatch):
    definition = {"id": "exp", "inputs": [], "chaos_mesh": {"kind": "PodChaos"}}
    monkeypatch.setattr(planning, "load_metadata", lambda _: metadata(definition))
    service = planning.PlanService(discovery_factory=lambda _: MagicMock())

    no_cluster = service.plan_experiment(
        experiment(engine="Chaos Mesh", variables={"aws_region": "us-east-1"})
    )
    assert "requires an EKS cluster" in no_cluster.blockers[0]

    definition["chaos_mesh"] = {}
    no_kind = service.plan_experiment(
        experiment(
            engine="Chaos Mesh",
            variables={"aws_region": "us-east-1", "eks_cluster": "cluster"},
        )
    )
    assert "does not define a Chaos Mesh kind" in no_kind.blockers[0]

    definition["chaos_mesh"] = {"kind": "PodChaos"}
    preflight = MagicMock()
    preflight.check.return_value = SimpleNamespace(
        status="READY",
        executable=True,
        checks=[],
        blockers=[],
        warnings=["daemon coverage is partial"],
    )
    service.chaos_mesh_preflight_factory = MagicMock(return_value=preflight)
    ready = service.plan_experiment(
        experiment(
            engine="Chaos Mesh",
            variables={"aws_region": "us-east-1", "eks_cluster": "cluster"},
        )
    )
    assert ready.warnings == ["Chaos Mesh 'exp': daemon coverage is partial"]
    preflight.check.assert_called_once_with(
        cluster="cluster", kind="PodChaos", namespace=None
    )


def test_planner_kind_loading_and_selection_helpers(tmp_path):
    definition_file = tmp_path / "experiment.json"
    definition_file.write_text(json.dumps({"chaos_mesh": {"kind": "NetworkChaos"}}))
    exp = experiment(json_file=str(definition_file))

    assert planning.PlanService._load_chaos_mesh_kind(exp) == "NetworkChaos"
    assert planning.PlanService._load_chaos_mesh_kind(exp, {"chaos_mesh": "bad"}) == (
        "NetworkChaos"
    )
    assert planning.PlanService._load_chaos_mesh_kind(experiment()) is None
    definition_file.write_text("not json")
    assert planning.PlanService._load_chaos_mesh_kind(exp) is None

    resources = [
        {"id": "one", "name": "first"},
        {"arn": "arn:two", "name": "second"},
    ]
    assert planning.PlanService._match_selected_resources([], "one") == []
    assert planning.PlanService._match_selected_resources(resources, ["one", "arn:two"]) == resources
    assert planning.PlanService._match_selected_resources(resources, 123) == []


@pytest.mark.parametrize(
    ("resource_type", "variables", "message"),
    [
        ("eks-node", {}, "requires an EKS cluster"),
        ("eks-namespace", {}, "requires an EKS cluster"),
        ("eks-deployment", {}, "requires a namespace"),
        ("eks-deployment", {"namespace": "ns"}, "requires an EKS cluster"),
        ("eks-pod", {}, "requires a namespace"),
        ("eks-pod", {"namespace": "ns"}, "requires an EKS cluster"),
    ],
)
def test_planner_discovery_requires_parent_values(resource_type, variables, message):
    with pytest.raises(ValueError, match=message):
        planning.PlanService()._discover_resources(
            resource_type, variables, {}, MagicMock()
        )


def test_planner_target_resolution_validation_and_deduplication():
    service = planning.PlanService()
    definition = {
        "inputs": [
            {"type": "aws_resource"},
            {"name": "target", "type": "aws_resource", "resource_type": "lambda"},
        ]
    }
    with pytest.raises(ValueError, match="was not supplied"):
        service._resolve_targets(experiment(variables={}), definition, MagicMock())

    discovery = MagicMock()
    discovery.discover.return_value = None
    assert service._discover_resources("lambda", {}, {}, discovery) == []
    assert service._deduplicate_targets(
        [
            {"resource_type": "lambda", "resource_id": "one"},
            {"resource_type": "lambda", "resource_id": "one"},
        ]
    ) == [{"resource_type": "lambda", "resource_id": "one"}]


def test_planner_recovery_sources(monkeypatch):
    result = PlanResult()
    planning.PlanService._add_recovery({"recovery": "automatic"}, experiment(), result)
    assert result.recovery["behavior"] == "automatic"

    recovered = PlanResult()
    monkeypatch.setattr(
        "builtins.open", mock_open(read_data=json.dumps({"recovery": "restore snapshot"}))
    )
    planning.PlanService._add_recovery({"json": "exp.json"}, experiment(), recovered)
    assert recovered.recovery["behavior"] == "restore snapshot"

    rollback = PlanResult()
    monkeypatch.setattr(
        "builtins.open",
        mock_open(read_data=json.dumps({"rollbacks": [{"name": "undo"}, {}]})),
    )
    planning.PlanService._add_recovery({"json": "exp.json"}, experiment(), rollback)
    assert rollback.recovery["details"][0]["rollback_actions"] == ["undo"]

    fallback = PlanResult()
    monkeypatch.setattr("builtins.open", MagicMock(side_effect=OSError("missing")))
    planning.PlanService._add_recovery({"json": "missing.json"}, experiment(), fallback)
    assert fallback.recovery["details"][0]["recovery"].startswith("Provider/framework")


def test_input_parameter_coercion_and_generic_types(monkeypatch):
    monkeypatch.setattr(input_engine.Validator, "validate", lambda *_: (True, ""))
    assert input_engine._validate_fis_parameter({"name": "count", "type": "number"}, "2") == (
        True,
        2,
        "",
    )
    assert input_engine._validate_fis_parameter({"name": "ratio", "type": "number"}, "2.5")[1] == 2.5
    assert input_engine._validate_fis_parameter({"name": "enabled", "type": "boolean"}, "yes")[1] is True

    monkeypatch.setattr(input_engine, "title", MagicMock())
    monkeypatch.setattr(input_engine, "error", MagicMock())
    monkeypatch.setattr(
        input_engine,
        "get_input",
        MagicMock(side_effect=["bad", "7", "2.5", "no", "value"]),
    )
    fields = [
        {"name": "count", "label": "Count", "type": "integer"},
        {"name": "ratio", "label": "Ratio", "type": "float"},
        {"name": "enabled", "label": "Enabled", "type": "boolean"},
        {"name": "text", "label": "Text", "type": "string"},
    ]
    values = input_engine.collect_inputs({"name": "types", "inputs": fields})
    assert {key: values[key] for key in ("count", "ratio", "enabled", "text")} == {
        "count": 7,
        "ratio": 2.5,
        "enabled": False,
        "text": "value",
    }
    input_engine.error.assert_called_once()


def test_input_multiple_and_ebs_resource_selection(monkeypatch):
    selector = MagicMock()
    selector.select_multiple.return_value = [{"arn": "a"}, {"arn": "b"}]
    selector.select.return_value = {"id": "i-1"}
    selector.select_ebs_volume.return_value = {"id": "vol-1", "device_name": "/dev/xvdf"}
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    multiple = input_engine.collect_inputs(
        {
            "name": "multi",
            "inputs": [{
                "name": "functions",
                "label": "Functions",
                "type": "aws_resource",
                "resource_type": "lambda",
                "multiple": True,
                "return": "arn",
            }],
        }
    )
    assert multiple["functions"] == ["a", "b"]

    ebs = input_engine.collect_inputs(
        {
            "name": "ebs",
            "inputs": [
                {"name": "instance", "label": "Instance", "type": "aws_resource", "resource_type": "ec2", "return": "id"},
                {"name": "volume", "label": "Volume", "type": "aws_resource", "resource_type": "ebs-volume", "parent": "instance", "return": "id"},
            ],
        }
    )
    assert ebs["volume"] == "vol-1"
    assert ebs["device_name"] == "/dev/xvdf"
    selector.select_ebs_volume.assert_called_once_with("i-1")


def test_input_fis_resource_and_target_failures(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiments.return_value = [{
        "id": "exp",
        "name": "Experiment",
        "parameters": [{"name": "target", "label": "Target", "type": "aws_resource"}],
    }]
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(input_engine, "get_input", MagicMock(return_value="1"))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    with pytest.raises(ValueError, match="Missing resource_type"):
        input_engine.collect_inputs(
            {"name": "fis", "inputs": [{"name": "experiment_id", "label": "Experiment"}]},
            prefill={"service_id": "ec2"},
        )

    catalog.get_experiment.return_value = {"resource_type": "unsupported"}
    with pytest.raises(LookupError, match="not supported"):
        input_engine.collect_inputs(
            {"name": "fis", "inputs": [{"name": "target_arn", "label": "Target"}]},
            prefill={"service_id": "custom", "experiment_id": "exp"},
        )


def test_platform_context_cleanup_cache_and_refresh_failures(monkeypatch, tmp_path):
    helper = ModuleType("chaosforge.providers.azure.components.aks.kubernetes")
    helper.delete_kube_context = MagicMock(return_value=False)
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    run = MagicMock()
    monkeypatch.setattr(platform_selector.subprocess, "run", run)
    platform_selector._remove_kube_context("temporary")
    run.assert_not_called()

    cache = tmp_path / "azure.json"
    monkeypatch.setattr(platform_selector, "_AZURE_CACHE_FILE", str(cache))
    assert platform_selector._load_azure_cache() is None

    selector = platform_selector.PlatformSelector()
    context.aks_kube_context = None
    context.azure_subscription = None
    context.azure_resource_group = None
    context.aks_cluster_name = None
    assert selector.ensure_azure_kube_context() is False

    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    context.aks_cluster_name = "cluster"
    monkeypatch.setattr(platform_selector, "error", MagicMock())
    run.side_effect = FileNotFoundError
    assert selector.ensure_azure_kube_context() is False
    assert "not found" in platform_selector.error.call_args.args[0]


def test_platform_manual_cluster_setup_fallback(monkeypatch):
    selector = platform_selector.PlatformSelector()
    monkeypatch.setattr(platform_selector, "title", MagicMock())
    monkeypatch.setattr(platform_selector, "console", MagicMock())
    monkeypatch.setattr(platform_selector, "error", MagicMock())
    monkeypatch.setattr(platform_selector, "info", MagicMock())
    save = MagicMock()
    monkeypatch.setattr(platform_selector, "_save_azure_cache", save)
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda _: nullcontext()
    )
    monkeypatch.setattr(
        platform_selector,
        "prompt",
        MagicMock(side_effect=["sub-12345678", "rg", "cluster", "y"]),
    )
    runs = MagicMock(
        side_effect=[
            SimpleNamespace(returncode=0, stdout='{"name":"Account"}', stderr=""),
            SimpleNamespace(returncode=1, stdout="", stderr="listing denied"),
            SimpleNamespace(returncode=0, stdout='{"location":"eastus"}', stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]
    )
    monkeypatch.setattr(platform_selector.subprocess, "run", runs)
    helper = ModuleType("chaosforge.providers.azure.components.aks.kubernetes")
    helper.list_kube_contexts = lambda: []
    monkeypatch.setitem(sys.modules, helper.__name__, helper)

    assert selector._prompt_azure_details() is True
    assert context.azure_resource_group == "rg"
    assert context.azure_location == "eastus"
    assert context.aks_kube_context == "cluster"
    assert runs.call_args_list[-1].args[0][0:3] == azure_cli_command(
        "aks", "get-credentials"
    )
    assert save.call_args.args[0]["kube_context"] == "cluster"


def test_redis_context_requires_login_and_handles_discovery_failures(monkeypatch):
    context.azure_subscription = None
    context.azure_resource_group = None
    report = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "error", report)
    monkeypatch.setattr(
        azure_redis_menu,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": False},
    )
    assert azure_redis_menu._ensure_azure_context() is False
    assert "Log in to Azure" in report.call_args.args[0]

    monkeypatch.setattr(
        azure_redis_menu,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Account"},
    )
    monkeypatch.setattr(
        azure_redis_menu,
        "AzureResourceDiscovery",
        MagicMock(side_effect=RuntimeError("denied")),
    )
    assert azure_redis_menu._ensure_azure_context() is False
    assert "Could not discover Azure resource groups" in report.call_args.args[0]


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ({"name": "cache", "label": "Cache", "required": True}, "", "is required"),
        ({"name": "count", "label": "Count", "type": "integer"}, "bad", "must be an integer"),
        ({"name": "mode", "label": "Mode", "type": "choice", "choices": ["safe"]}, "fast", "must be one of"),
    ],
)
def test_redis_menu_rejects_invalid_fields(monkeypatch, field, bad_value, message):
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    metadata_item = {"id": "exp", "name": "Experiment", "inputs": [field]}
    monkeypatch.setattr(
        azure_redis_menu,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Account"},
    )
    groups = MagicMock()
    groups.list_resource_groups.return_value = [{"id": "rg", "name": "rg"}]
    monkeypatch.setattr(azure_redis_menu, "AzureResourceDiscovery", MagicMock(return_value=groups))
    monkeypatch.setattr(azure_redis_menu, "get_experiments", lambda _: [metadata_item])
    monkeypatch.setattr(
        azure_redis_menu, "prompt", MagicMock(side_effect=["1", "1", bad_value, "0"])
    )
    report = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "error", report)
    build = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "build_experiment", build)

    azure_redis_menu.redis_experiment_menu()

    assert message in report.call_args.args[0]
    build.assert_not_called()


def test_redis_menu_navigation_and_integer_default(monkeypatch):
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    item = {
        "id": "exp",
        "name": "Experiment",
        "inputs": [{"name": "count", "label": "Count", "type": "integer", "default": 3}],
    }
    monkeypatch.setattr(
        azure_redis_menu,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Account"},
    )
    groups = MagicMock()
    groups.list_resource_groups.return_value = [{"id": "rg", "name": "rg"}]
    monkeypatch.setattr(azure_redis_menu, "AzureResourceDiscovery", MagicMock(return_value=groups))
    monkeypatch.setattr(azure_redis_menu, "get_experiments", lambda _: [item])
    build = MagicMock(return_value=SimpleNamespace(name="Experiment"))
    monkeypatch.setattr(azure_redis_menu, "build_experiment", build)
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(side_effect=["1", "1", "bad", "1", ""]))
    monkeypatch.setattr(azure_redis_menu, "error", MagicMock())

    azure_redis_menu.redis_experiment_menu()
    assert build.call_args.args[2]["count"] == 3
    azure_redis_menu.error.assert_called_once_with("Count must be an integer.")

    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(side_effect=["1", "m"]))
    with pytest.raises(BackToMainMenu):
        azure_redis_menu.redis_experiment_menu()
