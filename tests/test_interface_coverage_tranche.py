"""Isolated coverage for CLI, Azure setup, and Flask interface boundaries."""

import json
import runpy
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli import main as cli_main
from chaosforge.interfaces.cli.interactive import platform_selector
from chaosforge.interfaces.web import app as web_app


@pytest.fixture
def client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


def test_yaml_validation_covers_schema_campaign_and_credential_outcomes(monkeypatch):
    monkeypatch.setattr(cli_main, "load_yaml", lambda _: {"cloud": {"provider": "aws"}})
    monkeypatch.setattr(cli_main, "error", MagicMock())
    monkeypatch.setattr(cli_main, "success", MagicMock())

    monkeypatch.setattr(cli_main, "YAMLValidator", lambda: SimpleNamespace(validate=lambda _: {"valid": False, "errors": ["missing name"]}))
    assert cli_main.load_and_validate_yaml_campaign("bad.yaml") is None
    cli_main.error.assert_called_with("YAML SCHEMA VALIDATION FAILED")

    campaign = SimpleNamespace(experiments=[])
    monkeypatch.setattr(cli_main, "YAMLValidator", lambda: SimpleNamespace(validate=lambda _: {"valid": True}))
    monkeypatch.setattr(cli_main, "build_campaign", lambda _: campaign)
    monkeypatch.setattr(
        cli_main,
        "ExperimentValidationService",
        lambda: SimpleNamespace(validate_campaign=lambda _: {"valid": True, "experiments": []}),
    )
    assert cli_main.load_and_validate_yaml_campaign("no-region.yaml") is None
    cli_main.error.assert_called_with("AWS CREDENTIAL VERIFICATION FAILED")

    experiment = SimpleNamespace(variables={"aws_region": "us-east-1"})
    campaign.experiments = [experiment]
    discovery = MagicMock()
    discovery.verify_aws_credentials.return_value = {"account_id": "123", "region": "us-east-1"}
    monkeypatch.setattr(cli_main, "AWSDiscovery", MagicMock(return_value=discovery))
    assert cli_main.load_and_validate_yaml_campaign("valid.yaml") is campaign
    discovery.verify_aws_credentials.assert_called_once_with()


def test_yaml_validation_rejects_failed_aws_and_azure_target_preflight(monkeypatch):
    campaign = SimpleNamespace(
        experiments=[SimpleNamespace(variables={"aws_region": "us-east-1"})]
    )
    monkeypatch.setattr(
        cli_main,
        "YAMLValidator",
        lambda: SimpleNamespace(validate=lambda _: {"valid": True}),
    )
    monkeypatch.setattr(cli_main, "build_campaign", lambda _: campaign)
    monkeypatch.setattr(
        cli_main,
        "ExperimentValidationService",
        lambda: SimpleNamespace(
            validate_campaign=lambda _: {"valid": True, "experiments": []}
        ),
    )
    monkeypatch.setattr(cli_main, "error", MagicMock())
    monkeypatch.setattr(
        cli_main,
        "AWSDiscovery",
        MagicMock(
            return_value=SimpleNamespace(
                verify_aws_credentials=lambda: {
                    "account_id": "123",
                    "region": "us-east-1",
                }
            )
        ),
    )
    preflight = MagicMock(return_value=SimpleNamespace(ready=False, errors=["missing target"]))
    monkeypatch.setattr(cli_main.campaign_preflight, "preflight", preflight)

    monkeypatch.setattr(
        cli_main,
        "load_yaml",
        lambda _: {"cloud": {"provider": "aws"}, "environment": {}},
    )
    assert cli_main.load_and_validate_yaml_campaign("aws.yaml") is None
    cli_main.error.assert_called_with("CAMPAIGN TARGET PREFLIGHT FAILED")

    campaign.experiments = []
    monkeypatch.setattr(
        cli_main,
        "load_yaml",
        lambda _: {"cloud": {"provider": "azure"}},
    )
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "name": "Engineering"},
    )
    assert cli_main.load_and_validate_yaml_campaign("azure.yaml") is None
    assert preflight.call_count == 2


def test_refresh_failed_aks_pod_targets_handles_missing_and_replacement(monkeypatch):
    from chaosforge.providers.azure.components.aks import discovery as aks_discovery

    existing = SimpleNamespace(
        service="aks",
        status="FAILED",
        variables={"target_mode": "pod", "aks_context": "ctx", "namespace": "apps", "pod": "live"},
    )
    missing = SimpleNamespace(
        service="aks",
        status="FAILED",
        variables={"target_mode": "pod", "aks_context": "ctx", "namespace": "apps", "pod": "gone"},
    )
    invalid = SimpleNamespace(
        service="aks",
        status="FAILED",
        variables={"target_mode": "pod", "aks_context": "ctx", "namespace": "apps", "pod": "old"},
    )
    replacement = SimpleNamespace(
        service="aks",
        status="FAILED",
        variables={"target_mode": "pod", "aks_context": "ctx", "namespace": "apps", "pod": "stale"},
    )
    discovery = MagicMock()
    discovery.list_pods.side_effect = [["live"], [], ["new-pod"], ["fresh-pod"]]
    discovery.get_pod_label.return_value = ("app", "api")
    discovery.get_deployment_for_pod.return_value = "api-deployment"
    monkeypatch.setattr(aks_discovery, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(side_effect=["bad", "1"]))
    monkeypatch.setattr(cli_main, "menu", MagicMock())
    monkeypatch.setattr(cli_main, "warning", MagicMock())
    monkeypatch.setattr(cli_main, "success", MagicMock())

    cli_main.refresh_failed_aks_pod_targets(
        SimpleNamespace(experiments=[existing, missing, invalid, replacement])
    )

    assert existing.status == "FAILED"
    assert missing.status == "SKIPPED"
    assert invalid.status == "SKIPPED"
    assert replacement.variables == {
        "target_mode": "pod",
        "aks_context": "ctx",
        "namespace": "apps",
        "pod": "fresh-pod",
        "deployment": "fresh-pod",
        "label_key": "app",
        "label_val": "api",
        "owning_deployment": "api-deployment",
    }


def test_campaign_environment_uses_azure_subscription_identity(monkeypatch):
    campaign = SimpleNamespace(cloud_provider="azure")
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"subscription_id": "sub-1", "name": "Engineering"},
    )

    assert web_app._campaign_environment(campaign) == {
        "subscription_id": "sub-1",
        "subscription_name": "Engineering",
    }


def test_cli_module_entrypoint_runs_main(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["chaosforge", "validate", "missing.yaml"])

    with pytest.warns(RuntimeWarning), pytest.raises(SystemExit) as exit_info:
        runpy.run_module("chaosforge.interfaces.cli.main", run_name="__main__")

    assert exit_info.value.code == 1


@pytest.mark.parametrize("skip_on_refresh", [1, 2])
def test_campaign_retry_reports_when_no_failed_experiments_remain_eligible(
    monkeypatch, skip_on_refresh
):
    failed = SimpleNamespace(
        name="Pod kill", service="aks", status="FAILED", variables={}
    )
    monkeypatch.setattr(cli_main.campaign, "experiments", [failed])
    monkeypatch.setattr(cli_main.campaign, "cloud_provider", "azure")
    monkeypatch.setattr(cli_main, "clear_screen", MagicMock())
    monkeypatch.setattr(cli_main, "print_banner", MagicMock())
    monkeypatch.setattr(cli_main, "dashboard", MagicMock())
    monkeypatch.setattr(cli_main, "title", MagicMock())
    monkeypatch.setattr(cli_main, "console", MagicMock())
    monkeypatch.setattr(cli_main, "list_all", lambda: [failed])
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(cli_main, "generate_report", MagicMock())
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    monkeypatch.setattr(cli_main, "warning", MagicMock())
    monkeypatch.setattr(cli_main, "execute_lifecycle_campaign", MagicMock())
    monkeypatch.setattr(cli_main, "confirm_permission_review", MagicMock(return_value=True))
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.campaign_result.show_campaign_result_menu",
        MagicMock(side_effect=["retry", None]),
    )
    refresh_calls = 0

    def refresh(campaign):
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls == skip_on_refresh:
            campaign.experiments[0].status = "SKIPPED"

    monkeypatch.setattr(cli_main, "refresh_failed_aks_pod_targets", refresh)

    cli_main.execute_campaign()

    cli_main.warning.assert_called_with("No failed experiments remain eligible for retry.")


def test_yaml_execution_and_planning_stop_on_errors_or_cancellation(monkeypatch):
    monkeypatch.setattr(cli_main, "error", MagicMock())
    monkeypatch.setattr(cli_main, "load_and_validate_yaml_campaign", lambda _: None)
    assert cli_main.execute_yaml_campaign("invalid.yaml") == 1
    assert cli_main.plan_yaml_campaign("invalid.yaml") == 1

    campaign = SimpleNamespace(name="Safe campaign")
    plan = SimpleNamespace(executable=False)
    monkeypatch.setattr(cli_main, "load_and_validate_yaml_campaign", lambda _: campaign)
    monkeypatch.setattr(cli_main, "PlanService", lambda: SimpleNamespace(plan_campaign=lambda _: plan))
    assert cli_main.execute_yaml_campaign("blocked.yaml") == 1

    plan.executable = True
    monkeypatch.setattr(cli_main, "display_campaign_plan", MagicMock())
    execute = MagicMock()
    monkeypatch.setattr(cli_main, "execute_lifecycle_campaign", execute)
    monkeypatch.setattr(cli_main.campaign_history, "start_execution", MagicMock(return_value="execution"))
    monkeypatch.setattr(cli_main.campaign_history, "finish_execution", MagicMock())
    assert cli_main.execute_yaml_campaign("non-interactive.yaml") == 0
    execute.assert_called_once()

    monkeypatch.setattr(cli_main, "PlanService", lambda: SimpleNamespace(plan_campaign=lambda _: (_ for _ in ()).throw(RuntimeError("planner unavailable"))))
    assert cli_main.plan_yaml_campaign("failure.yaml") == 1


def test_platform_cache_and_azure_setup_failure_paths_cleanup_state(monkeypatch, tmp_path):
    cache_file = tmp_path / "azure.json"
    monkeypatch.setattr(platform_selector, "_AZURE_CACHE_FILE", str(cache_file))
    platform_selector._save_azure_cache({"subscription_id": "sub"})
    assert platform_selector._load_azure_cache() == {"subscription_id": "sub"}
    cache_file.write_text("not json", encoding="utf-8")
    assert platform_selector._load_azure_cache() is None

    selector = platform_selector.PlatformSelector()
    monkeypatch.setattr(platform_selector, "title", MagicMock())
    monkeypatch.setattr(platform_selector, "console", MagicMock())
    monkeypatch.setattr(platform_selector, "error", MagicMock())
    monkeypatch.setattr(platform_selector, "prompt", MagicMock(return_value=""))
    assert selector._prompt_azure_details() is False

    monkeypatch.setattr(platform_selector, "prompt", MagicMock(return_value="sub"))
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda _: nullcontext())
    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError()))
    assert selector._prompt_azure_details() is False
    assert platform_selector.context.azure_subscription is None if hasattr(platform_selector, "context") else True


def test_platform_loads_complete_cache_and_selects_existing_cluster_context(monkeypatch):
    selector = platform_selector.PlatformSelector()
    context = __import__("chaosforge.interfaces.cli.session", fromlist=["context"]).context
    original = vars(context).copy()
    try:
        monkeypatch.setattr(
            platform_selector,
            "_load_azure_cache",
            lambda: {
                "subscription_id": "sub-12345678",
                "account_name": "Subscription",
                "resource_group": "group",
                "cluster_name": "cluster",
                "location": "westus",
                "kube_context": "cluster-context",
            },
        )
        monkeypatch.setattr(
            "chaosforge.providers.azure.discovery.resolve_subscription_id",
            lambda _: "sub-12345678",
        )
        selector._load_cached_azure_context()
        assert context.aks_kube_context == "cluster-context"

        monkeypatch.setattr(platform_selector, "title", MagicMock())
        monkeypatch.setattr(platform_selector, "console", MagicMock())
        monkeypatch.setattr(platform_selector, "error", MagicMock())
        monkeypatch.setattr(platform_selector, "info", MagicMock())
        monkeypatch.setattr(platform_selector, "_save_azure_cache", MagicMock())
        monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda _: nullcontext())
        monkeypatch.setattr(platform_selector, "prompt", MagicMock(side_effect=["sub-12345678", "1", "1"]))
        runs = [
            SimpleNamespace(returncode=0, stdout=json.dumps({"name": "Subscription"}), stderr=""),
            SimpleNamespace(returncode=0, stdout=json.dumps([{"name": "cluster", "resourceGroup": "group", "location": "westus"}]), stderr=""),
        ]
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=runs))
        kubernetes_helpers = ModuleType("chaosforge.providers.azure.components.aks.kubernetes")
        kubernetes_helpers.list_kube_contexts = lambda: ["cluster-context"]
        monkeypatch.setitem(sys.modules, "chaosforge.providers.azure.components.aks.kubernetes", kubernetes_helpers)

        assert selector._prompt_azure_details() is True
        assert context.aks_kube_context == "cluster-context"
    finally:
        vars(context).clear()
        vars(context).update(original)


def test_platform_azure_setup_removes_temporary_context_at_process_exit(monkeypatch):
    selector = platform_selector.PlatformSelector()
    context = __import__("chaosforge.interfaces.cli.session", fromlist=["context"]).context
    original = vars(context).copy()
    try:
        monkeypatch.setattr(platform_selector, "title", MagicMock())
        monkeypatch.setattr(platform_selector, "console", MagicMock())
        monkeypatch.setattr(platform_selector, "error", MagicMock())
        monkeypatch.setattr(platform_selector, "info", MagicMock())
        monkeypatch.setattr(platform_selector, "_save_azure_cache", MagicMock())
        register = MagicMock()
        monkeypatch.setattr(platform_selector.atexit, "register", register)
        monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda _: nullcontext())
        monkeypatch.setattr(platform_selector, "prompt", MagicMock(side_effect=["sub-12345678", "1", "0", "n"]))
        runs = [
            SimpleNamespace(returncode=0, stdout=json.dumps({"name": "Subscription"}), stderr=""),
            SimpleNamespace(returncode=0, stdout=json.dumps([{"name": "cluster", "resourceGroup": "group", "location": "westus"}]), stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]
        monkeypatch.setattr("subprocess.run", MagicMock(side_effect=runs))
        delete = MagicMock(return_value=True)
        kubernetes_helpers = ModuleType(
            "chaosforge.providers.azure.components.aks.kubernetes"
        )
        kubernetes_helpers.list_kube_contexts = list
        kubernetes_helpers.delete_kube_context = delete
        monkeypatch.setitem(
            sys.modules,
            "chaosforge.providers.azure.components.aks.kubernetes",
            kubernetes_helpers,
        )

        assert selector._prompt_azure_details() is True
        delete.assert_not_called()
        register.assert_called_once_with(platform_selector._remove_kube_context, "cluster")
        assert context.aks_kube_context == "cluster"
        cached = platform_selector._save_azure_cache.call_args.args[0]
        assert cached["kube_context"] is None
    finally:
        vars(context).clear()
        vars(context).update(original)


def test_cached_missing_kube_context_refreshes_credentials(monkeypatch):
    selector = platform_selector.PlatformSelector()
    context = __import__("chaosforge.interfaces.cli.session", fromlist=["context"]).context
    original = vars(context).copy()
    try:
        context.azure_subscription = "sub"
        context.azure_account_name = "Subscription"
        context.azure_resource_group = "group"
        context.aks_cluster_name = "cluster"
        context.azure_location = "westus"
        context.aks_kube_context = "stale-context"

        monkeypatch.setattr(
            "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
            lambda: ["other-context"],
        )
        run = MagicMock(return_value=SimpleNamespace(returncode=0, stderr=""))
        monkeypatch.setattr(platform_selector.subprocess, "run", run)
        save = MagicMock()
        monkeypatch.setattr(platform_selector, "_save_azure_cache", save)
        monkeypatch.setattr(platform_selector, "info", MagicMock())

        assert selector.ensure_azure_kube_context() is True
        assert context.aks_kube_context == "cluster"
        run.assert_called_once()
        save.assert_called_once()
    finally:
        vars(context).clear()
        vars(context).update(original)


def test_cached_missing_kube_context_reports_refresh_failure(monkeypatch):
    selector = platform_selector.PlatformSelector()
    context = __import__("chaosforge.interfaces.cli.session", fromlist=["context"]).context
    original = vars(context).copy()
    try:
        context.azure_subscription = "sub"
        context.azure_resource_group = "group"
        context.aks_cluster_name = "cluster"
        context.aks_kube_context = "stale-context"
        monkeypatch.setattr(
            "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
            list,
        )
        monkeypatch.setattr(
            platform_selector.subprocess,
            "run",
            MagicMock(return_value=SimpleNamespace(returncode=1, stderr="forbidden")),
        )
        error = MagicMock()
        monkeypatch.setattr(platform_selector, "error", error)
        monkeypatch.setattr(platform_selector, "info", MagicMock())

        assert selector.ensure_azure_kube_context() is False
        assert "forbidden" in error.call_args.args[0]
    finally:
        vars(context).clear()
        vars(context).update(original)


def test_web_experiment_get_post_and_ebs_enrichment_are_isolated(client, monkeypatch):
    metadata = {
        "experiments": [{
            "id": "ec2-ebs-volume-detach",
            "inputs": [
                {"name": "aws_region", "default": "us-west-2"},
                {"name": "instance_id", "type": "aws_resource", "resource_type": "ec2-instance"},
                {"name": "volume_id", "type": "aws_resource", "resource_type": "ec2-volume"},
            ],
            "iam": {"read": ["ec2:DescribeInstances"], "modify": ["ec2:DetachVolume"]},
        }]
    }
    monkeypatch.setattr(web_app, "load_metadata", lambda _: metadata)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {"summary": "detach"})
    discovery = MagicMock()
    discovery.discover.return_value = [{"id": "i-1"}]
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=discovery))
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    selector = MagicMock()
    selector.discovery.list_ec2_ebs_volumes.return_value = [{"id": "vol-1", "device_name": "/dev/xvdf"}]
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: SimpleNamespace(campaign_id="campaign-1"))

    assert client.get("/experiment/ec2/ec2-ebs-volume-detach").status_code == 200
    response = client.post("/experiment/ec2/ec2-ebs-volume-detach", data={"aws_region": "us-west-2", "instance_id": "i-1", "volume_id": "vol-1"})
    assert response.status_code == 302
    assert add.call_args.args[2]["device_name"] == "/dev/xvdf"
    assert client.get("/experiment/missing/id").status_code == 404
    assert client.get("/experiment/ec2/missing").status_code == 404


def test_web_campaign_execution_and_saved_campaign_routes(client, monkeypatch):
    current = SimpleNamespace(
        name="Current",
        continue_on_failure=True,
        cloud_provider="aws",
        experiments=[SimpleNamespace(service="lambda", id="exp-1")],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: current)
    selected = [SimpleNamespace(service="lambda", id=f"exp-{item}") for item in (1, 2)]
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda ids: selected)
    executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_executor", MagicMock(return_value=executor))
    monkeypatch.setattr(web_app, "_consume_permission_review_token", lambda *_: True)
    assert client.get("/campaign/execute-selected?ids=1,2&cloud=aws&review=approved").status_code == 302
    assert executor.start.call_args.args[0].experiments == selected
    assert client.get("/campaign/execute-selected").status_code == 302

    assert client.get("/campaign/save").status_code == 404
    assert client.get("/campaign/load/Saved").status_code == 404
    assert client.get("/campaign/run/Saved").status_code == 404
    assert client.get("/campaign/delete/Saved").status_code == 404


def test_web_fis_and_campaign_page_variants(client, monkeypatch):
    metadata = {"experiments": [{"id": "create", "inputs": []}]}
    catalog = MagicMock()
    catalog.get_services.return_value = ["ec2"]
    catalog.get_experiments.return_value = [{"id": "stop"}]
    monkeypatch.setattr(web_app, "load_metadata", lambda _: metadata)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(web_app, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())
    selector = MagicMock()
    selector.get_resources.return_value = [{"id": "i-1"}]
    selector.select_child_resources.return_value = [{"id": "vol-1"}]
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(web_app, "get_experiment", lambda _: None)

    assert client.post("/experiment/fis/create", data={"load_service": "1", "service_id": "ec2", "aws_region": "us-east-1"}).status_code == 200
    assert client.get("/api/resources/eks-pod/cluster::default::pod/eks-volume/us-east-1").get_json() == [{"id": "vol-1"}]
    selector.select_child_resources.assert_called_with("eks-pod", ("cluster", "default", "pod"), "eks-volume")
    assert client.get("/campaign/edit/0").status_code == 404

    assert client.get("/campaign/load").status_code == 404
