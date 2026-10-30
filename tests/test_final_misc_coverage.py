"""Behavior-focused coverage for small residual paths across subsystems."""

import builtins
import json
import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, mock_open

import pytest
from botocore.exceptions import ClientError
from kubernetes.client.rest import ApiException

from chaosforge.application.services import cloud_identity, planning
from chaosforge.application.services.campaign_executor import CampaignExecutor
from chaosforge.catalog.loader import ExperimentCatalog
from chaosforge.common.paths import ChaosForgePaths
from chaosforge.engines.chaos_mesh.chaos_mesh_client import ChaosMeshClient
from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshInstaller,
    HelmReleaseStatus,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_models import ChaosMeshExperiment
from chaosforge.engines.chaos_mesh.chaos_mesh_runner import ChaosMeshRunner
from chaosforge.interfaces.cli import main as cli_main
from chaosforge.interfaces.cli.interactive import input_engine, resource_selector
from chaosforge.interfaces.cli.interactive.ui import dashboard as dashboard_module
from chaosforge.interfaces.web import app as web_app
from chaosforge.lifecycle.checks.azure_redis_adapter import AzureRedisAdapter
from chaosforge.models.planning import PlanResult
from chaosforge.providers.aws.components.elb.experiments.toolkit.actions import (
    elb_health_check_actions,
    elb_listener_actions,
)
from chaosforge.providers.azure.components.azure_redis.experiments.chaos_studio.actions import (
    redis_reboot,
)
from chaosforge.providers.azure.components.azure_redis.experiments.custom.actions import (
    redis_actions,
)

lambda_concurrency_actions = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.toolkit.actions."
    "lambda_concurrency_actions"
)


def test_campaign_executor_calls_observers_with_results():
    experiment = SimpleNamespace(status="SUCCESS")
    campaign = SimpleNamespace(experiments=[experiment], continue_on_failure=False)
    before = MagicMock()
    after = MagicMock()
    execution = object()

    result = CampaignExecutor().execute(
        campaign,
        lambda _: execution,
        before_experiment=before,
        after_experiment=after,
    )

    before.assert_called_once_with(1, 1, experiment)
    after.assert_called_once_with(1, 1, experiment, execution)
    assert result.status == "SUCCESS"
    assert campaign.duration >= 0


def test_planning_lazy_discovery_and_json_kind_fallback(monkeypatch, tmp_path):
    discovery = MagicMock(return_value="discovery")
    monkeypatch.setattr("chaosforge.providers.aws.discovery.AWSDiscovery", discovery)
    assert planning._aws_discovery("eu-west-1") == "discovery"
    discovery.assert_called_once_with("eu-west-1")

    definition = tmp_path / "experiment.json"
    experiment = SimpleNamespace(json_file=str(definition))
    definition.write_text(json.dumps({"chaos_mesh": []}), encoding="utf-8")
    assert planning.PlanService._load_chaos_mesh_kind(experiment) is None
    definition.write_text(json.dumps({"chaos_mesh": {}}), encoding="utf-8")
    assert planning.PlanService._load_chaos_mesh_kind(experiment) is None


def test_plan_result_finalization_and_serialization_are_independent():
    blocked = PlanResult(blockers=["missing target"]).finalize()
    serialized = blocked.to_dict()
    serialized["blockers"].append("local mutation")

    assert blocked.executable is False
    assert blocked.blockers == ["missing target"]


def test_cloud_identity_refresh_bypasses_cached_value(monkeypatch):
    cloud_identity.clear_cloud_identity_cache()
    lookup = MagicMock(side_effect=[{"name": "old"}, {"name": "new"}])
    monkeypatch.setattr(cloud_identity, "_lookup_cloud_identity", lookup)

    assert cloud_identity.get_cloud_identity("aws")["name"] == "old"
    assert cloud_identity.get_cloud_identity("aws", refresh=True)["name"] == "new"
    assert lookup.call_count == 2


def test_catalog_definition_paths_cover_redis_and_unknown_services(tmp_path):
    paths = ChaosForgePaths(root=tmp_path)
    catalog = ExperimentCatalog(paths)

    redis_path = catalog.definition_path("azure_redis", "flush.json")
    missing_path = catalog.definition_path("unknown", "anything.json")

    assert redis_path == (
        tmp_path
        / "chaosforge/providers/azure/components/azure_redis/experiments/flush.json"
    )
    assert missing_path.name == "missing-definition.json"


def test_chaos_mesh_wait_for_deletion_sleeps_before_timeout(monkeypatch):
    client = ChaosMeshClient()
    client.get = MagicMock(side_effect=ApiException(status=500, reason="busy"))
    clock = iter((0.0, 0.1, 0.2, 2.0))
    sleep = MagicMock()
    monkeypatch.setattr(
        "chaosforge.engines.chaos_mesh.chaos_mesh_client.time.monotonic",
        lambda: next(clock),
    )
    monkeypatch.setattr(
        "chaosforge.engines.chaos_mesh.chaos_mesh_client.time.sleep", sleep
    )

    with pytest.raises(TimeoutError, match=r"(?s)Last API error:.*busy"):
        client.wait_for_deleted("PodChaos", "fault", timeout_seconds=1)

    sleep.assert_called_once_with(pytest.approx(0.8))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (HelmReleaseStatus.INSTALLED, True),
        (HelmReleaseStatus.ABSENT, False),
    ],
)
def test_installer_reports_only_confirmed_release_as_installed(monkeypatch, status, expected):
    installer = ChaosMeshInstaller()
    monkeypatch.setattr(installer, "release_status", lambda: (status, "status"))
    assert installer.is_release_installed() is expected


def test_chaos_mesh_models_and_runner_preserve_optional_metadata():
    manifest = ChaosMeshExperiment(
        kind="PodChaos",
        name="kill-one",
        annotations={"owner": "platform"},
    ).to_manifest()
    experiment = SimpleNamespace(
        variables={"manifest": {"metadata": {"namespace": "chaos-testing"}}}
    )

    assert manifest["metadata"]["annotations"] == {"owner": "platform"}
    assert ChaosMeshRunner._namespace(experiment) == "chaos-testing"


def test_azure_redis_adapter_explains_missing_sdk(monkeypatch):
    real_import = builtins.__import__

    def reject_azure_identity(name, *args, **kwargs):
        if name == "azure.identity":
            error = ImportError("not installed")
            error.name = "azure.identity"
            raise error
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_azure_identity)
    with pytest.raises(RuntimeError, match="Azure Redis SDK dependencies"):
        AzureRedisAdapter().capture(
            {"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache"}
        )


def test_redis_custom_client_uses_credential_and_subscription(monkeypatch):
    credential = object()
    credential_factory = MagicMock(return_value=credential)
    client_factory = MagicMock(return_value="client")
    identity = ModuleType("azure.identity")
    identity.DefaultAzureCredential = credential_factory
    redis = ModuleType("azure.mgmt.redis")
    redis.RedisManagementClient = client_factory
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    monkeypatch.setitem(sys.modules, "azure.mgmt.redis", redis)

    assert redis_actions._redis_client("subscription") == "client"
    client_factory.assert_called_once_with(credential, "subscription")


def test_redis_reboot_reports_missing_sdk_and_waits_for_terminal_state(monkeypatch):
    real_import = builtins.__import__

    def reject_azure_identity(name, *args, **kwargs):
        if name == "azure.identity":
            error = ImportError("not installed")
            error.name = "azure.identity"
            raise error
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_azure_identity)
    with pytest.raises(RuntimeError, match="azure.identity"):
        redis_reboot.run_experiment("sub", "rg", "cache", "identity")

    experiments = MagicMock()
    experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    experiments.get_execution.side_effect = [
        SimpleNamespace(status="Running"),
        SimpleNamespace(status="Succeeded"),
    ]
    sleep = MagicMock()
    monkeypatch.setattr(redis_reboot.time, "monotonic", MagicMock(side_effect=[0, 1, 2]))
    monkeypatch.setattr(redis_reboot.time, "sleep", sleep)
    redis_reboot._wait_for_completion(SimpleNamespace(experiments=experiments), "rg", "exp")
    sleep.assert_called_once_with(5)


def test_elb_actions_raise_clear_errors_for_missing_remote_data(monkeypatch):
    client = MagicMock()
    client.describe_target_groups.return_value = {"TargetGroups": []}
    client.describe_listener_attributes.return_value = {"Attributes": [{"Key": "other"}]}
    monkeypatch.setattr(elb_health_check_actions, "get_client", lambda _: client)
    monkeypatch.setattr(elb_listener_actions, "get_client", lambda _: client)

    with pytest.raises(RuntimeError, match="Target group 'tg' not found"):
        elb_health_check_actions.modify_health_check("tg", True, "eu-west-1")
    with pytest.raises(RuntimeError, match="Listener attribute 'routing.http2.enabled'"):
        elb_listener_actions.get_listener_attribute(
            "listener", "routing.http2.enabled", "eu-west-1"
        )


def test_lambda_concurrency_continues_after_aws_cleanup_errors(monkeypatch):
    client = MagicMock()
    not_found = type("NotFound", (Exception,), {})
    client.exceptions.ResourceNotFoundException = not_found
    client.exceptions.ProvisionedConcurrencyConfigNotFoundException = not_found
    client.delete_provisioned_concurrency_config.side_effect = ClientError(
        {"Error": {"Code": "Conflict", "Message": "busy"}}, "DeleteProvisioned"
    )
    client.get_provisioned_concurrency_config.side_effect = not_found()
    client.list_provisioned_concurrency_configs.side_effect = ClientError(
        {"Error": {"Code": "Throttled", "Message": "slow"}}, "ListProvisioned"
    )
    monkeypatch.setattr(lambda_concurrency_actions.boto3, "client", lambda *_, **__: client)
    monkeypatch.setattr(
        lambda_concurrency_actions,
        "open",
        mock_open(read_data=json.dumps({"original_provisioned": [{"Qualifier": "LIVE"}]})),
        raising=False,
    )

    result = lambda_concurrency_actions.update_concurrency("function", 3, "eu-west-1")

    client.put_function_concurrency.assert_called_once_with(
        FunctionName="function", ReservedConcurrentExecutions=3
    )
    assert result["new_concurrency"] == 3


def test_web_redis_discovery_requires_matching_identity_and_handles_errors(monkeypatch):
    web_app.app.config.update(TESTING=True)
    client = web_app.app.test_client()
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_, **__: {"authenticated": False})
    assert client.get("/api/azure/redis/caches/sub/rg").status_code == 401

    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_, **__: {"authenticated": True, "subscription_id": "sub"},
    )
    discovery = MagicMock()
    discovery.return_value.list_redis_caches.side_effect = RuntimeError("Azure unavailable")
    monkeypatch.setattr(web_app, "AzureResourceDiscovery", discovery)
    response = client.get("/api/azure/redis/caches/sub/rg")

    assert response.status_code == 400
    assert response.get_json() == {"error": "Azure unavailable"}


def test_cli_import_requires_selected_cloud(monkeypatch):
    monkeypatch.setattr(cli_main.context, "cloud", None)
    show_error = MagicMock()
    pause = MagicMock()
    monkeypatch.setattr(cli_main, "error", show_error)
    monkeypatch.setattr(cli_main, "pause", pause)

    assert cli_main.import_yaml_campaign() is None
    show_error.assert_called_once_with("Select a cloud provider before importing a campaign YAML.")
    pause.assert_called_once_with()


def test_dashboard_refreshes_identity_for_active_cloud(monkeypatch):
    identity = {"authenticated": True, "name": "engineering"}
    lookup = MagicMock(return_value=identity)
    output = MagicMock()
    monkeypatch.setattr(dashboard_module.context, "cloud", "aws")
    monkeypatch.setattr(dashboard_module, "get_cloud_identity", lookup)
    monkeypatch.setattr(dashboard_module, "console", output)

    dashboard_module.dashboard("eu-west-1", "campaign", 1)

    lookup.assert_called_once_with("aws", "eu-west-1")
    assert dashboard_module.context.cloud_identity == identity


def test_input_engine_reprompts_invalid_prefilled_fis_parameter(monkeypatch):
    experiment = {
        "parameters": [{"name": "count", "label": "Count", "type": "number"}]
    }
    catalog = MagicMock()
    catalog.get_experiment.return_value = experiment
    answers = iter(("bad", "2"))
    show_error = MagicMock()
    monkeypatch.setattr(input_engine, "FISCatalog", lambda: catalog)
    monkeypatch.setattr(input_engine, "prompt", lambda _: next(answers))
    monkeypatch.setattr(input_engine, "error", show_error)

    values = input_engine.collect_inputs(
        {
            "name": "FIS",
            "inputs": [
                {"name": "service_id", "label": "Service"},
                {"name": "experiment_id", "label": "Experiment"},
            ],
        },
        {"service_id": "ec2", "experiment_id": "stop"},
    )

    assert values["count"] == 2
    show_error.assert_called_once()


@pytest.mark.parametrize(
    ("field", "resource", "expected"),
    [
        (
            {"resource_type": "ecs-service", "parent": "cluster"},
            {"name": "service"},
            {"target": "service", "ecs_cluster": "cluster-a"},
        ),
        (
            {"resource_type": "ecs_service"},
            {"name": "service", "cluster": "cluster-b"},
            {"target": "service", "ecs_cluster": "cluster-b"},
        ),
        (
            {"resource_type": "apigateway"},
            {"name": "api", "protocol": "HTTP"},
            {"target": "api"},
        ),
    ],
)
def test_input_engine_preserves_selected_resource_context(
    monkeypatch, field, resource, expected
):
    selector = MagicMock()
    selector.select.return_value = resource
    selector.select_child.return_value = resource
    monkeypatch.setattr(input_engine, "ResourceSelector", lambda _: selector)
    monkeypatch.setattr(input_engine.context, "region", "eu-west-1")
    metadata_field = {"name": "target", "label": "Target", "type": "aws_resource", **field}
    inputs = []
    prefill = {}
    if field.get("parent"):
        inputs.append(
            {
                "name": "cluster",
                "label": "Cluster",
                "type": "aws_resource",
                "resource_type": "ecs",
            }
        )
        prefill["cluster"] = "cluster-a"
    inputs.append(metadata_field)

    values = input_engine.collect_inputs({"name": "Selection", "inputs": inputs}, prefill)

    assert {key: values[key] for key in expected} == expected
    if field["resource_type"] == "apigateway":
        assert input_engine.context.apigateway_protocol == "HTTP"


def test_input_engine_accepts_boolean_defaults_without_string_conversion(monkeypatch):
    monkeypatch.setattr(input_engine, "get_input", lambda _: "")
    values = input_engine.collect_inputs(
        {
            "name": "Boolean",
            "inputs": [
                {"name": "enabled", "label": "Enabled", "type": "boolean", "default": True}
            ],
        }
    )
    assert values["enabled"] is True


def test_resource_selector_cancellation_empty_results_and_child_dispatch(monkeypatch):
    selector = object.__new__(resource_selector.ResourceSelector)
    selector.discovery = MagicMock()
    selector.discovery.list_available_ec2_ebs_volumes.return_value = [{"id": "vol", "name": "vol"}]
    selector._select_resource = MagicMock(return_value=None)
    monkeypatch.setattr(resource_selector, "title", MagicMock())
    monkeypatch.setattr(resource_selector, "menu", MagicMock())
    assert selector.select_available_ebs_volume("i-1") is None

    selector.list_available_ebs_volumes_for_asg = MagicMock(return_value=[])
    with pytest.raises(LookupError, match="No available EBS volumes"):
        selector.select_available_ebs_volume_for_asg("asg")

    selector.discovery.list_elb_listeners.return_value = []
    with pytest.raises(LookupError, match="No ELB Listeners"):
        selector.select_elb_listener("lb")

    selector.select_available_ebs_volume_for_asg = MagicMock(return_value={"id": "vol-2"})
    assert selector.select_child("autoscaling-group", "asg", "ebs-volume-asg-available") == {
        "id": "vol-2"
    }
    selector.discovery.list_chaos_physical_machines.return_value = ["machine"]
    selector.discovery.list_eks_volumes.return_value = ["volume"]
    assert selector.select_child_resources("eks", "cluster", "chaos-physical-machine") == [
        "machine"
    ]
    assert selector.select_child_resources(
        "eks-pod", ("cluster", "namespace", "pod"), "eks-volume"
    ) == ["volume"]
