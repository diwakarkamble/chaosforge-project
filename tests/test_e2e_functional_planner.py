import pytest

from e2e.webui.functional.manifest import ManifestError
from e2e.webui.functional.planner import (
    group_cases_by_cloud,
    parse_components,
    parse_experiments,
    parse_tags,
    plan_cases,
    plan_tag_cases,
)


@pytest.mark.parametrize(
    ("cloud", "service", "fields", "expected"),
    [
        ("aws", "apigateway", [
            {"name": "rest_api_id", "type": "aws_resource", "resource_type": "apigateway"},
            {"name": "stage_name", "type": "aws_resource", "resource_type": "apigateway-stage", "parent": "rest_api_id"},
        ], ["rest_api_id", "stage_name"]),
        ("aws", "ecs", [
            {"name": "ecs_cluster", "type": "aws_resource", "resource_type": "ecs"},
            {"name": "ecs_service", "type": "aws_resource", "resource_type": "ecs-service", "parent": "ecs_cluster"},
        ], ["ecs_cluster", "ecs_service"]),
        ("azure", "azure_key_vault", [
            {"name": "resource_id", "type": "azure_component_resource"},
            {"name": "certificate_name", "type": "text", "required": True},
        ], ["resource_id", "certificate_name"]),
        ("azure", "azure_redis", [
            {"name": "redis_name", "type": "azure_redis_cache", "required": True},
        ], ["redis_name"]),
    ],
)
def test_graph_contracts_project_metadata_children_and_nonstandard_roots(cloud, service, fields, expected):
    from e2e.webui.functional.catalog import graph_resource_fields

    graph = graph_resource_fields(cloud, service, fields)

    assert [field["name"] for field in graph] == expected
    if service == "azure_key_vault":
        assert graph[-1] == {
            "name": "certificate_name", "type": "azure_component_resource", "required": True,
            "resource_type": "azure_key_vault_certificates", "parent": "resource_id",
        }
    if service == "azure_redis":
        assert graph[0]["resource_type"] == "Microsoft.Cache/Redis"


def test_graph_contracts_cover_all_child_discovery_aliases():
    from e2e.webui.functional.catalog import GRAPH_CONTRACTS

    assert {
        "elasticache", "azure_vmss", "azure_app_service", "azure_functions", "azure_container_apps",
        "azure_key_vault", "azure_postgres_flexible", "azure_cosmos_db", "azure_redis",
    } <= set(GRAPH_CONTRACTS)
    assert GRAPH_CONTRACTS["eks"]["skip_reason"]


def manifest():
    return {
        "defaults": {"mode": "tags", "tags": {"Chaosforge": "E2E-Test"}},
        "components": {
            "aws": {
                "lambda": {
                    "region": "eu-central-1",
                    "selector": "#function_name",
                    "target_variable": "lambda_name",
                    "inputs": {"wait_seconds": 30},
                    "experiments": ["aws-lambda-concurrency"],
                }
            },
            "azure": {
                "azure_vm": {
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "selector": "#resource_id",
                    "target_variable": "resource_id",
                    "experiments": ["azure-vm-reboot"],
                    "resources": [{"name": "e2e-vm"}],
                }
            },
        },
    }


def test_plan_cases_filters_cloud_components_and_overrides_tags():
    cases = plan_cases(
        manifest(), cloud_filter="aws", component_filter={"lambda"},
        tag_override={"ManagedBy": "ChaosForge"}, execute_override=True,
    )

    assert len(cases) == 1
    assert cases[0].cloud == "aws"
    assert cases[0].target["target"] == {"ManagedBy": "ChaosForge"}
    assert cases[0].execute is True
    assert cases[0].inputs == {"wait_seconds": 30}


def test_plan_cases_supports_explicit_mode_and_validation():
    cases = plan_cases(manifest(), cloud_filter="azure", mode_override="explicit")

    assert cases[0].target["target_type"] == "name"
    assert cases[0].target["target"] == "e2e-vm"
    with pytest.raises(ManifestError, match="absent from manifest"):
        plan_cases(manifest(), component_filter={"missing"})


def test_fis_execution_role_is_required_and_cli_option_overrides_configured_value(monkeypatch):
    monkeypatch.setattr(
        "e2e.webui.functional.planner.experiment_metadata",
        lambda service, experiment: {"inputs": [{"name": "role_arn", "required": True}]}
        if (service, experiment) == ("fis", "fis-create-experiment") else None,
    )
    fis_manifest = {
        "defaults": {"mode": "explicit"},
        "components": {"aws": {"fis": {
            "region": "eu-west-1", "selector": "#target_arn", "target_variable": "target_arn",
            "experiments": ["fis-create-experiment"], "resources": [{"name": "target"}],
        }}},
    }

    with pytest.raises(ManifestError, match="requires an AWS FIS execution role"):
        plan_cases(fis_manifest)
    cases = plan_cases(fis_manifest, aws_fis_role_arn="arn:aws:iam::123456789012:role/FIS")

    assert cases[0].inputs["role_arn"] == "arn:aws:iam::123456789012:role/FIS"


def test_group_cases_by_cloud_creates_one_campaign_group_per_cloud():
    cases = plan_cases(manifest())

    groups = group_cases_by_cloud(cases)

    assert [(group.cloud, len(group.cases)) for group in groups] == [("aws", 1), ("azure", 1)]


def test_combined_group_preserves_every_planned_experiment():
    cases = plan_cases(manifest())
    groups = group_cases_by_cloud(cases)

    assert {case.id for group in groups for case in group.cases} == {case.id for case in cases}


def test_parse_component_and_tag_arguments():
    assert parse_components("all") is None
    assert parse_components("lambda, azure_vm") == {"lambda", "azure_vm"}
    assert parse_tags(["Chaosforge=E2E-Test", "ManagedBy=ChaosForge"]) == {
        "Chaosforge": "E2E-Test", "ManagedBy": "ChaosForge",
    }
    with pytest.raises(ManifestError, match="KEY=VALUE"):
        parse_tags(["invalid"])
    assert parse_experiments(["ec2:stop-instances,s3:s3-versioning", "ec2:reboot-instances"]) == {
        "ec2": {"stop-instances", "reboot-instances"}, "s3": {"s3-versioning"},
    }
    with pytest.raises(ManifestError, match="COMPONENT:EXPERIMENT"):
        parse_experiments(["stop-instances"])


def test_plan_tag_cases_uses_built_in_catalog_without_a_manifest(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    resolved = []

    def resolve_identity(value, subscription_id):
        resolved.append((value, subscription_id))
        return "found", "/identities/chaos", ""

    monkeypatch.setattr("e2e.webui.functional.planner.resolve_chaos_identity", resolve_identity)

    cases = plan_tag_cases(
        cloud_filter="azure",
        component_filter={"azure_vm"},
        tags={"Chaosforge": "E2E-Test"},
        aws_region=None,
        azure_chaos_identity="/identities/chaos",
        vm_shutdown_duration="PT1M",
        vm_abrupt_shutdown=False,
        azure_subscription="web-ui-subscription",
        execute_override=True,
    )

    assert [case.experiment for case in cases] == [
        "azure-vm-redeploy", "azure-vm-shutdown", "azure-vm-toolkit-reboot", "azure-vm-boot-diagnostics-toggle",
    ]
    assert cases[0].inputs["chaos_identity_id"] == "/identities/chaos"
    assert cases[1].inputs["duration"] == "PT1M"
    assert cases[1].inputs["abrupt_shutdown"] is False
    assert cases[1].inputs["chaos_identity_id"] == "/identities/chaos"
    assert cases[-1].target["target"] == {"Chaosforge": "E2E-Test"}
    assert cases[-1].execute is True
    assert resolved == [("/identities/chaos", "web-ui-subscription")]


def test_tag_experiment_filter_requires_the_named_component_to_offer_it(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.TAG_CATALOG",
        {"aws": {"ec2": {
            "selector": "#instance_ids", "target_variable": "instance_ids",
            "experiments": [{"id": "ec2-incremental-instance-stop"}],
        }}},
    )

    cases = plan_tag_cases(
        cloud_filter="aws", component_filter={"ec2"}, tags={"E2E": "yes"}, aws_region="eu-west-1",
        azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        experiment_filter={"ec2": {"ec2-incremental-instance-stop"}},
    )

    assert [case.experiment for case in cases] == ["ec2-incremental-instance-stop"]
    with pytest.raises(ManifestError, match="not available for ec2"):
        plan_tag_cases(
            cloud_filter="aws", component_filter={"ec2"}, tags={"E2E": "yes"}, aws_region="eu-west-1",
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
            experiment_filter={"ec2": {"s3-versioning"}},
        )


def test_tag_filters_bind_selected_ec2_fis_actions_to_the_generic_fis_experiment(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    cases = plan_tag_cases(
        cloud_filter="aws", component_filter={"ec2"}, tags={"E2E": "yes"}, aws_region="eu-west-1",
        azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        aws_fis_role_arn="arn:aws:iam::123456789012:role/FIS",
        experiment_filter={"ec2": {"stop-instances", "reboot-instances", "terminate-instances"}},
    )

    assert [(case.service, case.experiment) for case in cases] == [
        ("fis", "fis-create-experiment"),
        ("fis", "fis-create-experiment"),
        ("fis", "fis-create-experiment"),
    ]
    assert {case.target["fis_experiment_id"] for case in cases} == {
        "stop-instances", "reboot-instances", "terminate-instances",
    }
    assert all(case.target["resolver_service"] == "ec2" for case in cases)
    assert all(case.inputs["role_arn"] == "arn:aws:iam::123456789012:role/FIS" for case in cases)
    assert all("created_by" not in case.inputs for case in cases)
    assert cases[-1].target["fis_experiment_id"] == "terminate-instances"
    assert {case.target["fis_experiment_id"] for case in cases[:2]} == {
        "reboot-instances", "stop-instances",
    }


def test_tag_filter_allows_chaos_mesh_experiment_under_the_eks_component(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.TAG_CATALOG",
        {"aws": {"eks": {}}},
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.catalog_experiments",
        lambda service, _config: [{"id": "chaos-mesh-pod-failure"}] if service == "chaos_mesh" else [],
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.experiment_metadata",
        lambda service, experiment: {
            "id": experiment,
            "inputs": [
                {"name": "aws_region", "type": "text", "default": "eu-central-1"},
                {"name": "eks_cluster", "type": "aws_resource", "resource_type": "eks", "required": True},
                {"name": "namespace", "type": "aws_resource", "resource_type": "eks-namespace", "parent": "eks_cluster", "required": True},
                {"name": "pod", "type": "aws_resource", "resource_type": "eks-pod", "parent": "namespace", "required": False},
            ],
        }
        if service == "chaos_mesh" and experiment == "chaos-mesh-pod-failure"
        else None,
    )

    cases = plan_tag_cases(
        cloud_filter="aws",
        component_filter={"eks"},
        experiment_filter={"chaos_mesh": {"chaos-mesh-pod-failure"}},
        tags={"Chaosforge": "E2E-Test"},
        aws_region="eu-central-1",
        azure_chaos_identity="",
        vm_shutdown_duration="PT1M",
        vm_abrupt_shutdown=False,
        input_values={
            "defaults": {},
            "components": {
                "eks": {
                    "experiments": {
                        "chaos-mesh-pod-failure": {
                            "namespace": "sample-app",
                            "pod": "sample-app-123",
                        }
                    }
                }
            },
        },
        execute_override=True,
    )

    assert len(cases) == 1
    case = cases[0]
    assert (case.service, case.experiment) == ("chaos_mesh", "chaos-mesh-pod-failure")
    assert case.target["resolver_service"] == "eks"
    assert case.target_variable == "eks_cluster"
    assert [field["name"] for field in case.resource_fields] == ["eks_cluster"]
    assert case.inputs["namespace"] == "sample-app"
    assert case.inputs["pod"] == "sample-app-123"


def test_tag_filter_allows_eks_workload_experiment_with_explicit_kubernetes_inputs(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr("e2e.webui.functional.planner.TAG_CATALOG", {"aws": {"eks": {}}})
    monkeypatch.setattr(
        "e2e.webui.functional.planner.catalog_experiments",
        lambda *_: [{"id": "eks-container-restart"}],
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.experiment_metadata",
        lambda *_: {
            "inputs": [
                {"name": "eks_cluster", "type": "aws_resource", "resource_type": "eks", "required": True},
                {"name": "namespace", "type": "aws_resource", "resource_type": "eks-namespace", "parent": "eks_cluster", "required": True},
                {"name": "pod_name", "type": "aws_resource", "resource_type": "eks-pod", "parent": "namespace", "required": True},
                {"name": "aws_region", "type": "text", "default": "eu-central-1"},
            ]
        },
    )

    cases = plan_tag_cases(
        cloud_filter="aws",
        component_filter={"eks"},
        experiment_filter={"eks": {"eks-container-restart"}},
        tags={"Chaosforge": "E2E-Test"},
        aws_region="eu-central-1",
        azure_chaos_identity="",
        vm_shutdown_duration="PT1M",
        vm_abrupt_shutdown=False,
        input_values={
            "defaults": {},
            "components": {
                "eks": {
                    "experiments": {
                        "eks-container-restart": {
                            "namespace": "sample-app",
                            "pod_name": "sample-app-123",
                        }
                    }
                }
            },
        },
        strict_inputs=True,
    )

    assert len(cases) == 1
    assert cases[0].skip_reason == ""
    assert cases[0].target["resolver_service"] == "eks"
    assert [field["name"] for field in cases[0].resource_fields] == ["eks_cluster"]


def test_tag_filters_bind_elasticache_replication_group_fis_action(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)

    cases = plan_tag_cases(
        cloud_filter="aws", component_filter={"elasticache"}, tags={"E2E": "yes"},
        aws_region="eu-west-1", azure_chaos_identity="", vm_shutdown_duration="PT1M",
        vm_abrupt_shutdown=False, aws_fis_role_arn="arn:aws:iam::123456789012:role/FIS",
        experiment_filter={"elasticache": {"interrupt-az-power"}},
    )

    assert [(case.service, case.experiment) for case in cases] == [
        ("fis", "fis-create-experiment")
    ]
    assert cases[0].target["resolver_service"] == "elasticache"
    assert cases[0].target["fis_experiment_id"] == "interrupt-az-power"

    with pytest.raises(ManifestError, match="requires an AWS FIS execution role"):
        plan_tag_cases(
            cloud_filter="aws", component_filter={"ec2"}, tags={"E2E": "yes"}, aws_region="eu-west-1",
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
            experiment_filter={"ec2": {"stop-instances"}},
        )
    with pytest.raises(ManifestError, match="not tag-resolvable for ec2"):
        plan_tag_cases(
            cloud_filter="aws", component_filter={"ec2"}, tags={"E2E": "yes"}, aws_region="eu-west-1",
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
            aws_fis_role_arn="arn:aws:iam::123456789012:role/FIS",
            experiment_filter={"ec2": {"spot-instance-interruption"}},
        )
    with pytest.raises(ManifestError, match="excluded by --e2e-components"):
        plan_tag_cases(
            cloud_filter="aws", component_filter={"ec2"}, tags={"E2E": "yes"}, aws_region="eu-west-1",
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
            experiment_filter={"s3": {"s3-versioning"}},
        )

    with pytest.raises(ManifestError, match="requires an AWS FIS execution role"):
        plan_tag_cases(
            cloud_filter="aws", component_filter={"ec2"}, tags={"E2E": "yes"}, aws_region="eu-west-1",
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
            experiment_filter={"ec2": {"stop-instances"}},
        )


def test_tag_filters_bind_kinesis_stream_fis_actions(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)

    cases = plan_tag_cases(
        cloud_filter="aws", component_filter={"kinesis"}, tags={"E2E": "yes"},
        aws_region="eu-central-1", azure_chaos_identity="", vm_shutdown_duration="PT1M",
        vm_abrupt_shutdown=False, aws_fis_role_arn="arn:aws:iam::123456789012:role/FIS",
        experiment_filter={"kinesis": {
            "kinesis-provisioned-throughput-exception", "kinesis-expired-iterator-exception",
        }},
    )

    assert [(case.service, case.experiment) for case in cases] == [
        ("fis", "fis-create-experiment"), ("fis", "fis-create-experiment"),
    ]
    assert {case.target["fis_experiment_id"] for case in cases} == {
        "kinesis-provisioned-throughput-exception", "kinesis-expired-iterator-exception",
    }
    assert all(case.target["resolver_service"] == "kinesis" for case in cases)
    assert all(case.inputs["role_arn"] == "arn:aws:iam::123456789012:role/FIS" for case in cases)


def test_plan_tag_cases_resolves_contract_backed_required_text_input(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.experiment_metadata",
        lambda *_: {"inputs": [{"name": "certificate_name", "required": True, "type": "text"}]},
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.TAG_CATALOG",
        {"azure": {"azure_key_vault": {
            "resource_type": "Microsoft.KeyVault/vaults", "selector": "#resource_id", "target_variable": "resource_id",
            "experiments": [{"id": "azure-key-vault-disable-certificate", "inputs": {}}],
        }}},
    )

    cases = plan_tag_cases(
        cloud_filter="azure", component_filter={"azure_key_vault"}, tags={"E2E": "yes"},
        aws_region=None, azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
    )
    assert not cases[0].skip_reason
    assert cases[0].resource_fields[-1]["name"] == "certificate_name"


def test_tag_catalog_lists_every_non_aks_component_root():
    from e2e.webui.functional.catalog import TAG_CATALOG

    assert {
        "apigateway", "dynamodb", "ec2", "ecs", "eks", "elasticache", "elb", "kinesis", "lambda", "rds", "s3", "sns", "vpc",
    } <= set(TAG_CATALOG["aws"])
    assert {
        "azure_vm", "azure_vmss", "azure_app_service", "azure_functions", "azure_key_vault", "azure_cosmos_db",
        "azure_event_hub", "azure_postgres_flexible", "azure_container_apps", "azure_redis",
    } <= set(TAG_CATALOG["azure"])


def test_tag_cases_use_short_functional_defaults_and_inputs_file_overrides(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.TAG_CATALOG",
        {"azure": {"azure_vm": {"resource_type": "Microsoft.Compute/virtualMachines"}}},
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.catalog_experiments",
        lambda *_: [{"id": "azure-vm-boot-diagnostics-toggle"}],
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.experiment_metadata",
        lambda *_: {"inputs": [
            {"name": "resource_id", "type": "azure_component_resource", "required": True},
            {"name": "duration_seconds", "type": "integer", "required": True, "default": 300},
        ]},
    )

    defaults = plan_tag_cases(
        cloud_filter="azure", component_filter={"azure_vm"}, tags={"E2E": "yes"},
        aws_region=None, azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
    )
    overridden = plan_tag_cases(
        cloud_filter="azure", component_filter={"azure_vm"}, tags={"E2E": "yes"},
        aws_region=None, azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        input_values={
            "defaults": {"duration_seconds": 45},
            "components": {"azure_vm": {"experiments": {"azure-vm-boot-diagnostics-toggle": {"duration_seconds": 15}}}},
        },
    )

    assert defaults[0].inputs["duration_seconds"] == 60
    assert overridden[0].inputs["duration_seconds"] == 15


def test_tag_cases_use_built_in_event_hub_state_default(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.TAG_CATALOG",
        {"azure": {"azure_event_hub": {"resource_type": "Microsoft.EventHub/namespaces"}}},
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.catalog_experiments",
        lambda *_: [{"id": "azure-event-hub-state"}],
    )
    monkeypatch.setattr(
        "e2e.webui.functional.planner.experiment_metadata",
        lambda *_: {"inputs": [
                {"name": "resource_id", "type": "azure_component_resource", "required": True},
                {"name": "desired_state", "type": "choice", "required": True},
                {"name": "event_hubs", "type": "text", "required": True, "default": "*"},
        ]},
    )

    cases = plan_tag_cases(
        cloud_filter="azure", component_filter={"azure_event_hub"}, tags={"E2E": "yes"},
        aws_region=None, azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
    )

    assert cases[0].inputs["desired_state"] == "Disabled"
    assert [field["name"] for field in cases[0].resource_fields] == ["resource_id"]
    assert cases[0].inputs["event_hubs"] == "*"
    assert not cases[0].skip_reason


def test_plan_tag_cases_derives_metadata_cases_orders_and_skips_irreversible(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.TAG_CATALOG",
        {"azure": {"azure_key_vault": {"resource_type": "Microsoft.KeyVault/vaults"}}},
    )
    experiments = [
        {"id": "azure-key-vault-increment-certificate-version"},
        {"id": "azure-key-vault-deny-access"},
    ]
    monkeypatch.setattr("e2e.webui.functional.planner.catalog_experiments", lambda *_: experiments)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.experiment_metadata",
        lambda _service, experiment_id: {
            "id": experiment_id,
            "inputs": [
                {"name": "resource_id", "type": "azure_component_resource", "required": True},
                {"name": "duration", "type": "text", "default": "PT5M", "required": True},
            ],
        },
    )

    cases = plan_tag_cases(
        cloud_filter="azure", component_filter={"azure_key_vault"}, tags={"E2E": "yes"},
        aws_region=None, azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        input_values={"defaults": {"duration": "PT2M"}, "components": {}},
    )

    assert [case.experiment for case in cases] == [
        "azure-key-vault-deny-access", "azure-key-vault-increment-certificate-version",
    ]
    assert cases[0].inputs["duration"] == "PT2M"
    assert cases[0].target["resource_fields"] == [
        {"name": "resource_id", "type": "azure_component_resource", "required": True},
    ]
    assert [case.experiment for case in plan_tag_cases(
        cloud_filter="azure", component_filter={"azure_key_vault"}, tags={"E2E": "yes"},
        aws_region=None, azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        skip_irreversible=True,
    )] == ["azure-key-vault-deny-access"]


def test_plan_tag_cases_requires_tags_and_aws_region(monkeypatch):
    monkeypatch.setattr("e2e.webui.functional.planner.validate_tag_catalog", lambda: None)
    monkeypatch.setattr(
        "e2e.webui.functional.planner.resolve_chaos_identity", lambda *_: ("missing", "", "identity not found")
    )

    with pytest.raises(ManifestError, match="at least one --e2e-tag"):
        plan_tag_cases(
            cloud_filter="azure", component_filter=None, tags={}, aws_region=None,
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        )
    with pytest.raises(ManifestError, match="--e2e-aws-region"):
        plan_tag_cases(
            cloud_filter="aws",
            component_filter={"lambda"},
            tags={"Chaosforge": "E2E-Test"},
            aws_region=None,
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        )
    with pytest.raises(ManifestError, match="safe catalog"):
        plan_tag_cases(
            cloud_filter="azure",
            component_filter={"missing"},
            tags={"Chaosforge": "E2E-Test"},
            aws_region=None,
            azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        )
    with pytest.raises(ManifestError, match="--e2e-azure-chaos-identity"):
        plan_tag_cases(
            cloud_filter="azure", component_filter={"azure_vm"}, tags={"Chaosforge": "E2E-Test"},
            aws_region=None, azure_chaos_identity="", vm_shutdown_duration="PT1M", vm_abrupt_shutdown=False,
        )
