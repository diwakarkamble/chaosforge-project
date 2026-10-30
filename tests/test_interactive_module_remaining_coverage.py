from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli.interactive import azure_aks_service as aks
from chaosforge.interfaces.cli.interactive import azure_redis_menu as redis
from chaosforge.interfaces.cli.interactive import input_engine
from chaosforge.interfaces.cli.interactive import platform_selector as platform
from chaosforge.interfaces.cli.session import context


@pytest.fixture(autouse=True)
def restore_context():
    original = vars(context).copy()
    yield
    vars(context).clear()
    vars(context).update(original)


def test_redis_context_rejects_invalid_resource_group_selection(monkeypatch):
    monkeypatch.setattr(redis, "get_cloud_identity", lambda *_args, **_kwargs: {
        "authenticated": True, "subscription_id": "sub", "name": "Account"
    })
    discovery = MagicMock()
    discovery.list_resource_groups.return_value = [{"id": "rg", "name": "group"}]
    monkeypatch.setattr(redis, "AzureResourceDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(redis, "prompt", MagicMock(return_value="invalid"))
    report = MagicMock()
    monkeypatch.setattr(redis, "error", report)

    assert redis._ensure_azure_context() is False
    report.assert_called_once_with("Invalid Resource Group selection.")


def test_input_engine_skips_prefilled_fis_parameter(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "parameters": [
            {"name": "already_set", "label": "Already Set", "type": "string"},
            {"name": "new_value", "label": "New Value", "type": "string"},
        ]
    }
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock())
    monkeypatch.setattr(input_engine, "prompt", MagicMock(return_value="entered"))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    values = input_engine.collect_inputs(
        {"name": "FIS", "inputs": [{"name": "service_id", "label": "Service"},
                                    {"name": "experiment_id", "label": "Experiment"}]},
        prefill={"service_id": "ec2", "experiment_id": "stop", "already_set": "kept"},
    )

    assert values["already_set"] == "kept"
    assert values["new_value"] == "entered"


def test_input_engine_ignores_missing_prefilled_fis_experiment(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = None
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    values = input_engine.collect_inputs(
        {"name": "FIS", "inputs": [{"name": "experiment_id", "label": "Experiment"}]},
        prefill={"service_id": "ec2", "experiment_id": "missing"},
    )

    assert values["experiment_id"] == "missing"


def test_input_engine_binds_component_fis_metadata_before_collection(monkeypatch):
    bound = {"name": "Stop EC2 Instances", "inputs": []}
    bind = MagicMock(return_value=bound)
    monkeypatch.setattr(input_engine, "bind_component_fis", bind)
    monkeypatch.setattr(input_engine, "title", MagicMock())

    values = input_engine.collect_inputs(
        {"name": "FIS", "service": "fis", "inputs": [{"name": "service_id", "label": "Service"}]},
        prefill={"service_id": "ec2", "experiment_id": "stop-instances"},
    )

    assert values["service_id"] == "ec2"
    bind.assert_called_once_with(
        {"name": "FIS", "service": "fis", "inputs": [{"name": "service_id", "label": "Service"}]},
        "ec2",
        "stop-instances",
    )


def test_input_engine_fis_target_falls_back_to_component_selector(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {}
    selector = MagicMock()
    selector.select.return_value = {"arn": "arn:aws:ec2:region:account:instance/i-1"}
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    values = input_engine.collect_inputs(
        {"name": "FIS", "inputs": [{"name": "target_arn", "label": "Target"}]},
        prefill={"service_id": "ec2", "experiment_id": "legacy"},
    )

    selector.select.assert_called_once_with("ec2")
    assert values["target_arn"].endswith("instance/i-1")


def test_input_engine_fis_target_uses_legacy_component_fallback(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {}
    selector = MagicMock()
    selector.select.return_value = {"arn": "arn:aws:ec2:region:account:instance/i-2"}
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(input_engine, "fis_target_selector", lambda *_: None)
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    values = input_engine.collect_inputs(
        {"name": "FIS", "inputs": [{"name": "target_arn", "label": "Target"}]},
        prefill={"service_id": "ec2", "experiment_id": "legacy"},
    )

    selector.select.assert_called_once_with("ec2")
    assert values["target_arn"].endswith("instance/i-2")


@pytest.mark.parametrize(
    "metadata,prefill",
    [
        (
            {"name": "ASG", "inputs": [
                {"name": "asg", "label": "ASG", "type": "aws_resource",
                 "resource_type": "autoscaling-group"},
                {"name": "volume", "label": "Volume", "type": "aws_resource",
                 "resource_type": "ebs-volume-asg-available", "parent": "asg"},
            ]},
            {"asg": "asg-1"},
        ),
        (
            {"name": "Child", "inputs": [
                {"name": "group", "label": "Group", "type": "aws_resource",
                 "resource_type": "security-group"},
                {"name": "rule", "label": "Rule", "type": "aws_resource",
                 "resource_type": "security-group-rule", "parent": "group"},
            ]},
            {"group": "sg-1"},
        ),
        (
            {"name": "Direct", "inputs": [
                {"name": "function", "label": "Function", "type": "aws_resource",
                 "resource_type": "lambda"},
            ]},
            {},
        ),
    ],
)
def test_input_engine_returns_none_when_resource_selection_is_cancelled(monkeypatch, metadata, prefill):
    selector = MagicMock()
    selector.select.return_value = None
    selector.select_child.return_value = None
    selector.select_available_ebs_volume_for_asg.return_value = None
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    assert input_engine.collect_inputs(metadata, prefill=prefill) is None


def test_platform_manual_setup_handles_cluster_listing_and_show_failures(monkeypatch):
    selector = platform.PlatformSelector()
    responses = [
        SimpleNamespace(returncode=0, stdout='{"name": "Account"}', stderr=""),
        FileNotFoundError(),
        RuntimeError("details unavailable"),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ]
    monkeypatch.setattr(platform.subprocess, "run", MagicMock(side_effect=responses))
    monkeypatch.setattr(platform, "prompt", MagicMock(side_effect=["sub", "rg", "aks", "y"]))
    monkeypatch.setattr(platform, "_save_azure_cache", MagicMock())
    monkeypatch.setattr(platform, "error", MagicMock())
    monkeypatch.setattr(platform, "info", MagicMock())
    monkeypatch.setattr(platform, "console", MagicMock())
    monkeypatch.setattr(platform, "title", MagicMock())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda *_: nullcontext())
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts", lambda: []
    )

    assert selector._prompt_azure_details() is True
    assert context.azure_location is None


def test_platform_manual_setup_handles_generic_cluster_listing_failure(monkeypatch):
    selector = platform.PlatformSelector()
    monkeypatch.setattr(platform.subprocess, "run", MagicMock(side_effect=[
        SimpleNamespace(returncode=0, stdout='{"name": "Account"}', stderr=""),
        RuntimeError("cluster listing unavailable"),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ]))
    monkeypatch.setattr(platform, "prompt", MagicMock(side_effect=["sub", "rg", "aks", "y"]))
    monkeypatch.setattr(platform, "_save_azure_cache", MagicMock())
    monkeypatch.setattr(platform, "error", MagicMock())
    monkeypatch.setattr(platform, "info", MagicMock())
    monkeypatch.setattr(platform, "console", MagicMock())
    monkeypatch.setattr(platform, "title", MagicMock())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda *_: nullcontext())
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts", lambda: []
    )

    assert selector._prompt_azure_details() is True


def test_platform_fetches_credentials_when_matching_context_is_declined(monkeypatch):
    selector = platform.PlatformSelector()
    monkeypatch.setattr(platform.subprocess, "run", MagicMock(side_effect=[
        SimpleNamespace(returncode=0, stdout='{"name": "Account"}', stderr=""),
        SimpleNamespace(returncode=0, stdout='[{"name": "aks", "resourceGroup": "rg"}]', stderr=""),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ]))
    monkeypatch.setattr(platform, "prompt", MagicMock(side_effect=["sub", "1", "0", "y"]))
    monkeypatch.setattr(platform, "_save_azure_cache", MagicMock())
    monkeypatch.setattr(platform, "console", MagicMock())
    monkeypatch.setattr(platform, "title", MagicMock())
    monkeypatch.setattr(platform, "info", MagicMock())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda *_: nullcontext())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.tables.menu", MagicMock())
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts", lambda: ["aks-admin"]
    )

    assert selector._prompt_azure_details() is True
    assert context.aks_kube_context == "aks"


def test_platform_ignores_kubeconfig_query_errors_during_setup(monkeypatch):
    selector = platform.PlatformSelector()
    monkeypatch.setattr(platform.subprocess, "run", MagicMock(side_effect=[
        SimpleNamespace(returncode=0, stdout='{"name": "Account"}', stderr=""),
        SimpleNamespace(returncode=0, stdout='[{"name": "aks", "resourceGroup": "rg"}]', stderr=""),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ]))
    monkeypatch.setattr(platform, "prompt", MagicMock(side_effect=["sub", "1", "y"]))
    monkeypatch.setattr(platform, "_save_azure_cache", MagicMock())
    monkeypatch.setattr(platform, "console", MagicMock())
    monkeypatch.setattr(platform, "title", MagicMock())
    monkeypatch.setattr(platform, "info", MagicMock())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.spinner.spinner", lambda *_: nullcontext())
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
        MagicMock(side_effect=RuntimeError("bad kubeconfig")),
    )

    assert selector._prompt_azure_details() is True
    assert context.aks_kube_context == "aks"


def test_aks_pod_selection_retries_and_namespace_backtracks(monkeypatch):
    discovery = MagicMock()
    discovery.list_namespaces.return_value = ["first", "second"]
    discovery.list_pods.return_value = ["pod"]
    discovery.list_deployments.return_value = ["deployment"]
    discovery.get_label_selector.return_value = ("app", "api")
    discovery.get_safe_label_selector.return_value = {"app": "api"}
    discovery.get_pod_count.return_value = 1
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(aks, "title", MagicMock())
    monkeypatch.setattr(aks, "console", MagicMock())
    monkeypatch.setattr(aks, "info", MagicMock())
    monkeypatch.setattr(aks, "_pick", MagicMock(side_effect=[
        "first", "By Pod", aks._BackStep(), aks._BackStep(), "second", "By Deployment", "deployment",
    ]))
    monkeypatch.setattr(aks, "prompt", MagicMock(return_value="n"))

    values = aks._collect_aks_inputs({"name": "AKS", "inputs": [
        {"name": "namespace", "type": "azure_aks_namespace"},
        {"name": "deployment", "type": "azure_aks_deployment"},
    ]})

    assert values["namespace"] == "second"
    assert values["deployment"] == "deployment"


def test_aks_validation_and_cluster_back_paths(monkeypatch):
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock())
    monkeypatch.setattr(aks, "title", MagicMock())
    monkeypatch.setattr(aks, "console", MagicMock())
    monkeypatch.setattr(aks, "error", MagicMock())
    monkeypatch.setattr(aks, "info", MagicMock())
    monkeypatch.setattr(aks, "_pick", MagicMock(side_effect=["fixed mode", "fixed-percent mode"]))
    monkeypatch.setattr(aks, "prompt", MagicMock(side_effect=["bad", "1", "101", "50", "n"]))

    values = aks._collect_aks_inputs({"name": "Modes", "inputs": [
        {"name": "first", "type": "chaos_mode"},
        {"name": "second", "type": "chaos_mode"},
    ]})

    assert values["chaos_value"] == "50"

    context.aks_kube_context = "ctx"
    monkeypatch.setattr(aks, "prompt", MagicMock(return_value="0"))
    assert aks._collect_aks_inputs({"name": "Back", "inputs": [
        {"name": "aks_context", "type": "azure_aks_cluster"},
        {"name": "count", "label": "Count", "type": "integer"},
    ]}) is None
