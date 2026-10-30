"""Regression coverage for statements listed in the full coverage report."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.catalog import loader
from chaosforge.catalog.loader import ExperimentCatalog
from chaosforge.common.paths import ChaosForgePaths
from chaosforge.interfaces.cli import main as cli_main
from chaosforge.interfaces.cli.interactive import azure_aks_service as aks
from chaosforge.interfaces.cli.interactive import resource_selector
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.session import context
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.providers.aws.discovery import AWSDiscovery


def _aks_metadata(*inputs):
    return {"name": "Coverage", "id": "aks-clock-skew-forward", "inputs": list(inputs)}


@pytest.fixture(autouse=True)
def aks_context():
    original = vars(context).copy()
    context.aks_kube_context = "ctx"
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    context.aks_cluster_name = "cluster"
    context.azure_location = "eastus"
    yield
    vars(context).clear()
    vars(context).update(original)


def _collect_aks(monkeypatch, metadata, answers, discovery):
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(aks, "prompt", MagicMock(side_effect=answers))
    monkeypatch.setattr(aks, "title", MagicMock())
    return aks._collect_aks_inputs(metadata)


def test_catalog_resolves_non_redis_azure_definition_path(monkeypatch, tmp_path):
    metadata = tmp_path / "chaosforge/providers/azure/components/azure_test/experiments/metadata.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(loader.AZURE_COMPONENT_PACKAGES, "azure_test", "azure_test")
    monkeypatch.setattr(ExperimentCatalog, "metadata_path", lambda *_args: metadata)

    path = ExperimentCatalog(ChaosForgePaths(tmp_path)).definition_path("azure_test", "spec.json")

    assert path == metadata.parent / "toolkit/definitions/spec.json"


def test_aks_empty_pods_retries_or_returns_to_menu(monkeypatch):
    discovery = MagicMock()
    discovery.list_namespaces.return_value = ["apps"]
    discovery.list_pods.return_value = []
    metadata = _aks_metadata(
        {"name": "aks_context", "label": "Cluster", "type": "azure_aks_cluster"},
        {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace"},
    )

    with pytest.raises(BackToMainMenu):
        _collect_aks(monkeypatch, metadata, ["1", "2", "0"], discovery)


def test_aks_pod_mode_populates_deployment_without_discovery(monkeypatch):
    discovery = MagicMock()
    discovery.list_namespaces.return_value = ["apps"]
    discovery.list_pods.return_value = ["pod-1"]
    discovery.get_pod_label.return_value = ("app", "api")
    discovery.get_deployment_for_pod.return_value = "deployment"
    metadata = _aks_metadata(
        {"name": "aks_context", "label": "Cluster", "type": "azure_aks_cluster"},
        {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace"},
        {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment"},
    )

    values = _collect_aks(monkeypatch, metadata, ["1", "2", "1", "n"], discovery)

    assert values["deployment"] == "pod-1"
    discovery.list_deployments.assert_not_called()


def test_aks_empty_deployments_returns_to_menu(monkeypatch):
    discovery = MagicMock()
    discovery.list_namespaces.return_value = ["apps"]
    discovery.list_deployments.return_value = []
    metadata = _aks_metadata(
        {"name": "aks_context", "label": "Cluster", "type": "azure_aks_cluster"},
        {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace"},
        {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment"},
    )

    with pytest.raises(BackToMainMenu):
        _collect_aks(monkeypatch, metadata, ["1", "1", "0"], discovery)


def test_aks_time_offset_back_chaos_main_menu_and_integer_minimum(monkeypatch):
    discovery = MagicMock()

    assert _collect_aks(
        monkeypatch,
        _aks_metadata({"name": "offset", "label": "Offset", "type": "time_offset"}),
        ["0"],
        discovery,
    ) is None

    with pytest.raises(BackToMainMenu):
        _collect_aks(
            monkeypatch,
            _aks_metadata({"name": "mode", "label": "Mode", "type": "chaos_mode"}),
            ["3", "m"],
            discovery,
        )

    report = MagicMock()
    monkeypatch.setattr(aks, "error", report)
    values = _collect_aks(
        monkeypatch,
        _aks_metadata({"name": "count", "label": "Count", "type": "integer", "min": 2}),
        ["1", "2", "n"],
        discovery,
    )
    assert values["count"] == 2
    report.assert_called_once_with("Value must be >= 2")


def test_resource_selector_handles_a_nonempty_selection_that_parses_empty(monkeypatch):
    class EmptySelection(str):
        def split(self, _separator=None, _maxsplit=-1):
            return []

    selector = object.__new__(resource_selector.ResourceSelector)
    selector.get_resources = MagicMock(return_value=[{"name": "one"}])
    monkeypatch.setattr(resource_selector, "prompt", lambda _: EmptySelection("selected"))
    monkeypatch.setattr(resource_selector, "title", MagicMock())
    monkeypatch.setattr(resource_selector, "menu", MagicMock())

    assert selector.select_multiple("lambda") is None


def test_cli_skips_incomplete_aks_pod_target(monkeypatch):
    experiment = SimpleNamespace(service="aks", variables={"target_mode": "pod", "aks_context": "ctx"})
    discovery = MagicMock()
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery",
        MagicMock(return_value=discovery),
    )

    cli_main.refresh_failed_aks_pod_targets(SimpleNamespace(experiments=[experiment]))

    discovery.list_pods.assert_not_called()


@pytest.mark.parametrize("experiment_id", ["elasticache-daily-snapshot", "s3-lifecycle"])
def test_resolver_returns_registered_aws_and_s3_common_checks(experiment_id):
    check = CheckResolver().resolve(SimpleNamespace(id=experiment_id, variables={}))

    assert isinstance(check, CommonResourceCheck)
    assert check.name == f"{experiment_id}-lifecycle"


def test_resolver_returns_generic_aws_resource_check():
    check = CheckResolver().resolve(
        SimpleNamespace(id="dynamodb-capacity", variables={})
    )

    assert isinstance(check, CommonResourceCheck)
    assert check.name == "dynamodb-capacity-lifecycle"


def test_aws_routes_evaluate_the_second_local_route_guard(monkeypatch):
    class ChangingRoute(dict):
        def __init__(self):
            super().__init__(GatewayId="local")
            self.calls = 0

        def get(self, key, default=None):
            if key == "GatewayId":
                self.calls += 1
                return "not-local" if self.calls == 1 else "local"
            return super().get(key, default)

    client = MagicMock()
    client.describe_route_tables.return_value = {"RouteTables": [{"Routes": [ChangingRoute()]}]}
    monkeypatch.setattr("chaosforge.providers.aws.discovery.boto3.client", lambda *_args, **_kwargs: client)

    assert AWSDiscovery("eu-west-1").list_routes("rtb-1") == []
