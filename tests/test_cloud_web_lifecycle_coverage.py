"""Coverage for cloud-first Web, shared lifecycle, and CLI boundary gaps."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.application.campaigns import factory
from chaosforge.application.services import lifecycle_execution
from chaosforge.interfaces.cli.interactive import input_engine, menu_flat
from chaosforge.interfaces.web import app as web_app
from chaosforge.interfaces.web import catalog, forms
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.lifecycle.execution_dispatcher import ExecutionDispatcher


@pytest.fixture
def client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


def test_catalog_fallbacks_and_invalid_cloud(monkeypatch, client):
    monkeypatch.setattr(catalog, "discover_services", lambda cloud: ["new-service"])
    monkeypatch.setattr(catalog, "display_name", lambda service: "New Service")

    assert client.get("/cloud/not-a-cloud").status_code == 404
    assert catalog.cloud_cards() == list(catalog.CLOUDS.values())
    assert catalog.service_cards("azure") == [
        {
            "id": "new-service",
            "name": "New Service",
            "icon": "Azure-Cloud.svg",
            "description": "Configure and execute controlled resilience experiments",
        }
    ]
    with pytest.raises(ValueError, match="Unsupported cloud provider"):
        catalog.service_cards("gcp")
    assert catalog.service_cloud("aks") == "azure"
    assert catalog.service_cloud("lambda") == "aws"


def test_azure_component_cards_use_official_component_icons():
    expected = {
        "azure_vm": "Fluent-Server.svg",
        "azure_vmss": "Fluent-Server-Multiple.svg",
        "azure_app_service": "Fluent-Web-Asset.svg",
        "azure_key_vault": "Fluent-Key.svg",
        "azure_cosmos_db": "Fluent-Globe.svg",
        "azure_event_hub": "Fluent-Channel.svg",
        "azure_postgres_flexible": "Fluent-Database.svg",
        "azure_container_apps": "Fluent-Box.svg",
        "azure_functions": "Fluent-Code.svg",
    }
    icon_dir = Path("chaosforge/interfaces/web/static/icons")

    assert {service: catalog.SERVICE_ICONS[service] for service in expected} == expected
    assert all((icon_dir / icon).is_file() for icon in expected.values())


def test_form_normalization_covers_defaults_regions_numbers_and_errors(monkeypatch):
    seen = []

    def validate(field, value):
        seen.append((field, value))
        return (value != "bad", "invalid")

    monkeypatch.setattr(forms.Validator, "validate", validate)
    values, errors = forms.normalize_values(
        [
            {"name": "region", "type": "aws_region", "default": "east"},
            {"name": "whole", "type": "number"},
            {"name": "fraction", "type": "float"},
            {"name": "bad", "type": "string"},
        ],
        {"region": "", "whole": "2.0", "fraction": "2.5", "bad": "bad"},
    )

    assert values == {"region": "east", "whole": 2, "fraction": 2.5}
    assert errors == {"bad": "invalid"}
    assert seen[0][0]["type"] == "region"


@pytest.mark.parametrize(
    ("service", "engine", "target"),
    [
        ("lambda", "Chaos Toolkit", "lambda"),
        ("aks", "Azure Chaos Studio", "aks"),
        ("azure_redis", "Chaos Toolkit", "azure_redis"),
        ("fis", "AWS FIS", "ec2"),
        ("chaos_mesh", "Chaos Mesh", "eks"),
    ],
)
def test_factory_builds_every_engine(monkeypatch, service, engine, target):
    path = Path("definition.json")
    experiment_catalog = MagicMock()
    experiment_catalog.definition_path.return_value = path
    monkeypatch.setattr(factory, "ExperimentCatalog", MagicMock(return_value=experiment_catalog))
    variables = {"service_id": "ec2"} if service == "fis" else {}

    experiment = factory.create_experiment(
        service,
        {"id": "fault", "name": "Fault", "json": "fault.json"},
        variables,
        default_region="west",
    )

    assert experiment.engine == engine
    assert experiment.target_service == target
    assert experiment.json_file == ("" if service == "fis" else str(path))
    if service in {"aks", "azure_redis"}:
        assert experiment.variables["experiment_id"] == "fault"
        assert "aws_region" not in experiment.variables
    else:
        assert experiment.variables["aws_region"] == "west"


def test_lifecycle_service_wires_discovery_runner_and_campaign_callbacks(monkeypatch):
    toolkit = MagicMock()
    resolver = MagicMock()
    discovery = MagicMock()
    dispatcher = MagicMock()
    runner = MagicMock()
    runner.execute.return_value = "experiment-result"
    monkeypatch.setattr(lifecycle_execution, "AWSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(
        lifecycle_execution, "ExecutionDispatcher", MagicMock(return_value=dispatcher)
    )
    monkeypatch.setattr(lifecycle_execution, "LifecycleRunner", MagicMock(return_value=runner))
    campaign_executor = MagicMock()
    campaign_executor.execute.return_value = "campaign-result"
    monkeypatch.setattr(
        lifecycle_execution, "CampaignExecutor", MagicMock(return_value=campaign_executor)
    )
    service = lifecycle_execution.LifecycleExecutionService(toolkit, resolver)
    experiment = SimpleNamespace(variables={"aws_region": "west"})

    assert service.execute_experiment(experiment) == "experiment-result"
    lifecycle_execution.AWSDiscovery.assert_called_once_with("west")
    lifecycle_execution.ExecutionDispatcher.assert_called_once_with(
        chaos_toolkit_runner=toolkit, discovery=discovery
    )
    lifecycle_execution.LifecycleRunner.assert_called_once_with(
        runner=toolkit,
        check_resolver=resolver,
        discovery=discovery,
        dispatcher=dispatcher,
    )

    before = MagicMock()
    after = MagicMock()
    campaign = SimpleNamespace(experiments=[], cloud_provider="aws", name="Campaign", continue_on_failure=False)
    assert service.execute_campaign(
        campaign, before_experiment=before, after_experiment=after
    ) == "campaign-result"
    args, kwargs = campaign_executor.execute.call_args
    assert args[0] is campaign
    assert args[1].__self__ is service
    assert kwargs == {"before_experiment": before, "after_experiment": after}


def test_lifecycle_service_omits_discovery_without_region(monkeypatch):
    monkeypatch.setattr(lifecycle_execution, "ExecutionDispatcher", MagicMock())
    monkeypatch.setattr(lifecycle_execution, "LifecycleRunner", MagicMock())
    service = lifecycle_execution.LifecycleExecutionService(MagicMock(), MagicMock())

    service.create_runner(SimpleNamespace(variables={}))

    assert lifecycle_execution.ExecutionDispatcher.call_args.kwargs["discovery"] is None


def test_lifecycle_service_builds_aks_runner_without_aws_discovery(monkeypatch):
    dispatcher = MagicMock()
    runner = MagicMock()
    monkeypatch.setattr(lifecycle_execution, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(
        lifecycle_execution, "ExecutionDispatcher", MagicMock(return_value=dispatcher)
    )
    monkeypatch.setattr(
        lifecycle_execution, "LifecycleRunner", MagicMock(return_value=runner)
    )
    experiment = SimpleNamespace(
        id="aks-pod-kill",
        service="aks",
        variables={"aks_context": "cluster", "namespace": "apps"},
    )

    created = lifecycle_execution.LifecycleExecutionService().create_runner(experiment)

    assert created is runner
    lifecycle_execution.AWSDiscovery.assert_not_called()
    assert lifecycle_execution.LifecycleRunner.call_args.kwargs["discovery"] is None


def test_lifecycle_service_passes_reviewed_aks_version_action_as_runtime_only(monkeypatch):
    service = lifecycle_execution.LifecycleExecutionService()
    runner = MagicMock()
    runner.execute.return_value = "result"
    monkeypatch.setattr(service, "create_runner", MagicMock(return_value=runner))
    experiment = SimpleNamespace(
        service="aks",
        variables={"aks_context": "cluster"},
        chaos_mesh_version_action="upgrade",
        chaos_mesh_installed_version="2.8.4",
    )

    assert service.execute_experiment(experiment) == "result"
    assert experiment.variables["chaos_mesh_version_action"] == "upgrade"
    assert experiment.variables["chaos_mesh_installed_version"] == "2.8.4"


def test_lifecycle_service_executes_native_aks_id_without_aws_discovery(monkeypatch):
    experiment = SimpleNamespace(
        id="aks-pod-kill",
        service="",
        variables={"aks_context": "cluster", "namespace": "apps"},
    )
    runner = MagicMock()
    runner.execute.return_value = "result"
    monkeypatch.setattr(lifecycle_execution, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(
        lifecycle_execution, "LifecycleRunner", MagicMock(return_value=runner)
    )

    result = lifecycle_execution.LifecycleExecutionService().execute_experiment(experiment)

    assert result == "result"
    lifecycle_execution.AWSDiscovery.assert_not_called()
    runner.execute.assert_called_once_with(experiment)


def test_common_check_preconditions_predicate_failures_and_displays():
    adapter = MagicMock()
    adapter.capture.return_value = {"exists": True, "configuration": {"size": 3}}
    ineligible = CommonResourceCheck(
        adapter, preconditions={"must be ready": lambda snapshot: False}
    )
    with pytest.raises(ValueError, match="must be ready"):
        ineligible.capture({})

    check = CommonResourceCheck(
        adapter,
        predicates={"broken": lambda *_: 1 / 0},
        report_field=("target_size", "configuration.size", "GB"),
    )
    result = check.validate({}, {"configuration": {"size": 2}})
    assert result["checks"] == {"broken": False}
    assert result["display"] == {"Expected": "2 GB", "Observed": "3 GB"}
    assert check.build_execution_display({"target_size": 4}) == {
        "Expected": "4 GB",
        "Observed": "Applied successfully",
    }
    assert check.build_execution_display({}) == {"Expected": "-", "Observed": "-"}
    assert CommonResourceCheck(adapter).build_execution_display({}) == {}
    assert check._get_field_value({"configuration": "bad"}, "configuration.size") is None
    assert check._build_validation_display({}, {}) == {}


def test_common_check_default_existence_predicate():
    adapter = MagicMock()
    adapter.capture.return_value = {"exists": True}
    result = CommonResourceCheck(adapter).validate({}, {"exists": True})
    assert result["passed"] is True
    assert result["checks"] == {"exists": True}


@pytest.mark.parametrize(
    "experiment_id",
    [
        "ec2-incremental-instance-stop",
        "ec2-ebs-volume-detach",
        "ecs-cpu-modification",
        "elb-cross-zone",
        "elb-listener",
        "elb-load-balancer",
        "elb-target-group",
        "api-gateway-access-logging",
        "s3-bucket-policy",
        "apigateway-access-logging",
    ],
)
def test_resolver_remaining_common_check_branches(experiment_id):
    check = CheckResolver().resolve(SimpleNamespace(id=experiment_id, variables={}))
    assert isinstance(check, CommonResourceCheck)
    assert check.name == f"{experiment_id}-lifecycle"


def test_resolver_replica_check_and_vpc_capture_wrapper(monkeypatch):
    discovery = MagicMock()
    replica = CheckResolver().resolve(
        SimpleNamespace(id="eks-replica-reduction", variables={}), discovery
    )
    assert replica is not None

    capture = MagicMock(return_value={"exists": True})
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.aws_adapters.VPCResourceAdapter.capture", capture
    )
    check = CheckResolver().resolve(SimpleNamespace(id="vpc-route-table", variables={}))
    check.adapter.capture({"id": "rtb-1"})
    capture.assert_called_once_with({"id": "rtb-1", "resource_type": "route-table"})


def test_dispatcher_azure_missing_runners_and_mesh_observer():
    toolkit = MagicMock()
    toolkit.execute.return_value = "azure-result"
    mesh = MagicMock()
    mesh.execute.return_value = "mesh-result"
    gate = MagicMock()
    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=toolkit,
        chaos_mesh_runner=mesh,
        chaos_mesh_execution_gate=gate,
    )
    azure = SimpleNamespace(engine="Azure Chaos Studio")
    assert dispatcher.execute(azure) == "azure-result"

    observer = MagicMock()
    chaos_mesh = SimpleNamespace(engine="Chaos Mesh")
    assert dispatcher.execute(chaos_mesh, observer) == "mesh-result"
    mesh.execute.assert_called_once_with(chaos_mesh, observer=observer)

    dispatcher.fis_runner = None
    with pytest.raises(RuntimeError, match="FIS execution engine"):
        dispatcher._execute_fis(SimpleNamespace())
    dispatcher.chaos_mesh_runner = None
    with pytest.raises(RuntimeError, match="Chaos Mesh execution engine"):
        dispatcher._execute_chaos_mesh(SimpleNamespace())


def test_web_service_fallback_invalid_experiment_and_invalid_submission(
    monkeypatch, client
):
    rendered = MagicMock(return_value="rendered")
    monkeypatch.setattr(web_app, "render_template", rendered)
    monkeypatch.setattr(web_app, "load_metadata", lambda _: None)
    assert client.get("/service/new-service").status_code == 200
    assert rendered.call_args.kwargs["service"]["has_custom_experiments"] is False
    assert client.get("/experiment/new-service/fault").status_code == 404

    metadata = {"experiments": [{"id": "fault", "inputs": []}]}
    monkeypatch.setattr(web_app, "load_metadata", lambda _: metadata)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(web_app, "normalize_values", lambda *_: ({}, {"field": "required"}))
    response = client.post("/experiment/lambda/fault", data={})
    assert response.status_code == 400
    assert rendered.call_args.kwargs["errors"] == {"field": "required"}
    assert client.get("/experiment/lambda/missing").status_code == 404


def test_web_aks_submission_enriches_identity_and_labels(monkeypatch, client):
    metadata = {"experiments": [{"id": "aks-pod-kill", "inputs": []}]}
    monkeypatch.setattr(web_app, "load_metadata", lambda _: metadata)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Test subscription",
        },
    )
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(
        web_app,
        "normalize_values",
        lambda *_: (
            {"aks_context": "cluster", "namespace": "apps", "deployment": "api"},
            {},
        ),
    )
    discovery = MagicMock()
    discovery.get_label_selector.return_value = ("app", "api")
    discovery.get_safe_label_selector.return_value = {"app": "api"}
    groups = MagicMock()
    groups.list_aks_cluster_names.return_value = ["cluster"]
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(web_app, "AzureResourceDiscovery", MagicMock(return_value=groups))
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: SimpleNamespace(campaign_id="campaign-1"))

    response = client.post(
        "/experiment/aks/aks-pod-kill",
        data={"subscription_id": "sub", "resource_group": "rg", "location": "east"},
    )

    assert response.status_code == 302
    values = add.call_args.args[2]
    assert values == {
        "aks_context": "cluster",
        "namespace": "apps",
        "deployment": "api",
            "subscription_id": "sub",
            "resource_group": "rg",
            "aks_name": "cluster",
            "label_key": "app",
        "label_val": "api",
    }


def test_web_aks_fixed_mode_rejects_more_targets_than_matching_pods(monkeypatch, client):
    metadata = {"service": "aks", "experiments": [{"id": "aks-container-kill", "inputs": []}]}
    monkeypatch.setattr(web_app, "load_metadata", lambda _: metadata)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(
        web_app,
        "normalize_values",
        lambda *_: (
            {
                "aks_context": "cluster",
                "namespace": "apps",
                "deployment": "api",
                "target_mode": "deployment",
                "chaos_mode": "fixed",
                "chaos_value": "3",
            },
            {},
        ),
    )
    discovery = MagicMock()
    discovery.get_label_selector.return_value = ("app", "api")
    discovery.get_pod_count.return_value = 2
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    rendered = MagicMock(return_value="validation error")
    monkeypatch.setattr(web_app, "render_template", rendered)

    response = client.post(
        "/experiment/aks/aks-container-kill",
        data={"subscription_id": "sub", "resource_group": "rg"},
    )

    assert response.status_code == 400
    assert rendered.call_args.kwargs["errors"] == {
        "chaos_value": "Mode Value cannot exceed the matching pod count (2)."
    }
    discovery.get_pod_count.assert_called_once_with("cluster", "apps", "app", "api")


def test_web_resource_discovery_skips_children_and_handles_provider_failure(
    monkeypatch, client
):
    metadata = {
        "experiments": [
            {
                "id": "fault",
                "inputs": [
                    {
                        "name": "child",
                        "type": "aws_resource",
                        "resource_type": "lambda",
                        "parent": "root",
                    },
                    {
                        "name": "root",
                        "type": "aws_resource",
                        "resource_type": "lambda",
                    },
                ],
            }
        ]
    }
    monkeypatch.setattr(web_app, "load_metadata", lambda _: metadata)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {})
    discovery = MagicMock()
    discovery.discover.side_effect = RuntimeError("provider unavailable")
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(web_app, "render_template", MagicMock(return_value="page"))

    assert client.get("/experiment/lambda/fault").status_code == 200
    discovery.discover.assert_called_once_with("lambda")
    assert web_app.render_template.call_args.kwargs["discovered_resources"] == []


def test_web_fis_and_resource_apis(monkeypatch, client):
    fis = MagicMock()
    fis.get_experiments.return_value = [{"id": "stop"}]
    fis.get_experiment.return_value = {"parameters": [{"name": "duration"}]}
    monkeypatch.setattr(web_app, "FISCatalog", MagicMock(return_value=fis))
    selector = MagicMock()
    selector.get_resources.return_value = [{"id": "resource"}]
    selector.select_child_resources.return_value = [{"id": "child"}]
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: "description")

    assert client.get("/api/fis/experiments/ec2").get_json() == [{"id": "stop"}]
    assert client.get("/api/fis/resources/ec2/west").get_json() == [{"id": "resource"}]
    assert client.get("/api/fis/parameters/ec2/stop").get_json() == [
        {"name": "duration"}
    ]
    assert client.get("/api/fis/descriptions/ec2/stop").get_json() == "description"
    assert client.get("/api/resources/lambda/west").get_json() == [{"id": "resource"}]
    assert client.get(
        "/api/resources/eks-namespace/cluster::apps/eks-deployment/west"
    ).get_json() == [{"id": "child"}]
    selector.select_child_resources.assert_called_with(
        "eks-namespace", ("cluster", "apps"), "eks-deployment"
    )


def test_all_aks_discovery_api_routes(monkeypatch, client):
    discovery = MagicMock()
    discovery.list_contexts.return_value = ["cluster"]
    discovery.list_namespaces.return_value = ["apps"]
    discovery.list_deployments.return_value = ["api"]
    discovery.list_nodes.return_value = ["node"]
    discovery.list_zones.return_value = ["zone-1"]
    discovery.list_containers.return_value = ["server"]
    groups = MagicMock()
    groups.list_aks_cluster_names.return_value = ["cluster"]
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(web_app, "AzureResourceDiscovery", MagicMock(return_value=groups))

    expected = {
        "/api/azure/aks/contexts": "cluster",
        "/api/azure/aks/namespaces/cluster": "apps",
        "/api/azure/aks/deployments/cluster/apps": "api",
        "/api/azure/aks/nodes/cluster": "node",
        "/api/azure/aks/zones/cluster": "zone-1",
        "/api/azure/aks/containers/cluster/apps/api": "server",
    }
    for route, value in expected.items():
        assert client.get(route).get_json() == [{"id": value, "name": value}]

    generic = {
        "azure_aks_cluster": "cluster",
        "azure_aks_namespace": "apps",
        "azure_aks_deployment": "api",
        "azure_aks_container": "server",
        "azure_aks_node": "node",
        "azure_aks_zone": "zone-1",
    }
    for resource_type, value in generic.items():
        response = client.get(
            f"/api/azure/aks/resources/{resource_type}",
            query_string={
                "context": "cluster", "namespace": "apps", "deployment": "api",
                "resource_group": "rg", "subscription_id": "sub",
            },
        )
        assert response.get_json() == [{"id": value, "name": value}]
        response = client.post(
            f"/api/azure/aks/resources/{resource_type}",
            json={
                "context": "cluster", "namespace": "apps", "deployment": "api",
                "resource_group": "rg", "subscription_id": "sub",
            },
        )
        assert response.get_json() == [{"id": value, "name": value}]
    response = client.get("/api/azure/aks/resources/unknown")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Unsupported AKS resource type"}


def test_web_security_group_rule_api_preserves_zero_based_rule_ids(client, monkeypatch):
    selector = MagicMock()
    rules = [
        {"id": 0, "name": "TCP | 80 | 10.0.0.0/8"},
        {"id": 1, "name": "TCP | 443 | 10.0.0.0/8"},
        {"id": 2, "name": "TCP | 8080 | 10.0.0.0/8"},
    ]
    selector.select_child_resources.return_value = rules
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))

    response = client.get(
        "/api/resources/security-group/sg-123/security-group-rule/eu-west-1"
    )

    assert response.get_json() == rules
    selector.select_child_resources.assert_called_once_with(
        "security-group", "sg-123", "security-group-rule"
    )


def test_web_resource_dropdowns_accept_zero_as_a_valid_identifier():
    template = (
        Path(web_app.app.template_folder) / "experiment.html"
    ).read_text(encoding="utf-8")

    assert template.count('value === undefined || value === null || value === ""') == 1


def test_aks_resource_browser_endpoint_allowlist_matches_server_routes():
    script = (
        web_app.app.static_folder
        and (Path(web_app.app.static_folder) / "azure-experiment.js").read_text(encoding="utf-8")
    )
    expected_types = {
        "azure_aks_cluster",
        "azure_aks_namespace",
        "azure_aks_deployment",
        "azure_aks_container",
        "azure_aks_node",
        "azure_aks_zone",
    }

    assert script
    for resource_type in expected_types:
        assert f'"/api/azure/aks/resources/{resource_type}"' in script
    assert "switch (type)" in script
    assert "method: \"POST\"" in script
    assert "fetch(url)" not in script


def test_web_campaign_operational_and_report_routes(monkeypatch, client, tmp_path):
    campaign = SimpleNamespace(
        experiments=[SimpleNamespace(service="lambda")],
        cloud_provider="aws",
        name="Campaign",
        continue_on_failure=False,
    )
    monkeypatch.setattr(web_app, "get_current_campaign", MagicMock(return_value=campaign))
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "render_template", MagicMock(return_value="page"))
    monkeypatch.setattr(web_app, "remove_experiment", remove := MagicMock())
    monkeypatch.setattr(web_app, "clear_current_campaign", clear := MagicMock())
    monkeypatch.setattr(web_app, "_consume_permission_review_token", lambda *_: True)
    start = MagicMock()
    selected_executor = SimpleNamespace(start=start)
    start.return_value = "run-1"
    monkeypatch.setattr(web_app, "get_executor", MagicMock(return_value=selected_executor))
    logs = MagicMock()
    logs.get_logs.return_value = ["line"]
    logs.lines = ["one", "two"]
    logs.current = 1
    logs.total = 2
    logs.current_experiment = "fault"
    logs.running = True
    logs.finished = False
    monkeypatch.setattr(web_app, "get_log_manager", lambda cloud=None: logs)

    assert client.get("/campaign").status_code == 200
    assert client.get("/campaign/remove/2").status_code == 302
    assert client.get("/campaign/clear").status_code == 302
    assert client.get("/campaign/save").status_code == 404
    assert client.get("/campaign/execute?cloud=aws").status_code == 302
    assert client.get("/execution").status_code == 200
    assert client.get("/execution/logs").get_json() == ["line"]
    assert client.get("/progress").get_json() == {
        "current": 1,
        "total": 2,
        "experiment": "fault",
        "running": True,
        "finished": False,
    }
    assert client.get("/download_logs").data == b"one\ntwo"
    remove.assert_called_once_with(2)
    clear.assert_called_once_with()
    assert start.call_args.args[0].name == "Campaign"

    monkeypatch.setattr(web_app, "REPORTS_DIR", tmp_path)
    assert client.get("/report/download").status_code == 404
    report = tmp_path / "report.txt"
    report.write_text("result", encoding="utf-8")
    response = client.get("/report/download")
    assert response.status_code == 200
    assert response.data == b"result"


def test_web_edit_campaign_redirects_to_experiment_with_edit_index(monkeypatch, client):
    stored = SimpleNamespace(service="aks", id="fault", variables={})
    monkeypatch.setattr(web_app, "get_experiment", lambda _: stored)
    monkeypatch.setattr(web_app, "load_metadata", lambda _: {"experiments": [{"id": "fault"}]})

    response = client.get("/campaign/edit/3")

    assert response.status_code == 200
    assert b'action="/experiment/aks/fault?edit_index=3"' in response.data


def test_web_edit_fis_campaign_preserves_selected_catalog_identity(monkeypatch, client):
    stored = SimpleNamespace(
        service="fis",
        id="fis-create-experiment",
        variables={"service_id": "ec2", "experiment_id": "stop-instances"},
    )
    monkeypatch.setattr(web_app, "get_experiment", lambda _: stored)

    response = client.get("/campaign/edit/3")

    assert response.status_code == 200
    assert b"fis_service_id=ec2" in response.data
    assert b"fis_experiment_id=stop-instances" in response.data


def test_web_edit_campaign_rejects_untrusted_persisted_experiment_identity(monkeypatch, client):
    stored = SimpleNamespace(service="//attacker.invalid", id="evil", variables={})
    monkeypatch.setattr(web_app, "get_experiment", lambda _: stored)
    monkeypatch.setattr(web_app, "load_metadata", lambda _: None)

    response = client.get("/campaign/edit/3")

    assert response.status_code == 404
    assert "attacker.invalid" not in response.get_data(as_text=True)


def test_web_edit_campaign_rejects_invalid_persisted_fis_identity(monkeypatch, client):
    stored = SimpleNamespace(
        service="fis",
        id="fis-create-experiment",
        variables={"service_id": "attacker", "experiment_id": "malicious"},
    )
    monkeypatch.setattr(web_app, "get_experiment", lambda _: stored)
    monkeypatch.setattr(web_app, "load_metadata", lambda _: {"experiments": [{"id": "fis-create-experiment"}]})
    monkeypatch.setattr(
        web_app,
        "FISCatalog",
        MagicMock(return_value=SimpleNamespace(get_experiment=lambda *_: None)),
    )

    response = client.get("/campaign/edit/3")

    assert response.status_code == 404


def test_flat_menu_includes_and_executes_chaos_mesh(monkeypatch):
    monkeypatch.setattr(menu_flat, "FISCatalog", lambda: SimpleNamespace(get_menu_items=lambda _: []))
    monkeypatch.setattr(
        menu_flat,
        "get_experiments",
        lambda service: (
            [{"id": "mesh-fault", "name": "Mesh Fault"}]
            if service == "chaos_mesh"
            else []
        ),
    )
    monkeypatch.setattr(menu_flat, "prompt", MagicMock(side_effect=["1", "0"]))
    monkeypatch.setattr(menu_flat, "menu", MagicMock())
    monkeypatch.setattr(menu_flat, "section", MagicMock())
    monkeypatch.setattr(menu_flat.console, "print", MagicMock())
    execute = MagicMock()
    monkeypatch.setattr(menu_flat, "execute_experiment", execute)

    menu_flat.experiment_menu("eks")

    execute.assert_called_once_with("mesh-fault", prefill=None)


def test_input_engine_fis_and_resource_failure_paths(monkeypatch):
    selector = MagicMock()
    selector.select.return_value = None
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())
    monkeypatch.setattr(input_engine, "get_input", MagicMock(return_value="1"))
    catalog_mock = MagicMock()
    catalog_mock.get_experiments.return_value = [
        {
            "id": "fault",
            "name": "Fault",
            "parameters": [
                {
                    "name": "target",
                    "label": "Target",
                    "type": "aws_resource",
                    "resource_type": "lambda",
                }
            ],
        }
    ]
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog_mock))
    assert input_engine.collect_inputs(
        {"name": "FIS", "inputs": [{"name": "experiment_id", "label": "Experiment"}]},
        prefill={"service_id": "lambda"},
    ) is None

    selector.select.return_value = {"name": "missing id"}
    with pytest.raises(ValueError, match="does not contain 'id'"):
        input_engine.collect_inputs(
            {"name": "FIS", "inputs": [{"name": "experiment_id", "label": "Experiment"}]},
            prefill={"service_id": "lambda"},
        )


@pytest.mark.parametrize("service", ["ecs", "s3"])
def test_input_engine_fis_special_targets(monkeypatch, service):
    selector = MagicMock()
    selector.select.return_value = {"id": f"{service}-target"}
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())
    catalog_mock = MagicMock()
    catalog_mock.get_experiment.return_value = {}
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog_mock))
    result = input_engine.collect_inputs(
        {"name": "FIS", "inputs": [{"name": "target_arn", "label": "Target"}]},
        prefill={"service_id": service, "experiment_id": "fault"},
    )
    assert result["target_arn"] == f"{service}-target"
    selector.select.assert_called_once_with("ecs_task" if service == "ecs" else "s3")


@pytest.mark.parametrize("resource", [None, {"name": "missing identifier"}])
def test_input_engine_target_selection_rejects_missing_resource_identity(
    monkeypatch, resource
):
    selector = MagicMock()
    selector.select.return_value = resource
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())
    catalog_mock = MagicMock()
    catalog_mock.get_experiment.return_value = {}
    monkeypatch.setattr(input_engine, "FISCatalog", MagicMock(return_value=catalog_mock))
    metadata = {
        "name": "FIS",
        "inputs": [{"name": "target_arn", "label": "Target"}],
    }

    if resource is None:
        assert input_engine.collect_inputs(
            metadata, prefill={"service_id": "lambda", "experiment_id": "fault"}
        ) is None
    else:
        with pytest.raises(ValueError, match="does not contain an ARN or ID"):
            input_engine.collect_inputs(
                metadata, prefill={"service_id": "lambda", "experiment_id": "fault"}
            )


def test_input_engine_child_resource_variants_and_cancellation(monkeypatch):
    selector = MagicMock()
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())

    selector.select.return_value = {"id": "i-1"}
    selector.select_available_ebs_volume.return_value = None
    metadata = {
        "name": "EBS",
        "inputs": [
            {"name": "instance", "label": "Instance", "type": "aws_resource", "resource_type": "ec2", "return": "id"},
            {"name": "volume", "label": "Volume", "type": "aws_resource", "resource_type": "ebs-volume-available", "parent": "instance", "return": "id"},
        ],
    }
    assert input_engine.collect_inputs(metadata) is None

    selector.select_multiple.return_value = None
    assert input_engine.collect_inputs(
        {"name": "Many", "inputs": [{"name": "items", "label": "Items", "type": "aws_resource", "resource_type": "lambda", "multiple": True}]}
    ) is None


def test_input_engine_boolean_conversion_paths(monkeypatch):
    monkeypatch.setattr(input_engine, "title", MagicMock())
    monkeypatch.setattr(input_engine.Validator, "validate", lambda *_: (True, ""))
    report = MagicMock()
    monkeypatch.setattr(input_engine, "error", report)
    monkeypatch.setattr(input_engine, "get_input", MagicMock(side_effect=["maybe", "yes", "no"]))
    result = input_engine.collect_inputs(
        {
            "name": "Booleans",
            "inputs": [
                {"name": "enabled", "label": "Enabled", "type": "boolean"},
                {"name": "disabled", "label": "Disabled", "type": "boolean"},
            ],
        }
    )
    assert result["enabled"] is True
    assert result["disabled"] is False
    report.assert_called_once_with("Enter a valid boolean value.")
