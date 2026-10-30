"""Isolated coverage for remaining lower-level CLI, validation, and reporting modules."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import chaosforge.__main__ as package_main
from chaosforge.application import discovery
from chaosforge.application.campaigns import builder, yaml_builder
from chaosforge.application.services import campaign_service, generic
from chaosforge.application.validation.legacy_experiment_validator import (
    ExperimentValidator,
)
from chaosforge.application.validation.yaml import YAMLValidationError, YAMLValidator
from chaosforge.interfaces.cli import legacy_context
from chaosforge.interfaces.cli import main as cli_main
from chaosforge.interfaces.cli.interactive import phase_ui
from chaosforge.interfaces.cli.interactive.ui import menu_renderer, tables
from chaosforge.interfaces.web import __main__ as web_main
from chaosforge.lifecycle.checks import validations
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.eks_deployment import EKSDeploymentCheck
from chaosforge.models import Campaign, Experiment
from chaosforge.reporting import pdf_generator, sns_notifier, time_utils
from chaosforge.storage.campaigns import CampaignStore


def test_module_entrypoints_and_context_defaults(monkeypatch):
    package_cli = MagicMock()
    monkeypatch.setattr(package_main, "main", package_cli)
    assert package_main.main is package_cli

    context = legacy_context.PlatformContext()
    assert context.cloud is None
    assert context.region is None
    assert context.azure_subscription is None
    assert context.aks_kube_context is None

    run = MagicMock()
    monkeypatch.setattr(web_main.app, "run", run)
    web_main.main()
    run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False)


def test_menu_renderer_prints_a_panel(monkeypatch):
    console = MagicMock()
    monkeypatch.setattr(menu_renderer, "console", console)

    menu_renderer.render_main_menu([("1", "Create campaign")])

    assert console.print.call_count == 3


def test_main_menu_option_column_is_left_aligned(monkeypatch):
    console = MagicMock()
    monkeypatch.setattr(menu_renderer, "console", console)

    menu_renderer.render_main_menu([("1", "Create campaign"), ("10", "Edit campaign")])

    panel = console.print.call_args_list[1].args[0]
    assert panel.renderable.columns[0].justify == "left"


def test_report_time_and_common_resource_check_failure_paths():
    assert "UTC+08:00" in time_utils.format_report_time(
        datetime(2026, 1, 1, tzinfo=timezone.utc), "Asia/Shanghai"
    )
    assert "CST" in time_utils.format_report_time(
        datetime(2026, 1, 1), "Asia/Shanghai"
    )

    adapter = MagicMock()
    adapter.capture.return_value = {"exists": True, "state": {"value": 2}}
    check = CommonResourceCheck(
        adapter,
        predicates={
            "matches": lambda current, baseline: current["state"] == baseline["state"],
            "raises": lambda current, baseline: (_ for _ in ()).throw(RuntimeError("bad predicate")),
        },
        report_field=("target", "state.value", "units"),
    )

    result = check.validate({"target": 2}, {"exists": True, "state": {"value": 2}})
    assert result["passed"] is False
    assert result["checks"] == {"matches": True, "raises": False}
    assert result["display"] == {"Expected": "2 units", "Observed": "2 units"}
    assert check.build_execution_display({"target": None}) == {
        "Expected": "-",
        "Observed": "-",
    }

    adapter.capture.side_effect = RuntimeError("unavailable")
    assert check.validate({}, {}) == {
        "passed": False,
        "exists": False,
        "error": "unavailable",
    }


@pytest.mark.parametrize(
    ("service", "variables", "engine", "target_service"),
    [
        ("aks", {}, "Azure Chaos Studio", "aks"),
        ("fis", {"service_id": "ec2"}, "AWS FIS", "ec2"),
        ("chaos_mesh", {}, "Chaos Mesh", "eks"),
    ],
)
def test_campaign_builder_selects_engine_and_target(monkeypatch, service, variables, engine, target_service):
    monkeypatch.setattr(builder, "add", MagicMock())
    create = MagicMock()
    monkeypatch.setattr(builder, "create_experiment", create)
    create.return_value = Experiment(
        "id", service, "Name", "/tmp/experiment.json", variables, engine, target_service
    )

    experiment = builder.build_experiment(
        service,
        {"id": "id", "name": "Name", "json": "experiment.json"},
        variables,
    )

    assert experiment.engine == engine
    assert experiment.target_service == target_service


def test_yaml_builder_and_generic_service_error_paths(monkeypatch):
    service = MagicMock()
    service.build_document.side_effect = LookupError("Service 'missing' not found")
    monkeypatch.setattr(yaml_builder, "CampaignYAMLService", MagicMock(return_value=service))
    with pytest.raises(LookupError, match="Service 'missing' not found"):
        yaml_builder.build_campaign({"experiments": [{"service": "missing", "experiment": "id", "variables": {}}]})

    monkeypatch.setattr(generic, "get_experiment", MagicMock(return_value=None))
    monkeypatch.setattr("builtins.input", MagicMock())
    assert generic.add_generic("lambda", "missing") is None

    metadata = {"name": "Original"}
    monkeypatch.setattr(generic, "get_experiment", MagicMock(return_value=metadata))
    catalog = MagicMock()
    catalog.get_experiment.return_value = {"name": "Stop instance"}
    monkeypatch.setattr(generic, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(generic, "collect_inputs", MagicMock(return_value={"service_id": "ec2"}))
    build = MagicMock()
    monkeypatch.setattr(generic, "build_experiment", build)

    generic.add_generic("fis", "template", prefill={"service_id": "ec2", "experiment_id": "stop"})

    assert build.call_args.args[1]["name"] == "Stop instance (AWS FIS)"


def test_discovery_and_campaign_service_wrappers(monkeypatch):
    catalog = MagicMock()
    catalog.list_services.return_value = ["lambda", "aks", "fis", "chaos_mesh", "__cache__"]
    monkeypatch.setattr(discovery, "ExperimentCatalog", MagicMock(return_value=catalog))
    assert discovery.discover_services("aws") == ["kinesis", "lambda"]
    assert discovery.discover_services("azure") == ["aks"]
    assert discovery.display_name("unknown-service") == "Unknown-Service"

    campaign = Campaign(
        name="Active",
        experiments=[Experiment("id", "lambda", "Name", "file", {})],
    )
    monkeypatch.setattr(campaign_service, "get_campaign", MagicMock(return_value=campaign))
    assert campaign_service.get_selected_experiments([-1, 0, 2]) == [campaign.experiments[0]]

    add = MagicMock()
    monkeypatch.setattr(campaign_service, "add", add)
    create = MagicMock(
        return_value=Experiment(
            "fis-id", "fis", "FIS", "/tmp/definition.json", {}, "AWS FIS"
        )
    )
    monkeypatch.setattr(campaign_service, "create_experiment", create)
    experiment = campaign_service.add_experiment(
        {"service": "fis"},
        {"id": "fis-id", "name": "FIS", "json": "fis.json"},
        {},
    )
    assert experiment.engine == "AWS FIS"
    add.assert_called_once_with(experiment)

    lifecycle = MagicMock()
    monkeypatch.setattr(campaign_service, "lifecycle_service", lifecycle)
    assert campaign_service.execute_current_campaign() is campaign
    assert campaign_service.execute_current_campaign_web() is campaign
    assert lifecycle.execute_campaign.call_count == 2

    get = MagicMock(return_value="experiment")
    list_all = MagicMock(return_value=["experiment"])
    update = MagicMock()
    remove = MagicMock()
    clear = MagicMock()
    save = MagicMock()
    load = MagicMock(return_value=campaign)
    list_saved = MagicMock(return_value=[{"name": "saved"}])
    delete = MagicMock()
    monkeypatch.setattr(campaign_service, "get", get)
    monkeypatch.setattr(campaign_service, "list_all", list_all)
    monkeypatch.setattr(campaign_service, "update", update)
    monkeypatch.setattr(campaign_service, "remove", remove)
    monkeypatch.setattr(campaign_service, "clear", clear)
    monkeypatch.setattr(campaign_service, "save_campaign", save)
    monkeypatch.setattr(campaign_service, "load_campaign", load)
    monkeypatch.setattr(campaign_service, "list_campaigns", list_saved)
    monkeypatch.setattr(campaign_service, "delete_campaign", delete)

    assert campaign_service.get_current_campaign() is campaign
    assert campaign_service.get_experiments() == ["experiment"]
    assert campaign_service.get_experiment(2) == "experiment"
    campaign_service.update_experiment(2, "updated")
    campaign_service.remove_experiment(2)
    campaign_service.clear_current_campaign()
    campaign_service.save_current_campaign("saved")
    assert campaign_service.load_saved_campaign("saved") is campaign
    assert campaign_service.list_saved_campaigns() == [{"name": "saved"}]
    campaign_service.delete_saved_campaign("saved")


def test_legacy_validator_reports_invalid_metadata_types_ranges_and_unknown_values():
    validator = ExperimentValidator()
    assert not validator.validate({"inputs": "bad"}, {}).get("valid")

    result = validator.validate(
        {
            "inputs": [
                {"name": "count", "required": True, "type": "integer", "min": "2", "max": "4"},
                {"name": "ratio", "type": "float", "min": 0.1, "max": 0.9},
                {"name": "enabled", "type": "boolean"},
            ]
        },
        {"count": True, "ratio": "bad", "enabled": "perhaps", "extra": "value"},
    )
    assert result["valid"] is False
    assert len(result["errors"]) == 3
    assert result["warnings"] == ["Variable 'extra' is not defined in experiment metadata."]

    bounds = validator.validate(
        {"inputs": [{"name": "count", "type": "integer", "min": 2, "max": 4}, {"name": "ratio", "type": "float", "min": 0.1, "max": 0.9}]},
        {"count": 5, "ratio": 0.0},
    )
    assert len(bounds["errors"]) == 2
    assert validator._parse_integer_limit("invalid") is None
    assert validator._parse_float_limit("invalid") is None
    assert validator._is_boolean(" false ") is True


def test_yaml_validator_and_error_string_cover_invalid_document_shapes():
    validator = YAMLValidator()
    assert str(YAMLValidationError("root", "bad")) == "root: bad"
    assert not validator.validate([])["valid"]
    result = validator.validate(
        {
            "unknown": True,
            "campaign": ["bad"],
            "cloud": {"provider": 1},
            "experiments": [None, {"service": "", "experiment": 1, "variables": []}],
        }
    )
    assert result["valid"] is False
    assert "root: unknown key 'unknown'." in result["errors"]
    assert any("campaign: must be" in error for error in result["errors"])
    assert any("cloud.provider: must be" in error for error in result["errors"])
    assert any("experiments[0]" in error for error in result["errors"])


def test_campaign_store_lists_missing_directory_sorts_and_deletes(tmp_path):
    paths = SimpleNamespace(campaigns=tmp_path / "campaigns")
    store = CampaignStore(paths)
    assert store.list() == []
    campaign = Campaign(name="One", experiments=[Experiment("id", "lambda", "Name", "file", {"x": 1})])
    store.save(campaign)
    store.save(Campaign(name="Two"))
    listed = store.list()
    assert {item["name"] for item in listed} == {"One", "Two"}
    assert store.load("One").experiments[0].variables == {"x": 1}
    store.delete("One")
    store.delete("One")
    assert not (paths.campaigns / "One.campaign.json").exists()


def test_eks_deployment_check_captures_and_compares_without_kubernetes_connection():
    deployment = SimpleNamespace(
        spec=SimpleNamespace(replicas=None),
        status=SimpleNamespace(ready_replicas=None, available_replicas=2, updated_replicas=2),
    )
    discovery = MagicMock()
    discovery.k8s_apps_api.read_namespaced_deployment.return_value = deployment
    check = EKSDeploymentCheck(discovery)
    target = {"eks_cluster": "cluster", "namespace": "default", "deployment_name": "api"}
    baseline = check.capture(target)
    assert baseline["desired_replicas"] == 0
    assert check.validate(target, baseline)["passed"] is True

    check.capture = MagicMock(side_effect=RuntimeError("not found"))
    failure = check.validate(target, baseline)
    assert failure["passed"] is False
    assert failure["error"] == "not found"


@pytest.mark.parametrize(
    ("check_type", "target", "expected"),
    [
        (validations.EKSDeploymentCheck, {"eks_cluster": "c", "namespace": "n", "deployment_name": "d"}, {"deployment": "d"}),
        (validations.EKSPodCheck, {"eks_cluster": "c", "namespace": "n", "pod": "p"}, {"pod": "p"}),
        (validations.EKSNodeCheck, {"eks_cluster": "c", "node_name": "node"}, {"node": "node"}),
        (validations.EKSContainerRestartCheck, {"eks_cluster": "c", "namespace": "n", "pod_name": "p"}, {"pod": "p"}),
    ],
)
def test_validation_adapters_add_target_identity(monkeypatch, check_type, target, expected):
    adapter_name = check_type.__name__.replace("Check", "Adapter")
    if check_type is validations.EKSContainerRestartCheck:
        adapter_name = "EKSContainerRestartAdapter"
    monkeypatch.setattr(validations, adapter_name, MagicMock())
    check = check_type(MagicMock())
    check.common_check = MagicMock()
    check.common_check.capture.return_value = {"exists": True}
    check.common_check.validate.return_value = {"passed": True}
    assert check.capture(target) == {"exists": True}
    result = check.validate(target, {})
    assert result["passed"] is True
    assert all(result[key] == value for key, value in expected.items())


def test_phase_ui_and_tables_render_buffered_failure_and_dry_run(monkeypatch):
    output = MagicMock()
    monkeypatch.setattr(phase_ui, "console", output)
    ticks = iter([1.0, 2.5])
    monkeypatch.setattr(phase_ui.time, "monotonic", lambda: next(ticks))
    ui = phase_ui.PhaseUI("experiment")
    with ui.phase("custom"):
        ui.step("queued")
        ui.step("now", live=True)
        ui.status("ready")
        ui.info("note")
    assert output.print.call_count >= 6

    ticks = iter([3.0, 4.0])
    monkeypatch.setattr(phase_ui.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="x" * 101), ui.phase("setup"):
        raise RuntimeError("x" * 101)

    monkeypatch.setattr(phase_ui.time, "sleep", MagicMock())
    assert list(phase_ui.live_countdown("run", 2)) == [(2, 0), (1, 1), (0, 2)]
    rendered = MagicMock()
    monkeypatch.setattr(tables, "console", rendered)
    tables.menu_categorized("Choices", [("Empty", []), ("Actions", [(1, "Run")])])
    tables.campaign([Experiment("id", "lambda", "Name", "file", {"dry_run": "yes"}, status="SUCCESS")])
    assert rendered.print.call_count == 2


def test_reporting_helpers_escape_pdf_text_and_publish_all_summary_outcomes(monkeypatch, tmp_path):
    report = tmp_path / "report.txt"
    report.write_text("<unsafe> & text\n\n", encoding="utf-8")
    document = MagicMock()
    monkeypatch.setattr(pdf_generator, "SimpleDocTemplate", MagicMock(return_value=document))
    pdf = pdf_generator.generate_pdf(report)
    assert pdf == report.with_suffix(".pdf")
    story = document.build.call_args.args[0]
    assert len(story) == 2

    client = MagicMock()
    monkeypatch.setattr(sns_notifier.boto3, "client", MagicMock(return_value=client))
    campaign = SimpleNamespace(name="Release", start_time="start", end_time="end", duration=1.0, experiments=[SimpleNamespace(status="SUCCESS"), SimpleNamespace(status="FAILED")])
    sns_notifier.publish_summary("arn", "region", campaign, report)
    message = client.publish.call_args.kwargs["Message"]
    assert "PARTIAL SUCCESS" in message

    campaign.experiments = [SimpleNamespace(status="FAILED")]
    sns_notifier.publish_summary("arn", "region", campaign, report)
    assert "Result : FAILED" in client.publish.call_args.kwargs["Message"]
    campaign.experiments = [SimpleNamespace(status="SUCCESS")]
    sns_notifier.publish_summary("arn", "region", campaign, report)
    assert "Result : SUCCESS" in client.publish.call_args.kwargs["Message"]


def test_cli_lifecycle_helpers_display_plan_and_command_dispatch(monkeypatch, capsys):
    experiment = SimpleNamespace(variables={"aws_region": "eu-west-1"})
    runner = MagicMock()
    monkeypatch.setattr(cli_main.lifecycle_service, "create_runner", MagicMock(return_value=runner))
    lifecycle = cli_main.create_lifecycle_runner(experiment)
    assert lifecycle is runner
    monkeypatch.setattr(cli_main, "create_lifecycle_runner", MagicMock(return_value=runner))
    cli_main.execute_lifecycle_experiment(experiment)
    runner.execute.assert_called_once_with(experiment)

    result = SimpleNamespace(executable=True, experiments=[], targets=[], impact={}, permissions=[], capabilities=[], duration={}, recovery={}, warnings=[], blockers=[])
    cli_main.display_campaign_plan(SimpleNamespace(name="Safe"), result)
    assert "Campaign    : Safe" in capsys.readouterr().out

    monkeypatch.setattr(cli_main, "validate_yaml_campaign", MagicMock(return_value=0))
    monkeypatch.setattr("sys.argv", ["chaosforge", "validate", "campaign.yaml"])
    with pytest.raises(SystemExit) as exit_result:
        cli_main.main()
    assert exit_result.value.code == 0
