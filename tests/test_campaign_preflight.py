import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.application.services.campaign_preflight import CampaignPreflightService
from chaosforge.catalog import ExperimentCatalog


def _campaign(lambda_name="demo"):
    experiment = SimpleNamespace(
        id="lambda-memory",
        service="lambda",
        variables={"lambda_name": lambda_name, "aws_region": "eu-central-1"},
    )
    return SimpleNamespace(cloud_provider="aws", experiments=[experiment])


def test_preflight_rejects_template_and_identity_mismatch():
    service = CampaignPreflightService()
    identity = {"account_id": "123"}

    template = service.preflight(_campaign(), {"template": True}, identity)
    mismatch = service.preflight(_campaign(), {"environment": {"account_id": "999"}}, identity)

    assert template.ready is False
    assert "template" in template.errors[0].lower()
    assert mismatch.ready is False
    assert "999" in mismatch.errors[0]


def test_preflight_resolves_lambda_target(monkeypatch):
    client = MagicMock()
    client.get_function.return_value = {
        "Configuration": {"FunctionName": "demo", "FunctionArn": "arn:lambda:demo"}
    }
    monkeypatch.setattr("chaosforge.application.services.campaign_preflight.boto3.client", lambda *_args, **_kwargs: client)

    result = CampaignPreflightService().preflight(
        _campaign(),
        {"environment": {"account_id": "123"}},
        {"account_id": "123"},
    )

    assert result.ready is True
    assert result.targets[0]["arn"] == "arn:lambda:demo"


def test_preflight_blocks_missing_lambda_target(monkeypatch):
    client = MagicMock()
    client.get_function.side_effect = RuntimeError("ResourceNotFoundException")
    monkeypatch.setattr("chaosforge.application.services.campaign_preflight.boto3.client", lambda *_args, **_kwargs: client)

    result = CampaignPreflightService().preflight(
        _campaign("missing"),
        {"environment": {"account_id": "123"}},
        {"account_id": "123"},
    )

    assert result.ready is False
    assert "missing" in result.errors[0]


def test_preflight_resolves_azure_redis_and_aks_targets(monkeypatch):
    redis = SimpleNamespace(
        id="azure-redis-reboot",
        service="azure_redis",
        variables={
            "subscription_id": "sub",
            "resource_group": "rg",
            "redis_name": "cache",
            "chaos_identity_id": "/identities/chaosforge-managed-identity",
        },
    )
    aks = SimpleNamespace(id="aks-pod-kill", service="aks", variables={"aks_context": "cluster"})
    campaign = SimpleNamespace(cloud_provider="azure", experiments=[redis, aks])
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.AzureResourceDiscovery.list_redis_caches",
        lambda *_args: [{"id": "cache", "name": "cache"}],
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery.list_contexts",
        lambda *_args: ["cluster"],
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.AzureRedisChaosIdentityService.readiness",
        lambda *_args: {"status": "ready"},
    )

    result = CampaignPreflightService().preflight(
        campaign,
        {"environment": {"subscription_id": "sub"}},
        {"subscription_id": "sub"},
    )

    assert result.ready is True
    assert [target["service"] for target in result.targets] == ["azure_redis", "aks"]


def test_preflight_resolves_azure_resource_name_to_canonical_arm_id(monkeypatch):
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a"
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "inputs": [{"name": "resource_id", "type": "azure_component_resource"}]
    }
    campaign = SimpleNamespace(
        cloud_provider="azure",
        experiments=[
            SimpleNamespace(
                id="azure-vm-toolkit-reboot",
                service="azure_vm",
                variables={"resource_name": "vm-a", "resource_group": "rg"},
            )
        ],
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.list_component_resources",
        lambda *_args: [{"id": resource_id, "name": "vm-a"}],
    )

    result = CampaignPreflightService(catalog).preflight(
        campaign,
        {"environment": {"subscription_id": "sub"}},
        {"subscription_id": "sub"},
    )

    assert result.ready is True
    assert campaign.experiments[0].variables == {
        "subscription_id": "sub",
        "resource_group": "rg",
        "resource_id": resource_id,
    }


def test_preflight_rejects_ambiguous_or_mixed_azure_resource_name_targets(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "inputs": [{"name": "resource_id", "type": "azure_component_resource"}]
    }
    identity = {"subscription_id": "sub"}
    document = {"environment": {"subscription_id": "sub"}}
    ambiguous = SimpleNamespace(
        cloud_provider="azure",
        experiments=[SimpleNamespace(
            id="azure-vm-toolkit-reboot", service="azure_vm",
            variables={"resource_name": "vm-a", "resource_group": "rg"},
        )],
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.list_component_resources",
        lambda *_args: [{"id": "/vm-a", "name": "vm-a"}, {"id": "/vm-b", "name": "vm-a"}],
    )

    result = CampaignPreflightService(catalog).preflight(ambiguous, document, identity)

    assert result.ready is False
    assert "matched multiple" in result.errors[0]
    mixed = SimpleNamespace(
        cloud_provider="azure",
        experiments=[SimpleNamespace(
            id="azure-vm-toolkit-reboot", service="azure_vm",
            variables={"resource_name": "vm-a", "resource_id": "/vm-a", "resource_group": "rg"},
        )],
    )

    result = CampaignPreflightService(catalog).preflight(mixed, document, identity)

    assert result.ready is False
    assert "either resource_id or resource_name" in result.errors[0]


def test_preflight_rejects_equivalent_azure_name_and_id_duplicates(monkeypatch):
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a"
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "inputs": [{"name": "resource_id", "type": "azure_component_resource"}]
    }
    campaign = SimpleNamespace(
        cloud_provider="azure",
        experiments=[
            SimpleNamespace(
                id="azure-vm-toolkit-reboot", service="azure_vm",
                variables={"resource_name": "vm-a", "resource_group": "rg"},
            ),
            SimpleNamespace(
                id="azure-vm-toolkit-reboot", service="azure_vm",
                variables={"resource_id": resource_id, "subscription_id": "sub", "resource_group": "rg"},
            ),
        ],
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.list_component_resources",
        lambda *_args: [{"id": resource_id, "name": "vm-a"}],
    )

    result = CampaignPreflightService(catalog).preflight(
        campaign,
        {"environment": {"subscription_id": "sub"}},
        {"subscription_id": "sub"},
    )

    assert result.ready is False
    assert "duplicates experiment 1 after Azure target resolution" in result.errors[0]


def test_azure_resource_name_normalization_reports_all_resolution_errors(monkeypatch):
    service = CampaignPreflightService(MagicMock())
    unsupported = SimpleNamespace(
        id="unsupported", service="aks", variables={"resource_name": "name"}
    )
    assert "not supported for aks" in service._normalize_azure_resource_names(
        SimpleNamespace(experiments=[unsupported]), {"subscription_id": "sub"}
    )[0]

    service.catalog.get_experiment.return_value = {"inputs": [{"name": "other"}]}
    unsupported_field = SimpleNamespace(
        id="unsupported-field", service="azure_vm", variables={"resource_name": "name"}
    )
    assert "uses a different target field" in service._normalize_azure_resource_names(
        SimpleNamespace(experiments=[unsupported_field]), {"subscription_id": "sub"}
    )[0]

    service.catalog.get_experiment.return_value = {
        "inputs": [{"name": "resource_id", "type": "azure_component_resource"}]
    }
    missing_scope = SimpleNamespace(
        id="missing-scope", service="azure_vm", variables={"resource_name": "name"}
    )
    assert "requires subscription_id and resource_group" in service._normalize_azure_resource_names(
        SimpleNamespace(experiments=[missing_scope]), {}
    )[0]

    lookup_error = SimpleNamespace(
        id="lookup-error", service="azure_vm", variables={"resource_name": "name", "resource_group": "rg"}
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.list_component_resources",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("denied")),
    )
    assert "could not resolve resource_name 'name': denied" in service._normalize_azure_resource_names(
        SimpleNamespace(experiments=[lookup_error]), {"subscription_id": "sub"}
    )[0]

    missing = SimpleNamespace(
        id="missing", service="azure_vm", variables={"resource_name": "name", "resource_group": "rg"}
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.list_component_resources",
        lambda *_args: [],
    )
    assert "was not found" in service._normalize_azure_resource_names(
        SimpleNamespace(experiments=[missing]), {"subscription_id": "sub"}
    )[0]

    named_only = SimpleNamespace(
        id="named-only", service="azure_vm", variables={"resource_name": "vm-a", "resource_group": "rg"}
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.list_component_resources",
        lambda *_args: [{"id": "vm-a", "name": "vm-a"}],
    )
    assert service._normalize_azure_resource_names(
        SimpleNamespace(experiments=[named_only]), {"subscription_id": "sub"}
    ) == []
    assert named_only.variables["resource_id"] == (
        "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a"
    )



def test_every_registered_aws_resource_type_has_a_preflight_resolver():
    supported = {
        "apigateway",
        "apigateway-stage",
        "autoscaling-group",
        "chaos-physical-machine",
        "dynamodb",
        "ebs-volume",
        "ebs-volume-asg-available",
        "ebs-volume-available",
        "ec2",
        "ecs",
            "ecs-service",
            "eks",
            "eks-container",
            "eks-deployment",
        "eks-namespace",
        "eks-node",
        "eks-pod",
        "eks-volume",
            "elasticache",
            "elasticache-cache-cluster",
            "elasticache-replication-group",
        "elb",
        "elb-listener",
        "elb-target",
        "elb-target-group",
        "internet-gateway",
        "lambda",
        "network-acl",
            "network-acl-rule",
            "rds",
            "rds-instance-class",
            "route",
        "route-table",
        "s3",
        "security-group",
        "security-group-rule",
        "sns",
        "sns_subscription",
    }
    catalog = ExperimentCatalog()
    registered = {
        field["resource_type"]
        for service in catalog.list_services()
        if service not in {"aks", "azure_redis", "fis"}
        for experiment in catalog.load_service(service).get("experiments", [])
        for field in experiment.get("inputs", [])
        if field.get("type") == "aws_resource"
    }

    assert registered <= supported


def test_preflight_resolves_catalog_aws_resource_and_blocks_missing_target(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "inputs": [
            {
                "name": "table_name",
                "type": "aws_resource",
                "resource_type": "dynamodb",
                "return": "name",
                "required": True,
            }
        ]
    }
    discovery = MagicMock()
    discovery.list_dynamodb_tables.return_value = [{"name": "table-a"}]
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.AWSDiscovery",
        lambda *_args: discovery,
    )
    experiment = SimpleNamespace(
        id="dynamodb-capacity",
        service="dynamodb",
        variables={"aws_region": "eu-central-1", "table_name": "table-a"},
    )
    campaign = SimpleNamespace(cloud_provider="aws", experiments=[experiment])
    service = CampaignPreflightService(catalog)

    ready = service.preflight(
        campaign, {"environment": {"account_id": "123"}}, {"account_id": "123"}
    )
    experiment.variables["table_name"] = "missing"
    blocked = service.preflight(
        campaign, {"environment": {"account_id": "123"}}, {"account_id": "123"}
    )

    assert ready.ready is True
    assert ready.targets[0]["resolved_inputs"] == ["table_name"]
    assert blocked.ready is False
    assert "table_name 'missing' was not found" in blocked.errors[0]


def test_preflight_validates_optional_resource_when_yaml_supplies_one(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "inputs": [
            {
                "name": "pod",
                "type": "aws_resource",
                "resource_type": "eks-pod",
                "parent": "namespace",
                "return": "name",
                "required": False,
            }
        ]
    }
    discovery = MagicMock()
    discovery.list_eks_pods.return_value = [{"name": "pod-a"}]
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.AWSDiscovery",
        lambda *_args: discovery,
    )
    experiment = SimpleNamespace(
        id="chaos-mesh-pod-kill",
        service="chaos_mesh",
        variables={
            "aws_region": "eu-central-1",
            "eks_cluster": "cluster",
            "namespace": "default",
            "pod": "missing",
        },
    )
    campaign = SimpleNamespace(cloud_provider="aws", experiments=[experiment])

    result = CampaignPreflightService(catalog).preflight(
        campaign, {"environment": {"account_id": "123"}}, {"account_id": "123"}
    )

    assert result.ready is False
    assert "pod 'missing' was not found" in result.errors[0]


def test_preflight_reports_missing_required_resource_and_discovery_failure(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "inputs": [
            {
                "name": "bucket_name",
                "type": "aws_resource",
                "resource_type": "s3",
                "return": "name",
                "required": True,
            }
        ]
    }
    discovery = MagicMock()
    discovery.list_s3_buckets.side_effect = RuntimeError("access denied")
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.AWSDiscovery",
        lambda *_args: discovery,
    )
    experiment = SimpleNamespace(
        id="s3-versioning",
        service="s3",
        variables={"aws_region": "eu-central-1"},
    )
    campaign = SimpleNamespace(cloud_provider="aws", experiments=[experiment])
    service = CampaignPreflightService(catalog)

    missing = service.preflight(
        campaign, {"environment": {"account_id": "123"}}, {"account_id": "123"}
    )
    experiment.variables["bucket_name"] = "bucket-a"
    failed_discovery = service.preflight(
        campaign, {"environment": {"account_id": "123"}}, {"account_id": "123"}
    )

    assert "bucket_name is required" in missing.errors[0]
    assert "Could not resolve bucket_name 'bucket-a': access denied" in failed_discovery.errors[0]


def test_aws_region_uses_arn_then_session_default(monkeypatch):
    assert CampaignPreflightService._aws_region(
        {"target_arn": "arn:aws:sns:eu-west-1:123:topic"}
    ) == "eu-west-1"
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.Session",
        lambda: SimpleNamespace(region_name=None),
    )

    assert CampaignPreflightService._aws_region({}) == "us-east-1"


def test_special_aws_resource_resolvers_cover_asg_and_elb(monkeypatch):
    discovery = MagicMock(region="eu-central-1")
    discovery.list_available_ec2_ebs_volumes.return_value = [{"id": "vol-1"}]
    autoscaling = MagicMock()
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {"Instances": [{"InstanceId": "i-1", "LifecycleState": "InService", "HealthStatus": "Healthy"}]}
        ]
    }
    elbv2 = MagicMock()
    elbv2.describe_target_groups.return_value = {"TargetGroups": [{"TargetGroupName": "tg", "TargetGroupArn": "tg-arn"}]}
    elbv2.describe_load_balancers.return_value = {"LoadBalancers": [{"LoadBalancerArn": "lb-arn"}]}
    elbv2.describe_listeners.return_value = {"Listeners": [{"ListenerArn": "listener-arn"}]}
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.client",
        lambda service, **_kwargs: {"autoscaling": autoscaling, "elbv2": elbv2}[service],
    )

    asg = CampaignPreflightService._aws_resources_for_field(
        discovery,
        {"resource_type": "ebs-volume-asg-available", "parent": "group"},
        {"group": "asg-a"},
    )
    target_groups = CampaignPreflightService._aws_resources_for_field(
        discovery, {"resource_type": "elb-target-group"}, {}
    )
    listeners = CampaignPreflightService._aws_resources_for_field(
        discovery, {"resource_type": "elb-listener"}, {}
    )

    assert asg == [{"id": "vol-1"}]
    assert target_groups[0]["arn"] == "tg-arn"
    assert listeners[0]["arn"] == "listener-arn"


def test_preflight_reports_unknown_resource_type_and_fis_target_failures(monkeypatch):
    discovery = MagicMock(region="eu-central-1")
    with pytest.raises(LookupError, match="No target resolver"):
        CampaignPreflightService._aws_resources_for_field(
            discovery, {"resource_type": "unknown"}, {}
        )

    fis = MagicMock()
    fis.get_experiment_template.side_effect = RuntimeError("not found")
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.client",
        lambda service, **_kwargs: fis,
    )
    experiment = SimpleNamespace(
        id="fis-start-template",
        service="fis",
        variables={"aws_region": "eu-central-1", "experiment_template_id": "missing"},
    )
    result = CampaignPreflightService().preflight(
        SimpleNamespace(cloud_provider="aws", experiments=[experiment]),
        {"environment": {"account_id": "123"}},
        {"account_id": "123"},
    )

    assert result.ready is False
    assert "FIS template 'missing' was not found" in result.errors[0]


def test_preflight_reports_azure_redis_and_aks_resolution_failures(monkeypatch):
    redis = SimpleNamespace(
        id="redis", service="azure_redis", variables={"subscription_id": "sub", "resource_group": "rg", "redis_name": "missing"}
    )
    aks = SimpleNamespace(id="aks", service="aks", variables={"aks_context": "missing"})
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.AzureResourceDiscovery.list_redis_caches",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery.list_contexts",
        lambda *_args: [],
    )

    result = CampaignPreflightService().preflight(
        SimpleNamespace(cloud_provider="azure", experiments=[redis, aks]),
        {"environment": {"subscription_id": "sub"}},
        {"subscription_id": "sub"},
    )

    assert result.ready is False
    assert "Redis cache 'missing' was not found" in result.errors[0]
    assert "AKS context 'missing' was not found" in result.errors[1]


def test_redis_reboot_preflight_requires_and_validates_chaos_identity(monkeypatch):
    experiment = SimpleNamespace(
        id="azure-redis-reboot", service="azure_redis",
        variables={"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache"},
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.AzureResourceDiscovery.list_redis_caches",
        lambda *_args: [{"id": "cache"}],
    )
    missing = CampaignPreflightService._resolve_azure_redis(experiment)
    assert "chaos_identity_id is required" in missing[1]

    experiment.variables["chaos_identity_id"] = "identity"
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.AzureRedisChaosIdentityService.readiness",
        lambda *_args: {"status": "missing_role", "message": "grant Contributor"},
    )
    assert CampaignPreflightService._resolve_azure_redis(experiment)[1] == "grant Contributor"
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.AzureRedisChaosIdentityService.readiness",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("identity denied")),
    )
    assert "Could not verify Azure Redis chaos identity: identity denied" in (
        CampaignPreflightService._resolve_azure_redis(experiment)[1]
    )


def test_classic_preflight_requires_and_validates_chaos_identity(monkeypatch):
    experiment = SimpleNamespace(
        id="azure-vm-shutdown",
        service="azure_vm",
        variables={
            "subscription_id": "sub",
            "resource_group": "rg",
            "resource_id": "/vm",
            "chaos_identity_id": "identity",
        },
    )
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    monkeypatch.setattr(
        "chaosforge.providers.azure.chaos_studio.classic.AzureChaosIdentityService.readiness",
        lambda *_args: {"status": "ready"},
    )

    target, error = CampaignPreflightService()._resolve_target(experiment)

    assert error is None
    assert target["chaos_identity_id"] == "identity"

    experiment.variables.pop("chaos_identity_id")
    assert "chaos_identity_id is required" in (
        CampaignPreflightService._resolve_azure_classic(experiment)[1]
    )

    experiment.variables["chaos_identity_id"] = "identity"
    monkeypatch.setattr(
        "chaosforge.providers.azure.chaos_studio.classic.AzureChaosIdentityService.readiness",
        lambda *_args: {"status": "missing_role", "message": "Grant Contributor"},
    )
    assert CampaignPreflightService._resolve_azure_classic(experiment)[1] == "Grant Contributor"

    monkeypatch.setattr(
        "chaosforge.providers.azure.chaos_studio.classic.AzureChaosIdentityService.readiness",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("identity denied")),
    )
    assert "Could not verify Azure Chaos identity: identity denied" in (
        CampaignPreflightService._resolve_azure_classic(experiment)[1]
    )


def test_preflight_leaves_non_classic_azure_experiments_on_their_own_resolver(monkeypatch):
    service = CampaignPreflightService()
    experiment = SimpleNamespace(id="azure-vm-toolkit-reboot", service="azure_vm", variables={})

    assert service._resolve_target(experiment) == (
        None,
        "resource_id is required for Azure target preflight.",
    )


def test_preflight_routes_aks_to_its_context_resolver(monkeypatch):
    service = CampaignPreflightService()
    experiment = SimpleNamespace(id="aks-pod-kill", service="aks", variables={})
    monkeypatch.setattr(service, "_resolve_aks_context", lambda value: (None, "missing context"))

    assert service._resolve_target(experiment) == (None, "missing context")


def test_preflight_reports_missing_lambda_redis_aks_and_fis_inputs(monkeypatch):
    lambda_result = CampaignPreflightService._resolve_lambda(
        SimpleNamespace(variables={"aws_region": "eu-central-1"})
    )
    redis_result = CampaignPreflightService._resolve_azure_redis(
        SimpleNamespace(variables={"subscription_id": "sub"})
    )
    aks_result = CampaignPreflightService._resolve_aks_context(
        SimpleNamespace(variables={})
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.client", MagicMock()
    )
    fis_result = CampaignPreflightService._resolve_fis(
        SimpleNamespace(id="fis-create-experiment", variables={"aws_region": "eu-central-1"})
    )

    assert "lambda_name and aws_region" in lambda_result[1]
    assert "subscription_id, resource_group, and redis_name" in redis_result[1]
    assert "aks_context is required" in aks_result[1]
    assert "role_arn and target_arn" in fis_result[1]


def test_every_standard_aws_resource_mapping_invokes_its_discovery_method():
    discovery = MagicMock(region="eu-central-1")
    resource_types = {
        "apigateway": "list_apigateway_apis",
        "apigateway-stage": "list_apigateway_stages",
        "autoscaling-group": "list_auto_scaling_groups",
        "chaos-physical-machine": "list_chaos_physical_machines",
        "dynamodb": "list_dynamodb_tables",
        "ebs-volume": "list_ec2_ebs_volumes",
        "ebs-volume-available": "list_available_ec2_ebs_volumes",
        "ec2": "list_ec2_instances",
        "ecs": "list_ecs_clusters",
        "ecs-service": "list_ecs_services",
        "eks": "list_eks_clusters",
        "eks-container": "list_eks_containers",
        "eks-deployment": "list_eks_deployments",
        "eks-namespace": "list_eks_namespaces",
        "eks-node": "list_eks_nodes",
        "eks-pod": "list_eks_pods",
        "eks-volume": "list_eks_volumes",
        "elb": "list_elb_load_balancers",
        "elb-target": "list_elb_targets",
        "internet-gateway": "list_internet_gateways",
        "lambda": "list_lambda_functions",
        "network-acl": "list_network_acls",
        "network-acl-rule": "list_network_acl_rules",
        "rds": "list_rds_instances",
        "route": "list_routes",
        "route-table": "list_route_tables",
        "s3": "list_s3_buckets",
        "security-group": "list_security_groups",
        "security-group-rule": "list_security_group_rules",
        "sns": "list_sns_topics",
        "sns_subscription": "list_sns_subscriptions",
    }
    for method in resource_types.values():
        getattr(discovery, method).return_value = [{"id": "resource"}]
    variables = {"parent": "parent", "eks_cluster": "cluster", "namespace": "namespace"}

    for resource_type, method in resource_types.items():
        CampaignPreflightService._aws_resources_for_field(
            discovery, {"resource_type": resource_type, "parent": "parent"}, variables
        )
        getattr(discovery, method).assert_called()


def test_special_resource_empty_and_elasticache_paths(monkeypatch):
    discovery = MagicMock(region="eu-central-1")
    discovery.list_elasticache_serverless.return_value = [{"name": "serverless"}]
    autoscaling = MagicMock()
    autoscaling.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [{"Instances": []}]}
    elasticache = MagicMock()
    elasticache.describe_cache_clusters.return_value = {"CacheClusters": [{"CacheClusterId": "cluster"}]}
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.client",
        lambda service, **_kwargs: {"autoscaling": autoscaling, "elasticache": elasticache}[service],
    )

    no_volume = CampaignPreflightService._aws_resources_for_field(
        discovery, {"resource_type": "ebs-volume-asg-available", "parent": "group"}, {"group": "asg"}
    )
    caches = CampaignPreflightService._aws_resources_for_field(
        discovery, {"resource_type": "elasticache"}, {}
    )

    assert no_volume == []
    assert {cache["name"] for cache in caches} == {"serverless", "cluster"}


def test_fis_stop_and_create_preflight_paths(monkeypatch):
    fis = MagicMock()
    iam = MagicMock()
    iam.get_role.return_value = {"Role": {"RoleName": "chaos"}}
    discovery = MagicMock(region="eu-central-1")
    discovery.list_dynamodb_tables.return_value = [{"arn": "table-arn"}]
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.client",
        lambda service, **_kwargs: {"fis": fis, "iam": iam}[service],
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.AWSDiscovery",
        lambda *_args: discovery,
    )

    stopped = CampaignPreflightService._resolve_fis(
        SimpleNamespace(id="fis-stop-experiment", variables={"aws_region": "eu-central-1", "experiment_id": "exp"})
    )
    created = CampaignPreflightService._resolve_fis(
        SimpleNamespace(
            id="fis-create-experiment",
            variables={
                "aws_region": "eu-central-1",
                "role_arn": "arn:aws:iam::123:role/chaos",
                "target_arn": "table-arn",
                "service_id": "dynamodb",
            },
        )
    )

    assert stopped[1] is None
    assert created[1] is None
    fis.get_experiment.assert_called_once_with(id="exp")
    iam.get_role.assert_called_once_with(RoleName="chaos")


def test_fis_role_target_and_azure_discovery_exceptions(monkeypatch):
    iam = MagicMock()
    iam.get_role.side_effect = RuntimeError("denied")
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.client",
        lambda *_args, **_kwargs: iam,
    )
    role_failure = CampaignPreflightService._resolve_fis(
        SimpleNamespace(
            id="fis-create-experiment",
            variables={"aws_region": "eu-central-1", "role_arn": "arn:aws:iam::123:role/chaos", "target_arn": "target"},
        )
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.discovery.AzureResourceDiscovery.list_redis_caches",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("redis denied")),
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery.list_contexts",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("kube denied")),
    )
    redis_failure = CampaignPreflightService._resolve_azure_redis(
        SimpleNamespace(variables={"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache"})
    )
    aks_failure = CampaignPreflightService._resolve_aks_context(
        SimpleNamespace(variables={"aks_context": "cluster"})
    )

    assert "FIS role" in role_failure[1]
    assert "Could not resolve Redis cache" in redis_failure[1]
    assert "Could not resolve AKS context" in aks_failure[1]


def test_preflight_handles_unregistered_experiments_and_optional_empty_resources(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = None
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.AWSDiscovery", MagicMock()
    )
    unregistered = CampaignPreflightService(catalog)._resolve_aws_resources(
        SimpleNamespace(id="missing", service="s3", variables={"aws_region": "eu-central-1"})
    )
    catalog.get_experiment.return_value = {
        "inputs": [
            {"name": "optional_pod", "type": "aws_resource", "resource_type": "eks-pod", "required": False},
            {"name": "note", "type": "text"},
        ]
    }
    optional = CampaignPreflightService(catalog)._resolve_aws_resources(
        SimpleNamespace(id="optional", service="chaos_mesh", variables={"aws_region": "eu-central-1"})
    )

    assert "not registered" in unregistered[1]
    assert optional[0]["resolved_inputs"] == []


def test_fis_stop_and_create_target_failures(monkeypatch):
    fis = MagicMock()
    fis.get_experiment.side_effect = RuntimeError("missing experiment")
    iam = MagicMock()
    iam.get_role.return_value = {"Role": {"RoleName": "chaos"}}
    discovery = MagicMock(region="eu-central-1")
    discovery.list_dynamodb_tables.return_value = []
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.boto3.client",
        lambda service, **_kwargs: {"fis": fis, "iam": iam}[service],
    )
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_preflight.AWSDiscovery",
        lambda *_args: discovery,
    )

    stop_failure = CampaignPreflightService._resolve_fis(
        SimpleNamespace(id="fis-stop-experiment", variables={"aws_region": "eu-central-1", "experiment_id": "missing"})
    )
    target_failure = CampaignPreflightService._resolve_fis(
        SimpleNamespace(
            id="fis-create-experiment",
            variables={
                "aws_region": "eu-central-1",
                "role_arn": "arn:aws:iam::123:role/chaos",
                "target_arn": "missing-target",
                "service_id": "dynamodb",
            },
        )
    )

    assert "FIS experiment 'missing' was not found" in stop_failure[1]
    assert "target_arn 'missing-target' was not found" in target_failure[1]
