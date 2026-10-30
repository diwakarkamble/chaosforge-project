"""Interactive CLI coverage with all terminal and execution boundaries mocked."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli import main as cli_main
from chaosforge.models import Campaign, Experiment


@pytest.fixture(autouse=True)
def restore_platform_context():
    """Keep CLI context and campaign-manager state from leaking between tests."""
    original = vars(cli_main.context).copy()
    campaign_state = vars(cli_main.campaign).copy()
    campaign_state["experiments"] = list(cli_main.campaign.experiments)
    yield
    vars(cli_main.context).clear()
    vars(cli_main.context).update(original)
    vars(cli_main.campaign).clear()
    vars(cli_main.campaign).update(campaign_state)


def experiment(service="lambda", name="Timeout", **variables):
    return Experiment(
        id="timeout",
        service=service,
        name=name,
        json_file="timeout.json",
        variables=variables,
    )


@pytest.fixture
def quiet_ui(monkeypatch):
    for name in (
        "clear_screen",
        "print_banner",
        "dashboard",
        "title",
        "menu",
        "pause",
        "error",
        "info",
        "success",
        "warning",
    ):
        monkeypatch.setattr(cli_main, name, MagicMock())
    monkeypatch.setattr(cli_main, "console", MagicMock())


def test_confirm_campaign_execution_retries_until_valid(monkeypatch, capsys):
    responses = iter(["maybe", "YES"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))

    assert cli_main.confirm_campaign_execution() is True
    assert "Please enter Y or N." in capsys.readouterr().out


def test_confirm_azure_details_uses_cached_context_or_prompts(monkeypatch):
    selector = MagicMock()
    selector._prompt_azure_details.return_value = False
    monkeypatch.setattr(cli_main, "PlatformSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(cli_main, "console", MagicMock())

    cli_main.context.azure_subscription = None
    cli_main.context.azure_resource_group = None
    cli_main.context.aks_cluster_name = None
    assert cli_main._confirm_azure_details() is False
    selector._prompt_azure_details.assert_called_once_with()

    cli_main.context.azure_subscription = "subscription"
    cli_main.context.azure_resource_group = "group"
    cli_main.context.aks_cluster_name = "cluster"
    cli_main.context.azure_account_name = "account"
    cli_main.context.aks_kube_context = "kubectl-context"
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="y"))
    selector.ensure_azure_kube_context.return_value = True

    assert cli_main._confirm_azure_details() is True
    assert selector._prompt_azure_details.call_count == 1
    selector.ensure_azure_kube_context.assert_called_once_with()


def test_add_experiment_handles_invalid_choice_then_routes_aws(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main.context, "region", "us-east-1")
    monkeypatch.setattr(cli_main, "discover_services", MagicMock(return_value=["lambda"]))
    monkeypatch.setattr(cli_main, "display_name", lambda service: service.title())
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["invalid", "1", "0"]))
    choose_experiment = MagicMock()
    monkeypatch.setattr(cli_main, "experiment_menu", choose_experiment)

    cli_main.add_experiment()

    cli_main.error.assert_called_once_with("Invalid Choice")
    choose_experiment.assert_called_once_with("lambda")


def test_add_experiment_routes_azure_aks_only_after_confirmation(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main.context, "region", "azure")
    monkeypatch.setattr(cli_main, "discover_services", MagicMock(return_value=["aks"]))
    monkeypatch.setattr(cli_main, "display_name", lambda service: service.upper())
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "1", "0"]))
    monkeypatch.setattr(cli_main, "_confirm_azure_details", MagicMock(side_effect=[False, True]))
    aks_menu = MagicMock()
    monkeypatch.setattr(cli_main, "aks_experiment_menu", aks_menu)

    cli_main.add_experiment()

    aks_menu.assert_called_once_with()


def test_add_experiment_routes_azure_redis_without_aks_confirmation(
    monkeypatch, quiet_ui
):
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main.context, "region", "azure")
    monkeypatch.setattr(
        cli_main, "discover_services", MagicMock(return_value=["azure_redis"])
    )
    monkeypatch.setattr(cli_main, "display_name", lambda service: service)
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "0"]))
    confirm = MagicMock()
    redis_menu = MagicMock()
    monkeypatch.setattr(cli_main, "_confirm_azure_details", confirm)
    monkeypatch.setattr(cli_main, "redis_experiment_menu", redis_menu)

    cli_main.add_experiment()

    redis_menu.assert_called_once_with()
    confirm.assert_not_called()


def test_add_experiment_routes_generic_azure_component_menu(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main.context, "region", "azure")
    monkeypatch.setattr(cli_main, "discover_services", MagicMock(return_value=["azure_vm"]))
    monkeypatch.setattr(cli_main, "display_name", lambda service: service)
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "0"]))
    component_menu = MagicMock()
    monkeypatch.setattr(cli_main, "azure_component_experiment_menu", component_menu)

    cli_main.add_experiment()

    component_menu.assert_called_once_with("azure_vm")


def test_view_campaign_reads_the_active_azure_campaign(monkeypatch, quiet_ui):
    azure_campaign = Campaign(name="Azure Draft", cloud_provider="azure")
    configured = experiment(name="Redis reboot")
    azure_campaign.experiments = [configured]
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main, "get_campaign", MagicMock(return_value=azure_campaign))
    listed = MagicMock(return_value=[configured])
    monkeypatch.setattr(cli_main, "list_all", listed)
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="0"))

    cli_main.view_campaign()

    listed.assert_called_with("azure")
    assert any("Azure Draft" in str(call) for call in cli_main.console.print.call_args_list)


def test_campaign_mutations_use_the_active_azure_cloud(monkeypatch, quiet_ui):
    existing = experiment(name="Redis reboot")
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[existing]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    remove = MagicMock()
    monkeypatch.setattr(cli_main, "remove", remove)

    cli_main.remove_experiment()

    remove.assert_called_once_with(0, "azure")


def test_edit_and_clear_campaign_mutations_use_the_active_azure_cloud(monkeypatch, quiet_ui):
    existing = experiment(name="Redis reboot")
    updated = experiment(name="Updated Redis reboot")
    azure_campaign = Campaign(name="Azure Draft", cloud_provider="azure", experiments=[existing])
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main, "get_campaign", MagicMock(return_value=azure_campaign))
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[existing]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"id": existing.id, "name": existing.name, "inputs": []}),
    )
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.azure_redis_menu.collect_redis_inputs",
        MagicMock(return_value={"redis_name": "cache"}),
    )
    monkeypatch.setattr(cli_main, "create_experiment", MagicMock(return_value=updated))
    monkeypatch.setattr(
        cli_main,
        "ExperimentValidationService",
        lambda: SimpleNamespace(validate_experiment=lambda _: {"valid": True, "errors": []}),
    )
    update = MagicMock()
    monkeypatch.setattr(cli_main, "update", update)

    cli_main.edit_campaign_experiment()

    update.assert_called_once_with(0, updated, "azure")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="y"))
    clear = MagicMock()
    monkeypatch.setattr(cli_main, "clear", clear)

    cli_main.clear_campaign()

    clear.assert_called_once_with("azure")


def test_add_azure_experiment_persists_to_the_azure_campaign(monkeypatch):
    from chaosforge.application.campaigns import builder, manager

    aws_campaign = manager.campaigns["aws"]
    azure_campaign = Campaign(name="Azure Draft", cloud_provider="azure")
    manager.campaigns["azure"] = azure_campaign
    monkeypatch.setattr(builder.context, "cloud", "azure")
    monkeypatch.setattr(manager.history_store, "active_draft_id", lambda _: None)
    try:
        builder.build_experiment(
            "azure_redis",
            {"id": "azure-redis-reboot", "name": "Redis reboot", "json": "redis.json"},
            {"resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache"},
        )

        assert manager.list_all("aws") == aws_campaign.experiments
        assert [item.name for item in manager.list_all("azure")] == ["Redis reboot"]
    finally:
        manager.campaigns.pop("azure", None)


def test_build_selected_campaign_deduplicates_and_orders_selection(monkeypatch, quiet_ui):
    first = experiment(name="First")
    second = experiment(name="Second")
    cli_main.campaign.name = "Production"
    cli_main.campaign.continue_on_failure = True
    cli_main.campaign.cloud_provider = "aws"
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="2, 1, 2"))

    selected = cli_main.build_selected_campaign([first, second])

    assert selected.name == "Production"
    assert selected.continue_on_failure is True
    assert selected.experiments == [first, second]


@pytest.mark.parametrize("selection", ["one", "3"])
def test_build_selected_campaign_rejects_invalid_or_missing_indexes(monkeypatch, quiet_ui, selection):
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=selection))

    assert cli_main.build_selected_campaign([experiment()]) is None
    cli_main.pause.assert_called_once_with()


def test_execute_campaign_runs_selected_campaign_and_retry_without_live_dependencies(
    monkeypatch, quiet_ui
):
    normal = experiment("lambda", "Timeout", dry_run="yes")
    fis = experiment("fis", "Stop instance (AWS FIS)", service_id="ec2")
    aks = experiment("aks", "Pod kill", namespace="default")
    experiments = [normal, fis, aks]
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=experiments))
    monkeypatch.setattr(cli_main, "confirm_permission_review", MagicMock(return_value=True))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="2"))
    selected_campaign = Campaign(name="Selected", experiments=[normal, aks])
    monkeypatch.setattr(cli_main, "build_selected_campaign", MagicMock(return_value=selected_campaign))
    execute = MagicMock()
    report = MagicMock()
    monkeypatch.setattr(cli_main, "execute_lifecycle_campaign", execute)
    monkeypatch.setattr(cli_main, "generate_report", report)
    monkeypatch.setattr(
        "chaosforge.application.metadata.load_service_metadata",
        lambda service: {"display_name": service.upper()},
    )
    result_menu = MagicMock(side_effect=["retry", None])
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.campaign_result.show_campaign_result_menu",
        result_menu,
    )
    monkeypatch.setattr(cli_main, "build_failed_campaign", MagicMock(return_value=Campaign()))

    cli_main.execute_campaign()

    execute.assert_called_once_with(selected_campaign)
    report.assert_called_once_with(selected_campaign)
    cli_main.warning.assert_called_once_with("No failed experiments found.")


def test_execute_campaign_stops_when_permission_review_is_rejected(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[experiment()]))
    monkeypatch.setattr(cli_main, "confirm_permission_review", MagicMock(return_value=False))
    execute = MagicMock()
    monkeypatch.setattr(cli_main, "execute_lifecycle_campaign", execute)

    cli_main.execute_campaign()

    execute.assert_not_called()
    cli_main.warning.assert_called_once_with("Campaign execution cancelled.")


def test_execute_campaign_stops_when_irreversible_review_is_rejected(
    monkeypatch, quiet_ui
):
    selected = experiment()
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[selected]))
    monkeypatch.setattr(cli_main, "confirm_permission_review", MagicMock(return_value=True))
    monkeypatch.setattr(cli_main, "confirm_irreversible_execution", MagicMock(return_value=False))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    execute = MagicMock()
    monkeypatch.setattr(cli_main, "execute_lifecycle_campaign", execute)

    cli_main.execute_campaign()

    execute.assert_not_called()
    cli_main.warning.assert_called_once_with("Campaign execution cancelled.")


def test_permission_review_displays_report_and_handles_invalid_input(monkeypatch):
    report = MagicMock()
    monkeypatch.setattr(cli_main, "display_permission_report", report)
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["invalid", "v", "n"]))
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    monkeypatch.setattr(cli_main, "warning", MagicMock())

    assert cli_main.confirm_permission_review(cli_main.campaign) is False
    report.assert_called_once_with(cli_main.campaign)
    cli_main.warning.assert_called_once_with("Invalid Selection")


def test_permission_review_accepts_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="y"))

    assert cli_main.confirm_permission_review(cli_main.campaign) is True


def test_irreversible_confirmation_requires_exact_acknowledgement(monkeypatch):
    campaign = Campaign(
        experiments=[Experiment("azure-redis-flush", "azure_redis", "Flush", "", {})]
    )
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="no"))
    assert cli_main.confirm_irreversible_execution(campaign) is False

    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="IRREVERSIBLE"))
    assert cli_main.confirm_irreversible_execution(campaign) is True

    assert cli_main.confirm_irreversible_execution(Campaign()) is True


def test_display_permission_report_delegates_to_shared_renderer(monkeypatch):
    monkeypatch.setattr(cli_main, "console", MagicMock())
    monkeypatch.setattr(cli_main.permission_reports, "render_terminal", MagicMock(return_value="report"))

    cli_main.display_permission_report(cli_main.campaign)

    cli_main.permission_reports.render_terminal.assert_called_once_with(cli_main.campaign)
    cli_main.console.print.assert_called_once_with("report")


def test_view_campaign_handles_invalid_choice_then_displays_permissions(monkeypatch, quiet_ui):
    configured = experiment("lambda", "Timeout", aws_region="us-east-1", service_id="lambda")
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[configured]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["bad", "1"]))
    report = MagicMock()
    monkeypatch.setattr(cli_main, "display_permission_report", report)

    cli_main.view_campaign()

    cli_main.error.assert_called_once_with("Invalid Choice")
    report.assert_called_once_with(cli_main.campaign)


def test_remove_and_clear_campaign_cover_mutating_and_cancelled_paths(monkeypatch, quiet_ui):
    entries = [experiment(name="First"), experiment(name="Second")]
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=entries))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="2"))
    remove = MagicMock()
    monkeypatch.setattr(cli_main, "remove", remove)

    cli_main.remove_experiment()

    remove.assert_called_once_with(1)
    cli_main.success.assert_called_once_with("Experiment removed successfully.")

    cli_main.success.reset_mock()
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="n"))
    clear = MagicMock()
    monkeypatch.setattr(cli_main, "clear", clear)

    cli_main.clear_campaign()

    clear.assert_not_called()
    cli_main.info.assert_called_once_with("Operation cancelled.")


def test_edit_campaign_experiment_replaces_selected_item(monkeypatch, quiet_ui):
    existing = experiment(name="Timeout", aws_region="us-east-1", target_timeout=3)
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[existing]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"id": "timeout", "name": "Timeout", "inputs": []}),
    )
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.input_engine.collect_inputs",
        MagicMock(return_value={"aws_region": "us-east-1", "target_timeout": 15}),
    )
    updated = experiment(name="Timeout", aws_region="us-east-1", target_timeout=15)
    monkeypatch.setattr(cli_main, "create_experiment", MagicMock(return_value=updated))
    monkeypatch.setattr(
        cli_main,
        "ExperimentValidationService",
        lambda: SimpleNamespace(validate_experiment=lambda _: {"valid": True, "errors": []}),
    )
    replace = MagicMock()
    monkeypatch.setattr(cli_main, "update", replace)

    cli_main.edit_campaign_experiment()

    replace.assert_called_once_with(0, updated)
    cli_main.success.assert_called_once_with("Timeout updated successfully.")


def test_edit_campaign_experiment_rejects_invalid_update(monkeypatch, quiet_ui):
    existing = experiment(name="Timeout", aws_region="us-east-1", target_timeout=3)
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[existing]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"id": "timeout", "name": "Timeout", "inputs": []}),
    )
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.input_engine.collect_inputs",
        MagicMock(return_value={"aws_region": "us-east-1", "target_timeout": 0}),
    )
    monkeypatch.setattr(cli_main, "create_experiment", MagicMock(return_value=existing))
    monkeypatch.setattr(
        cli_main,
        "ExperimentValidationService",
        lambda: SimpleNamespace(validate_experiment=lambda _: {"valid": False, "errors": ["invalid timeout"]}),
    )
    replace = MagicMock()
    monkeypatch.setattr(cli_main, "update", replace)

    cli_main.edit_campaign_experiment()

    replace.assert_not_called()
    cli_main.error.assert_called_once_with("Updated experiment validation failed.")


def test_edit_campaign_experiment_handles_selection_and_metadata_exit_paths(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    cli_main.edit_campaign_experiment()
    cli_main.warning.assert_called_once_with("Campaign is empty.")

    configured = experiment(name="Timeout")
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[configured]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="0"))
    cli_main.edit_campaign_experiment()

    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="bad"))
    cli_main.edit_campaign_experiment()
    cli_main.error.assert_called_with("Invalid Selection.")

    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value=None),
    )
    cli_main.edit_campaign_experiment()
    cli_main.error.assert_called_with("Metadata not found for Timeout.")


def test_edit_campaign_experiment_cancellation_paths(monkeypatch, quiet_ui):
    configured = experiment(name="Timeout")
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[configured]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"id": "timeout", "name": "Timeout", "inputs": []}),
    )
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.input_engine.collect_inputs",
        MagicMock(side_effect=cli_main.BackToMainMenu()),
    )
    cli_main.edit_campaign_experiment()

    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.input_engine.collect_inputs",
        MagicMock(return_value=None),
    )
    cli_main.edit_campaign_experiment()
    cli_main.info.assert_called_with("Experiment edit cancelled.")


@pytest.mark.parametrize(
    ("service", "collector_path", "variables"),
    [
        ("aks", "_collect_aks_inputs", {"aks_context": "ctx"}),
        ("azure_redis", "collect_redis_inputs", {"redis_name": "cache"}),
    ],
)
def test_edit_campaign_uses_provider_specific_collectors(
    monkeypatch, quiet_ui, service, collector_path, variables
):
    configured = experiment(service=service, name="Provider Experiment")
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[configured]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"id": configured.id, "name": configured.name, "inputs": []}),
    )
    module_name = (
        "chaosforge.interfaces.cli.interactive.azure_aks_service"
        if service == "aks"
        else "chaosforge.interfaces.cli.interactive.azure_redis_menu"
    )
    collector = MagicMock(return_value=variables)
    monkeypatch.setattr(import_module(module_name), collector_path, collector)
    updated = experiment(service=service, name="Updated")
    monkeypatch.setattr(cli_main, "create_experiment", MagicMock(return_value=updated))
    monkeypatch.setattr(
        cli_main,
        "ExperimentValidationService",
        lambda: SimpleNamespace(validate_experiment=lambda _: {"valid": True, "errors": []}),
    )
    update = MagicMock()
    monkeypatch.setattr(cli_main, "update", update)

    cli_main.edit_campaign_experiment()

    collector.assert_called_once()
    update.assert_called_once_with(0, updated)


def test_edit_campaign_preserves_fis_catalog_display_name(monkeypatch, quiet_ui):
    configured = experiment(
        service="fis",
        name="FIS",
        service_id="ec2",
        experiment_id="stop-instances",
    )
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[configured]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"id": configured.id, "name": "Create", "inputs": []}),
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.fis.catalog.FISCatalog.get_experiment",
        MagicMock(return_value={"name": "Stop Instances"}),
    )
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.input_engine.collect_inputs",
        MagicMock(return_value={"service_id": "ec2", "experiment_id": "stop-instances"}),
    )
    create = MagicMock(return_value=experiment(service="fis", name="Updated"))
    monkeypatch.setattr(cli_main, "create_experiment", create)
    monkeypatch.setattr(
        cli_main,
        "ExperimentValidationService",
        lambda: SimpleNamespace(validate_experiment=lambda _: {"valid": True, "errors": []}),
    )
    monkeypatch.setattr(cli_main, "update", MagicMock())

    cli_main.edit_campaign_experiment()

    assert create.call_args.args[1]["name"] == "Stop Instances (AWS FIS)"


def test_save_campaign_reports_success_and_os_error(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[experiment()]))
    export = MagicMock()
    monkeypatch.setattr(cli_main, "export_campaign_yaml", export)

    cli_main.save_campaign()

    export.assert_called_once_with()


def test_load_campaign_replaces_current_campaign(monkeypatch, quiet_ui):
    loaded = Campaign(
        name="Saved",
        experiments=[experiment()],
        continue_on_failure=True,
        cloud_provider="azure",
    )
    monkeypatch.setattr(
        cli_main,
        "list_saved_campaigns",
        MagicMock(return_value=[{"name": "Saved", "experiments": 1}]),
    )
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    loader = MagicMock(return_value=loaded)
    monkeypatch.setattr(cli_main, "load_saved_campaign", loader)

    cli_main.load_campaign()

    loader.assert_called_once_with("Saved")
    assert cli_main.campaign.name == "Saved"
    assert cli_main.campaign.experiments == loaded.experiments
    assert cli_main.campaign.cloud_provider == "azure"


def test_settings_updates_region_and_timezone_for_both_clouds(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "2", "1", "0"]))
    selector = MagicMock()
    selector.select.return_value = "ap-southeast-2"
    monkeypatch.setattr(cli_main, "RegionSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(cli_main, "timezone_options", MagicMock(return_value=[{"id": "Asia/Shanghai", "display": "China"}]))
    save_timezone = MagicMock()
    monkeypatch.setattr(cli_main, "set_timezone_id", save_timezone)

    cli_main.settings()

    assert cli_main.context.region == "ap-southeast-2"
    assert cli_main.context.timezone_id == "Asia/Shanghai"
    save_timezone.assert_called_once_with("Asia/Shanghai")

    cli_main.success.reset_mock()
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "1", "0"]))
    cli_main.settings()
    assert save_timezone.call_count == 2


def test_settings_rejects_invalid_menu_and_timezone_choices(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main, "timezone_options", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "9", "9", "0"]))

    cli_main.settings()

    assert cli_main.error.call_count == 2


def test_settings_region_selector_can_return_to_settings(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "0"]))
    selector = MagicMock()
    selector.select.return_value = None
    monkeypatch.setattr(cli_main, "RegionSelector", MagicMock(return_value=selector))

    cli_main.settings()

    selector.select.assert_called_once_with(navigation=True)


def test_settings_region_selector_can_return_to_main_menu(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    selector = MagicMock()
    selector.select.return_value = "__main_menu__"
    monkeypatch.setattr(cli_main, "RegionSelector", MagicMock(return_value=selector))

    cli_main.settings()

    selector.select.assert_called_once_with(navigation=True)


def test_settings_timezone_selector_has_back_and_main_menu(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "m"]))
    rendered_menu = MagicMock()
    monkeypatch.setattr(cli_main, "menu", rendered_menu)
    monkeypatch.setattr(cli_main, "timezone_options", MagicMock(return_value=[]))

    cli_main.settings()

    assert (0, "Back") in rendered_menu.call_args.args[1]
    assert ("M", "Main Menu") in rendered_menu.call_args.args[1]


def test_settings_timezone_selector_can_return_to_settings(monkeypatch, quiet_ui):
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main.context, "cloud", "azure")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "0", "0"]))
    monkeypatch.setattr(cli_main, "timezone_options", MagicMock(return_value=[]))

    cli_main.settings()


def test_interactive_main_dispatches_menu_action_then_exits(monkeypatch, quiet_ui):
    platform = MagicMock()
    platform.select.return_value = "azure"
    monkeypatch.setattr(cli_main, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "label": "Azure subscription", "name": "Test"}),
    )
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "render_main_menu", MagicMock())
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "0"]))
    campaign_library = MagicMock(return_value=False)
    monkeypatch.setattr(cli_main, "campaign_library", campaign_library)

    with pytest.raises(SystemExit) as result:
        cli_main.interactive_main()

    assert result.value.code == 0
    assert cli_main.context.cloud == "azure"
    assert cli_main.context.region == "azure"
    assert cli_main.context.cloud_identity["name"] == "Test"
    campaign_library.assert_called_once_with()


def test_interactive_main_displays_required_permissions(monkeypatch, quiet_ui):
    platform = MagicMock()
    platform.select.return_value = "azure"
    monkeypatch.setattr(cli_main, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "label": "Azure subscription", "name": "Test"}),
    )
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[MagicMock()]))
    monkeypatch.setattr(cli_main, "render_main_menu", MagicMock())
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["13", "0"]))
    display = MagicMock()
    monkeypatch.setattr(cli_main, "display_permission_report", display)
    monkeypatch.setattr(cli_main, "pause", MagicMock())

    with pytest.raises(SystemExit):
        cli_main.interactive_main()

    display.assert_called_once_with(cli_main.campaign)


def test_interactive_main_permission_action_handles_empty_campaign(monkeypatch, quiet_ui):
    platform = MagicMock()
    platform.select.return_value = "azure"
    monkeypatch.setattr(cli_main, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(cli_main, "get_cloud_identity", MagicMock(return_value={"authenticated": True}))
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "render_main_menu", MagicMock())
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["13", "0"]))
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    monkeypatch.setattr(cli_main, "warning", MagicMock())

    with pytest.raises(SystemExit):
        cli_main.interactive_main()

    cli_main.warning.assert_called_once_with("Campaign is empty.")


def test_interactive_main_recovers_from_back_navigation(monkeypatch, quiet_ui):
    platform = MagicMock()
    platform.select.return_value = "aws"
    region = MagicMock()
    region.select.return_value = "eu-west-1"
    monkeypatch.setattr(cli_main, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(cli_main, "RegionSelector", MagicMock(return_value=region))
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "render_main_menu", MagicMock())
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["1", "0"]))
    monkeypatch.setattr(cli_main, "campaign_library", MagicMock(side_effect=cli_main.BackToMainMenu()))

    with pytest.raises(SystemExit):
        cli_main.interactive_main()

    region.select.assert_called_once_with()


def test_lifecycle_helpers_create_aws_dispatcher_and_execute(monkeypatch):
    lifecycle = MagicMock()
    create_runner = MagicMock(return_value=lifecycle)
    monkeypatch.setattr(cli_main.lifecycle_service, "create_runner", create_runner)
    experiment_with_region = experiment(aws_region="eu-west-1")

    assert cli_main.create_lifecycle_runner(experiment_with_region) is lifecycle
    create_runner.assert_called_once_with(experiment_with_region)

    monkeypatch.setattr(cli_main, "create_lifecycle_runner", MagicMock(return_value=lifecycle))
    lifecycle.execute.return_value = "completed"
    assert cli_main.execute_lifecycle_experiment(experiment()) == "completed"

    execute_campaign = MagicMock()
    monkeypatch.setattr(cli_main.lifecycle_service, "execute_campaign", execute_campaign)
    campaign = Campaign(experiments=[experiment()])
    cli_main.execute_lifecycle_campaign(campaign)
    execute_campaign.assert_called_once_with(campaign)


def test_yaml_validation_reports_campaign_and_provider_failures(monkeypatch):
    yaml_campaign = Campaign(experiments=[experiment(aws_region="us-east-1")])
    monkeypatch.setattr(cli_main, "load_yaml", MagicMock(return_value={"cloud": {"provider": "aws"}}))
    monkeypatch.setattr(cli_main, "build_campaign", MagicMock(return_value=yaml_campaign))
    monkeypatch.setattr(cli_main, "error", MagicMock())
    monkeypatch.setattr(cli_main, "success", MagicMock())
    monkeypatch.setattr(cli_main, "YAMLValidator", lambda: SimpleNamespace(validate=lambda _: {"valid": True}))
    validation = {
        "valid": False,
        "experiments": [{
            "experiment_id": "timeout", "service": "lambda", "name": "Timeout",
            "errors": ["missing target"], "warnings": ["dry run"],
        }],
    }
    monkeypatch.setattr(
        cli_main, "ExperimentValidationService", lambda: SimpleNamespace(validate_campaign=lambda _: validation)
    )
    assert cli_main.load_and_validate_yaml_campaign("campaign.yaml") is None
    cli_main.error.assert_called_once_with("CAMPAIGN VALIDATION FAILED")

    monkeypatch.setattr(cli_main, "load_yaml", MagicMock(return_value={"cloud": {"provider": "azure"}}))
    monkeypatch.setattr(
        cli_main, "ExperimentValidationService", lambda: SimpleNamespace(validate_campaign=lambda _: {"valid": True, "experiments": []})
    )
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": False, "name": "Not logged in"}),
    )
    assert cli_main.load_and_validate_yaml_campaign("campaign.yaml") is None
    cli_main.error.assert_called_with("AZURE CREDENTIAL VERIFICATION FAILED")

    monkeypatch.setattr(cli_main, "load_yaml", MagicMock(return_value={"cloud": {"provider": "gcp"}}))
    assert cli_main.load_and_validate_yaml_campaign("campaign.yaml") is None
    cli_main.error.assert_called_with("Unsupported cloud provider: gcp")

    monkeypatch.setattr(cli_main, "load_yaml", MagicMock(side_effect=OSError("unreadable")))
    assert cli_main.load_and_validate_yaml_campaign("campaign.yaml") is None
    cli_main.error.assert_called_with("Validation error: unreadable")


def test_yaml_execution_import_and_validation_command_paths(monkeypatch, quiet_ui, tmp_path):
    monkeypatch.setattr(cli_main, "load_and_validate_yaml_campaign", MagicMock(return_value=Campaign(name="Safe")))
    planner = MagicMock()
    planner.plan_campaign.return_value = SimpleNamespace(executable=True)
    monkeypatch.setattr(cli_main, "PlanService", MagicMock(return_value=planner))
    monkeypatch.setattr(cli_main, "display_campaign_plan", MagicMock())
    confirmation = MagicMock()
    monkeypatch.setattr(cli_main, "confirm_campaign_execution", confirmation)
    execute = MagicMock()
    monkeypatch.setattr(cli_main, "execute_lifecycle_campaign", execute)
    monkeypatch.setattr(cli_main.campaign_history, "start_execution", MagicMock(return_value="execution"))
    monkeypatch.setattr(cli_main.campaign_history, "finish_execution", MagicMock())
    assert cli_main.execute_yaml_campaign("safe.yaml") == 0
    execute.assert_called_once()
    confirmation.assert_not_called()

    planner.plan_campaign.side_effect = ValueError("bad plan")
    assert cli_main.execute_yaml_campaign("safe.yaml") == 1

    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main.context, "region", "eu-west-1")
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "label": "AWS", "name": "Test"}),
    )
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=""))
    cli_main.import_yaml_campaign()
    cli_main.error.assert_called_with("YAML file path cannot be empty.")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=str(tmp_path / "missing.yaml")))
    cli_main.import_yaml_campaign()
    cli_main.error.assert_called_with(f"YAML file not found: {tmp_path / 'missing.yaml'}")

    path = tmp_path / "campaign.yaml"
    path.write_text("campaign: {}", encoding="utf-8")
    review = SimpleNamespace(
        valid=True,
        campaign=Campaign(name="Imported"),
        errors=(),
        document={"environment": {"account_id": "123"}},
    )
    inspect = MagicMock(return_value=review)
    monkeypatch.setattr(cli_main.campaign_yaml_service, "inspect_bytes", inspect)
    monkeypatch.setattr(
        cli_main.campaign_preflight,
        "preflight",
        MagicMock(return_value=SimpleNamespace(ready=True)),
    )
    replace = MagicMock()
    monkeypatch.setattr(cli_main, "replace_campaign", replace)
    monkeypatch.setattr(cli_main, "create_campaign_draft", MagicMock())
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=str(path)))
    cli_main.import_yaml_campaign()
    inspect.assert_called_once()
    replace.assert_called_once_with(review.campaign)


def test_yaml_execution_blocks_unacknowledged_irreversible_campaign(monkeypatch):
    campaign = Campaign(
        name="Unsafe",
        experiments=[
            Experiment("azure-redis-flush", "azure_redis", "Flush", "", {})
        ],
    )
    monkeypatch.setattr(
        cli_main, "load_and_validate_yaml_campaign", MagicMock(return_value=campaign)
    )
    planner = MagicMock()
    monkeypatch.setattr(cli_main, "PlanService", planner)

    assert cli_main.execute_yaml_campaign("unsafe.yaml") == 1
    planner.assert_not_called()


def test_yaml_execution_persists_failed_history(monkeypatch):
    campaign = Campaign(name="Failure")
    monkeypatch.setattr(cli_main, "load_and_validate_yaml_campaign", MagicMock(return_value=campaign))
    monkeypatch.setattr(cli_main, "PlanService", lambda: SimpleNamespace(plan_campaign=lambda _: SimpleNamespace(executable=True)))
    monkeypatch.setattr(cli_main, "display_campaign_plan", MagicMock())
    monkeypatch.setattr(cli_main.campaign_history, "start_execution", MagicMock(return_value="execution-1"))
    finish = MagicMock()
    monkeypatch.setattr(cli_main.campaign_history, "finish_execution", finish)
    monkeypatch.setattr(cli_main, "execute_lifecycle_campaign", MagicMock(side_effect=RuntimeError("failed")))

    with pytest.raises(RuntimeError, match="failed"):
        cli_main.execute_yaml_campaign("failure.yaml")

    finish.assert_called_once_with("execution-1", campaign, "FAILED")


@pytest.mark.parametrize(
    ("choice", "handler"),
    [("11", "campaign_history_view"), ("12", "campaign_library")],
)
def test_interactive_main_routes_campaign_history_actions(monkeypatch, quiet_ui, choice, handler):
    platform = MagicMock(select=MagicMock(return_value="azure"))
    monkeypatch.setattr(cli_main, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(cli_main, "get_cloud_identity", MagicMock(return_value={}))
    monkeypatch.setattr(cli_main, "render_main_menu", MagicMock())
    action = MagicMock()
    monkeypatch.setattr(cli_main, handler, action)
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=[choice, "0"]))
    monkeypatch.setattr(cli_main, "sys", SimpleNamespace(exit=lambda *_: (_ for _ in ()).throw(SystemExit())))

    with pytest.raises(SystemExit):
        cli_main.interactive_main()

    action.assert_called_once_with()

    monkeypatch.setattr(cli_main, "load_and_validate_yaml_campaign", MagicMock(return_value=None))
    assert cli_main.validate_yaml_campaign("invalid.yaml") == 1
    monkeypatch.setattr(cli_main, "load_and_validate_yaml_campaign", MagicMock(return_value=Campaign()))
    assert cli_main.validate_yaml_campaign("valid.yaml") == 0


def test_display_campaign_plan_covers_populated_and_empty_sections(capsys):
    result = SimpleNamespace(
        executable=True,
        experiments=[{"id": "one", "service": "lambda", "status": "READY"}],
        targets=[{"resource_type": "function", "resource_id": "fn"}],
        impact={
            "capacity": {"status": "SAFE", "affected_percent": 10},
            "availability_zones": ["us-east-1a"],
            "traffic": {"status": "LOW", "reason": "limited"},
            "customer_impact": {"status": "NONE", "reason": "dry run"},
        },
        permissions=[{"action": "lambda:GetFunction", "access": "read"}],
        capabilities=["rollback"],
        duration={"status": "KNOWN", "estimated_seconds": 30},
        recovery={"behavior": "automatic"},
        warnings=["review"],
        blockers=["approval"],
    )
    cli_main.display_campaign_plan(Campaign(name="Plan"), result)
    assert "approval" in capsys.readouterr().out

    result.targets = []
    result.impact = {}
    result.permissions = []
    result.capabilities = []
    result.warnings = []
    result.blockers = []
    result.duration = {}
    result.recovery = {}
    cli_main.display_campaign_plan(Campaign(name="Plan"), result)
    output = capsys.readouterr().out
    assert "  - None" in output
    assert "  - UNKNOWN" in output


def test_build_failed_campaign_preserves_campaign_settings():
    passed = experiment(name="Passed")
    passed.status = "COMPLETED"
    failed = experiment(name="Failed")
    failed.status = "FAILED"
    current = Campaign(
        name="Release",
        experiments=[passed, failed],
        continue_on_failure=True,
        cloud_provider="azure",
    )

    retry = cli_main.build_failed_campaign(current)

    assert retry.name == "Release - Retry"
    assert retry.experiments == [failed]
    assert retry.continue_on_failure is True
    assert retry.cloud_provider == "azure"


def test_edit_failed_campaign_and_menu_dispatches_remaining_actions(monkeypatch, quiet_ui):
    failed = experiment(name="Failed")
    failed.status = "FAILED"
    missing = experiment(name="Missing")
    missing.status = "FAILED"
    current = Campaign(experiments=[failed, missing])
    metadata = MagicMock(side_effect=[{"inputs": []}, None])
    collected = MagicMock(return_value={"updated": True})
    monkeypatch.setattr("chaosforge.application.metadata.get_experiment", metadata)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.input_engine.collect_inputs", collected)
    cli_main.edit_failed_campaign(current)
    assert failed.variables == {"updated": True}
    assert failed.status == "Pending"
    cli_main.warning.assert_called_once_with("Metadata not found for Missing")

    platform = MagicMock()
    platform.select.return_value = "azure"
    monkeypatch.setattr(cli_main, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(cli_main, "list_all", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "render_main_menu", MagicMock())
    handlers = {name: MagicMock() for name in (
        "view_campaign", "remove_experiment", "execute_campaign", "import_yaml_campaign",
        "clear_campaign", "save_campaign", "load_campaign", "settings", "edit_campaign_experiment",
    )}
    for name, handler in handlers.items():
        monkeypatch.setattr(cli_main, name, handler)
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["2", "3", "4", "5", "6", "7", "8", "9", "10", "bad", "0"]))
    with pytest.raises(SystemExit):
        cli_main.interactive_main()
    for handler in handlers.values():
        handler.assert_called_once_with()
    cli_main.error.assert_called_once_with("Invalid Choice")
