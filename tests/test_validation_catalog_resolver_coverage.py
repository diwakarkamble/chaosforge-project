import json
from types import SimpleNamespace

import pytest

from chaosforge.application.validation.yaml import YAMLValidationError, YAMLValidator
from chaosforge.catalog.loader import ExperimentCatalog
from chaosforge.common.paths import ChaosForgePaths
from chaosforge.lifecycle.checks.aws_adapters import (
    APIGatewayStageAdapter,
    EC2ResourceAdapter,
    ELBListenerAdapter,
    ELBLoadBalancerAdapter,
    ELBTargetGroupAdapter,
    S3BucketAdapter,
)
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.lifecycle.checks.validations import EKSDeploymentCheck


def _experiment(experiment_id, service="aws", variables=None):
    return SimpleNamespace(
        id=experiment_id,
        service=service,
        variables={} if variables is None else variables,
    )


def _valid_campaign(provider="aws"):
    identity = "account_id" if provider == "aws" else "subscription_id"
    return {
        "cloud": {"provider": provider},
        "environment": {identity: "identity"},
        "experiments": [
            {"service": "lambda", "experiment": "lambda-memory", "variables": {}}
        ],
    }


def test_yaml_validator_reports_root_campaign_cloud_and_experiment_type_errors():
    validator = YAMLValidator()

    assert str(YAMLValidationError("campaign.name", "invalid")) == "campaign.name: invalid"
    assert validator.validate("not-a-mapping")["errors"] == [
        "Root YAML document must be a mapping/object."
    ]

    result = validator.validate(
        {
            "campaign": [],
            "cloud": [],
            "experiments": [None, {"service": 1, "experiment": 2}],
        }
    )

    assert result["errors"] == [
        "campaign: must be a mapping/object.",
        "cloud: must be a mapping/object.",
        "experiments[0]: must be a mapping/object.",
        "experiments[1].service: must be a string.",
        "experiments[1].experiment: must be a string.",
        "experiments[1].variables: is required.",
    ]


@pytest.mark.parametrize(
    ("cloud", "expected_error"),
    [
        ({}, "environment.subscription_id: is required for an executable  campaign."),
        ({"provider": 1}, "cloud.provider: must be a string."),
    ],
)
def test_yaml_validator_handles_missing_and_invalid_cloud_providers(cloud, expected_error):
    data = _valid_campaign()
    data["cloud"] = cloud

    errors = YAMLValidator().validate(data)["errors"]

    assert errors == [expected_error]


@pytest.mark.parametrize(
    ("updates", "expected_error"),
    [
        ({"template": "yes"}, "template: must be a boolean."),
        ({"environment": None}, "environment: is required for an executable campaign."),
        ({"environment": []}, "environment: must be a mapping/object."),
        ({"environment": {"account_id": " "}}, "environment.account_id: is required for an executable aws campaign."),
    ],
)
def test_yaml_validator_validates_executable_environment(updates, expected_error):
    data = _valid_campaign()
    data.update(updates)

    assert expected_error in YAMLValidator().validate(data)["errors"]


def test_yaml_validator_accepts_templates_and_azure_subscription_identity():
    template = _valid_campaign()
    template["template"] = True
    template["environment"] = {}

    azure = _valid_campaign("azure")
    azure["cloud"]["provider"] = "AZURE"

    assert YAMLValidator().validate(template)["valid"] is True
    assert YAMLValidator().validate(azure)["valid"] is True


def test_yaml_validator_rejects_empty_service_and_experiment_names():
    data = _valid_campaign()
    data["experiments"][0]["service"] = " "
    data["experiments"][0]["experiment"] = ""

    assert YAMLValidator().validate(data)["errors"] == [
        "experiments[0].service: must not be empty.",
        "experiments[0].experiment: must not be empty.",
    ]


def test_catalog_resolves_all_special_paths_and_missing_services(tmp_path):
    paths = ChaosForgePaths(tmp_path)
    catalog = ExperimentCatalog(paths)
    fixtures = {
        "fis": tmp_path / "chaosforge/providers/aws/fis/metadata.json",
        "chaos_mesh": tmp_path / "chaosforge/engines/chaos_mesh/experiments/metadata.json",
        "aks": tmp_path / "chaosforge/providers/azure/components/aks/experiments/metadata.json",
        "azure_redis": tmp_path / "chaosforge/providers/azure/components/azure_redis/experiments/metadata.json",
    }
    for service, path in fixtures.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"experiments": [{"id": service}]}), encoding="utf-8")

    assert catalog.list_services() == ["aks", "azure_redis", "chaos_mesh", "fis"]
    assert catalog.load_service("missing") is None
    assert catalog.get_experiment("missing", "anything") is None
    assert catalog.get_experiment("fis", "fis") == {"id": "fis"}
    assert catalog.definition_path("fis", "experiment.json") == tmp_path / "chaosforge/catalog/missing-definition.json"
    assert catalog.definition_path("chaos_mesh", "experiment.json") == fixtures["chaos_mesh"].parent / "definitions/experiment.json"
    assert catalog.definition_path("aks", "experiment.json") == fixtures["aks"].parent / "toolkit/experiment.json"
    assert catalog.definition_path("aks", "experiment.json").name == "experiment.json"


@pytest.mark.parametrize(
    ("experiment_id", "recovery_supported"),
    [
        ("azure-redis-reboot", True),
        ("azure-redis-flush", False),
        ("azure-redis-access-disruption", True),
    ],
)
def test_resolver_configures_azure_redis_checks(experiment_id, recovery_supported):
    check = CheckResolver().resolve(_experiment(experiment_id, "azure_redis"))

    assert isinstance(check, CommonResourceCheck)
    assert check.name == f"{experiment_id}-lifecycle"
    assert check.recovery_supported is recovery_supported
    assert check.predicates["resource_exists"]({"exists": True}, {}) is True


def test_resolver_returns_eks_deployment_and_ec2_resource_checks():
    discovery = SimpleNamespace()
    eks_check = CheckResolver().resolve(_experiment("eks-replica-reduction"), discovery)
    incremental_check = CheckResolver().resolve(_experiment("ec2-incremental-instance-stop"))
    attachment_check = CheckResolver().resolve(_experiment("ec2-ebs-volume-detach"))

    assert isinstance(eks_check, EKSDeploymentCheck)
    assert isinstance(incremental_check.adapter, EC2ResourceAdapter)
    assert incremental_check.predicates["instances_stopped"](
        {"state": {"instance_states": {"i-1": "stopped"}}}, {}
    ) is True
    assert isinstance(attachment_check.adapter, EC2ResourceAdapter)
    assert attachment_check.predicates["attachments_restored"](
        {"configuration": {"block_device_mappings": ["volume"]}},
        {"configuration": {"block_device_mappings": ["volume"]}},
    ) is True


@pytest.mark.parametrize(
    ("experiment_id", "adapter_type"),
    [
        ("elb-cross-zone", ELBTargetGroupAdapter),
        ("elb-target-group", ELBTargetGroupAdapter),
        ("elb-listener", ELBListenerAdapter),
        ("elb-load-balancer", ELBLoadBalancerAdapter),
        ("ecs-cpu-modification", "ecs-service-adapter"),
        ("api-gateway-stage-cache", APIGatewayStageAdapter),
        ("s3-versioning", S3BucketAdapter),
        ("apigateway-stage-cache", APIGatewayStageAdapter),
    ],
)
def test_resolver_selects_adapter_for_registered_service_checks(experiment_id, adapter_type):
    check = CheckResolver().resolve(_experiment(experiment_id))

    assert isinstance(check, CommonResourceCheck)
    if isinstance(adapter_type, str):
        assert check.adapter.name == adapter_type
    else:
        assert isinstance(check.adapter, adapter_type)


def test_resolver_enriches_vpc_targets_before_capture(monkeypatch):
    captured = []

    def capture(self, target):
        captured.append(target)
        return target

    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.resolver.VPCResourceAdapter.capture", capture
    )
    check = CheckResolver().resolve(_experiment("vpc-route-table"))

    assert check.adapter.capture({"id": "rtb-1"}) == {
        "id": "rtb-1",
        "resource_type": "route-table",
    }
    assert captured == [{"id": "rtb-1", "resource_type": "route-table"}]
