from types import SimpleNamespace

import pytest

from chaosforge.lifecycle.checks.aws_adapters import (
    DynamoDBTableAdapter,
    EC2AutoScalingGroupAdapter,
    EC2ResourceAdapter,
    ElastiCacheReplicationGroupAdapter,
    ElastiCacheServerlessAdapter,
    RDSInstanceAdapter,
    SNSSubscriptionAdapter,
    SNSTopicAdapter,
    VPCResourceAdapter,
)
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.kubernetes_chaos import (
    SharedChaosMeshValidationCheck,
)
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.lifecycle.checks.validations import (
    EKSContainerRestartCheck,
    EKSNodeCheck,
)


@pytest.mark.parametrize("fis_experiment_id", ["stop-instances", "reboot-instances"])
def test_resolver_returns_ec2_check_for_fis_recovering_instances(
    fis_experiment_id,
):
    experiment = SimpleNamespace(
        id="fis-create-experiment",
        variables={
            "service_id": "ec2",
            "experiment_id": fis_experiment_id,
        },
    )

    check = CheckResolver().resolve(experiment)

    assert isinstance(check, CommonResourceCheck)
    assert isinstance(check.adapter, EC2ResourceAdapter)
    assert check.name == f"fis-{fis_experiment_id}-lifecycle"
    assert check.predicates["instance_state_restored"](
        {"state": {"instance_states": {"i-123": "running"}}},
        {"state": {"instance_states": {"i-123": "running"}}},
    ) is True
    assert check.predicates["instance_state_restored"](
        {"state": {"instance_states": {"i-123": "stopped"}}},
        {"state": {"instance_states": {"i-123": "running"}}},
    ) is False
    assert all(
        predicate(
            {"state": {"instance_states": {"i-123": "running"}}}
        )
        for predicate in check.preconditions.values()
    )
    assert not all(
        predicate(
            {"state": {"instance_states": {"i-123": "stopped"}}}
        )
        for predicate in check.preconditions.values()
    )


def test_resolver_returns_ec2_check_for_fis_terminate_instances():
    experiment = SimpleNamespace(
        id="fis-create-experiment",
        variables={
            "service_id": "ec2",
            "experiment_id": "terminate-instances",
        },
    )

    check = CheckResolver().resolve(experiment)

    assert isinstance(check.adapter, EC2ResourceAdapter)
    assert check.recovery_supported is False
    assert check.validation_timeout_seconds == 300
    assert check.predicates["instances_terminated"](
        {"state": {"instance_states": {"i-123": "terminated"}}},
        {},
    ) is True


@pytest.mark.parametrize(
    "experiment_id",
    [
        "lambda-memory",
        "lambda-timeout",
        "lambda-concurrency",
        "lambda-provisioned-concurrency",
        "lambda-retry",
        "lambda-storm-injector",
    ],
)
def test_resolver_returns_common_lambda_check(experiment_id):
    resolver = CheckResolver()

    experiment = SimpleNamespace(id=experiment_id)

    check = resolver.resolve(experiment)

    assert isinstance(check, CommonResourceCheck)
    assert check.name == f"{experiment_id}-lifecycle"
    assert check.adapter.name == "lambda-resource-adapter"


@pytest.mark.parametrize(
    "experiment_id",
    [
        "lambda-memory",
        "lambda-timeout",
        "lambda-concurrency",
        "lambda-provisioned-concurrency",
        "lambda-retry",
        "lambda-storm-injector",
    ],
)
def test_lambda_check_has_expected_predicates(experiment_id):
    resolver = CheckResolver()

    experiment = SimpleNamespace(id=experiment_id)

    check = resolver.resolve(experiment)

    assert check is not None
    assert "exists" in check.predicates
    assert "resource_exists" in check.predicates


def test_lambda_memory_check_validates_memory():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="lambda-memory")
    )

    current = {
        "exists": True,
        "configuration": {
            "memory_size": 512,
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "memory_size": 512,
        },
    }

    assert check.predicates["memory_size"](current, baseline) is True


def test_lambda_timeout_check_detects_changed_timeout():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="lambda-timeout")
    )

    current = {
        "exists": True,
        "configuration": {
            "timeout": 60,
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "timeout": 30,
        },
    }

    assert check.predicates["timeout"](current, baseline) is False


def test_lambda_concurrency_check_validates_reserved_concurrency():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="lambda-concurrency")
    )

    current = {
        "exists": True,
        "concurrency": {
            "reserved_concurrency": 25,
        },
    }

    baseline = {
        "exists": True,
        "concurrency": {
            "reserved_concurrency": 25,
        },
    }

    assert check.predicates["reserved_concurrency"](
        current,
        baseline,
    ) is True


def test_lambda_retry_check_detects_changed_retry_attempts():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="lambda-retry")
    )

    current = {
        "exists": True,
        "async_invoke": {
            "maximum_retry_attempts": 0,
        },
    }

    baseline = {
        "exists": True,
        "async_invoke": {
            "maximum_retry_attempts": 2,
        },
    }

    assert check.predicates["maximum_retry_attempts"](
        current,
        baseline,
    ) is False


def test_lambda_storm_check_validates_lambda_state():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="lambda-storm-injector")
    )

    current = {
        "exists": True,
        "state": {
            "state": "Active",
        },
    }

    baseline = {
        "exists": True,
        "state": {
            "state": "Active",
        },
    }

    assert check.predicates["lambda_state"](
        current,
        baseline,
    ) is True


def test_unsupported_experiment_returns_none():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="some-unsupported-experiment"
    )

    assert resolver.resolve(experiment) is None

def test_sns_experiments_resolve_to_expected_adapters():
    resolver = CheckResolver()

    expected_adapters = {
        "sns-publish-message": SNSTopicAdapter,
        "sns-topic-policy": SNSTopicAdapter,
        "sns-subscription-filter": SNSSubscriptionAdapter,
        "sns-delivery-policy": SNSTopicAdapter,
    }

    for experiment_id, adapter_type in expected_adapters.items():
        experiment = SimpleNamespace(id=experiment_id)

        check = resolver.resolve(experiment)

        assert isinstance(check, CommonResourceCheck)
        assert isinstance(check.adapter, adapter_type)
        assert check.name == f"{experiment_id}-lifecycle"


def test_sns_publish_message_has_resource_exists_predicate():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="sns-publish-message")
    )

    assert "resource_exists" in check.predicates

    current = {"exists": True}
    baseline = {"exists": True}

    assert check.predicates["resource_exists"](
        current,
        baseline,
    ) is True


def test_sns_topic_policy_detects_policy_change():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="sns-topic-policy")
    )

    current = {
        "exists": True,
        "configuration": {
            "policy": "changed-policy",
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "policy": "original-policy",
        },
    }

    assert check.predicates["policy_restored"](
        current,
        baseline,
    ) is False


def test_sns_subscription_filter_validates_filter_policy():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="sns-subscription-filter")
    )

    current = {
        "exists": True,
        "configuration": {
            "filter_policy": '{"event":["created"]}',
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "filter_policy": '{"event":["created"]}',
        },
    }

    assert check.predicates["filter_policy_restored"](
        current,
        baseline,
    ) is True


def test_sns_delivery_policy_detects_changed_policy():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="sns-delivery-policy")
    )

    current = {
        "exists": True,
        "configuration": {
            "delivery_policy": '{"healthyRetryPolicy":{}}',
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "delivery_policy": '{"healthyRetryPolicy":{"numRetries":3}}',
        },
    }

    assert check.predicates["delivery_policy_restored"](
        current,
        baseline,
    ) is False


def test_vpc_experiments_resolve_to_vpc_adapter():
    resolver = CheckResolver()

    experiment_ids = [
        "vpc-security-group",
        "vpc-route-table",
        "vpc-network-acl",
        "vpc-internet-gateway",
    ]

    for experiment_id in experiment_ids:
        experiment = SimpleNamespace(id=experiment_id)

        check = resolver.resolve(experiment)

        assert isinstance(check, CommonResourceCheck)
        assert isinstance(check.adapter, VPCResourceAdapter)
        assert check.name == f"{experiment_id}-lifecycle"


def test_vpc_security_group_predicates_validate_rules():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="vpc-security-group")
    )

    current = {
        "exists": True,
        "configuration": {
            "ingress": [{"protocol": "tcp", "port": 443}],
            "egress": [{"protocol": "-1"}],
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "ingress": [{"protocol": "tcp", "port": 443}],
            "egress": [{"protocol": "-1"}],
        },
    }

    assert check.predicates["resource_exists"](
        current,
        baseline,
    ) is True

    assert check.predicates["ingress_rules_restored"](
        current,
        baseline,
    ) is True

    assert check.predicates["egress_rules_restored"](
        current,
        baseline,
    ) is True


def test_s3_public_access_requires_an_enabled_block_control():
    check = CheckResolver().resolve(SimpleNamespace(id="s3-public-access"))
    eligibility = check.preconditions[
        "at least one Public Access Block control must be enabled"
    ]

    assert eligibility(
        {"configuration": {"public_access_block": {"BlockPublicAcls": True}}}
    ) is True
    assert eligibility(
        {
            "configuration": {
                "public_access_block": {
                    "BlockPublicAcls": False,
                    "IgnorePublicAcls": False,
                    "BlockPublicPolicy": False,
                    "RestrictPublicBuckets": False,
                }
            }
        }
    ) is False
    assert eligibility({"configuration": {"public_access_block": None}}) is False


def test_vpc_route_table_detects_changed_routes():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="vpc-route-table")
    )

    current = {
        "exists": True,
        "configuration": {
            "routes": [{"destination": "10.0.0.0/16"}],
            "associations": ["subnet-1"],
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "routes": [{"destination": "0.0.0.0/0"}],
            "associations": ["subnet-1"],
        },
    }

    assert check.predicates["routes_restored"](
        current,
        baseline,
    ) is False

    assert check.predicates["associations_restored"](
        current,
        baseline,
    ) is True


def test_vpc_network_acl_validates_entries_and_associations():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="vpc-network-acl")
    )

    current = {
        "exists": True,
        "configuration": {
            "entries": [{"rule_number": 100}],
            "associations": ["subnet-1"],
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "entries": [{"rule_number": 100}],
            "associations": ["subnet-1"],
        },
    }

    assert check.predicates["entries_restored"](
        current,
        baseline,
    ) is True

    assert check.predicates["associations_restored"](
        current,
        baseline,
    ) is True


def test_vpc_internet_gateway_detects_changed_attachments():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="vpc-internet-gateway")
    )

    current = {
        "exists": True,
        "configuration": {
            "attachments": [],
        },
    }

    baseline = {
        "exists": True,
        "configuration": {
            "attachments": [
                {"vpc_id": "vpc-123"},
            ],
        },
    }

    assert check.predicates["attachments_restored"](
        current,
        baseline,
    ) is False


def test_eks_resolver_requires_discovery():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="eks-replica-reduction"
    )

    with pytest.raises(
        ValueError,
        match="AWS discovery is required",
    ):
        resolver.resolve(experiment)

def test_chaos_mesh_pod_failure_resolves_to_eks_pod_check():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="chaos-mesh-pod-failure"
    )

    discovery = SimpleNamespace()

    check = resolver.resolve(
        experiment,
        discovery=discovery,
    )

    assert isinstance(check, SharedChaosMeshValidationCheck)
    assert check.name == "shared-kubernetes-chaos-validation"


def test_chaos_mesh_pod_failure_resolver_requires_discovery():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="chaos-mesh-pod-failure"
    )

    with pytest.raises(
        ValueError,
        match="AWS discovery is required",
    ):
        resolver.resolve(experiment)


def test_every_aks_catalog_experiment_resolves_without_aws_discovery():
    from chaosforge.catalog import ExperimentCatalog

    metadata = ExperimentCatalog().load_service("aks")

    for item in metadata["experiments"]:
        experiment = SimpleNamespace(
            id=item["id"],
            service="aks",
            variables={"aks_context": "cluster", "namespace": "default"},
        )

        check = CheckResolver().resolve(experiment, discovery=None)

        if item["id"] in {
            "aks-node-drain",
            "aks-node-taint",
            "aks-node-cpu-stress",
            "aks-node-memory-pressure",
            "aks-node-notready",
            "aks-node-zone-failure",
        }:
            assert check is None
        else:
            assert isinstance(check, SharedChaosMeshValidationCheck), item["id"]


def test_aks_node_experiments_use_provider_owned_lifecycle_checks():
    resolver = CheckResolver()

    for experiment_id in {
        "aks-node-drain",
        "aks-node-taint",
        "aks-node-cpu-stress",
        "aks-node-memory-pressure",
        "aks-node-notready",
        "aks-node-zone-failure",
    }:
        experiment = SimpleNamespace(
            id=experiment_id,
            service="aks",
            variables={"aks_context": "cluster", "target_node": "node-a"},
        )

        assert resolver.resolve(experiment) is None


@pytest.mark.parametrize("service", [None, "", "legacy-azure-service"])
def test_native_aks_ids_do_not_depend_on_stored_service_identity(service):
    experiment = SimpleNamespace(
        id="aks-pod-kill",
        service=service,
        variables={"aks_context": "cluster", "namespace": "default"},
    )

    check = CheckResolver().resolve(experiment, discovery=None)

    assert isinstance(check, SharedChaosMeshValidationCheck)


def test_eks_pod_check_uses_shared_post_validation(monkeypatch):
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="chaos-mesh-pod-failure"
    )

    discovery = SimpleNamespace()

    check = resolver.resolve(
        experiment,
        discovery=discovery,
    )

    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.safety.build_post_experiment_checks",
        lambda *args, **kwargs: {"Pod Recovery": lambda: (True, "ready")},
    )

    result = check.validate(
        {
            "eks_cluster": "test-cluster",
            "namespace": "default",
            "pod": "demo-pod",
        },
        {},
    )

    assert result["passed"] is True
    assert result["checks"]["Pod Recovery"]["passed"] is True
    assert result["validation_experiment_id"] == "aks-pod-failure"


def test_dynamodb_experiments_resolve_to_dynamodb_adapter():
    resolver = CheckResolver()

    experiment_ids = [
        "dynamodb-capacity",
        "dynamodb-pitr",
        "dynamodb-stream",
        "dynamodb-ttl",
    ]

    for experiment_id in experiment_ids:
        experiment = SimpleNamespace(id=experiment_id)

        check = resolver.resolve(experiment)

        assert isinstance(check, CommonResourceCheck)
        assert isinstance(
            check.adapter,
            DynamoDBTableAdapter,
        )
        assert check.name == f"{experiment_id}-lifecycle"


def test_rds_experiments_resolve_to_rds_adapter():
    resolver = CheckResolver()

    experiment_ids = [
        "rds-instance-class",
        "rds-backup-retention",
        "rds-auto-minor-version-upgrade",
        "rds-deletion-protection",
        "rds-storage-autoscaling",
        "rds-iops",
    ]

    for experiment_id in experiment_ids:
        experiment = SimpleNamespace(id=experiment_id)

        check = resolver.resolve(experiment)

        assert isinstance(check, CommonResourceCheck)
        assert isinstance(
            check.adapter,
            RDSInstanceAdapter,
        )
        assert check.name == f"{experiment_id}-lifecycle"


def test_elasticache_experiments_resolve_to_matching_target_adapter():
    resolver = CheckResolver()

    adapters = {
        "elasticache-security-group": ElastiCacheReplicationGroupAdapter,
        "elasticache-snapshot-retention": ElastiCacheReplicationGroupAdapter,
        "elasticache-usage-limit": ElastiCacheServerlessAdapter,
        "elasticache-daily-snapshot": ElastiCacheReplicationGroupAdapter,
    }

    for experiment_id, adapter in adapters.items():
        experiment = SimpleNamespace(id=experiment_id)

        check = resolver.resolve(experiment)

        assert isinstance(check, CommonResourceCheck)
        assert isinstance(
            check.adapter,
            adapter,
        )
        assert check.name == f"{experiment_id}-lifecycle"

def test_ec2_asg_experiments_resolve_to_autoscaling_group_adapter():
    resolver = CheckResolver()

    experiment_ids = [
        "ec2-ebs-volume-detach-asg",
        "ec2-ebs-volume-attach-asg",
    ]

    for experiment_id in experiment_ids:
        experiment = SimpleNamespace(id=experiment_id)

        check = resolver.resolve(experiment)

        assert isinstance(check, CommonResourceCheck)
        assert isinstance(
            check.adapter,
            EC2AutoScalingGroupAdapter,
        )
        assert check.name == f"{experiment_id}-lifecycle"

def test_eks_node_experiments_resolve_to_node_check():
    resolver = CheckResolver()

    experiment_ids = [
        "eks-node-cordon",
        "eks-node-drain",
    ]

    discovery = SimpleNamespace()

    for experiment_id in experiment_ids:
        experiment = SimpleNamespace(id=experiment_id)

        check = resolver.resolve(
            experiment,
            discovery=discovery,
        )

        assert isinstance(check, EKSNodeCheck)
        assert check.name == "eks-node"
        assert check.common_check.adapter.name == "eks-node-adapter"


def test_eks_node_experiments_require_discovery():
    resolver = CheckResolver()

    experiment_ids = [
        "eks-node-cordon",
        "eks-node-drain",
    ]

    for experiment_id in experiment_ids:
        experiment = SimpleNamespace(id=experiment_id)

        with pytest.raises(
            ValueError,
            match="AWS discovery is required",
        ):
            resolver.resolve(experiment)

def test_eks_node_check_validates_schedulable_state_recovery():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="eks-node-cordon",
    )

    discovery = SimpleNamespace()

    check = resolver.resolve(
        experiment,
        discovery=discovery,
    )

    baseline = {
        "exists": True,
        "cluster": "test-cluster",
        "node": "test-node",
        "unschedulable": False,
        "ready": "True",
        "conditions": {
            "Ready": "True",
        },
    }

    check.common_check.adapter.capture = lambda target: {
        "exists": True,
        "cluster": "test-cluster",
        "node": "test-node",
        "unschedulable": False,
        "ready": "True",
        "conditions": {
            "Ready": "True",
        },
    }

    result = check.validate(
        {
            "eks_cluster": "test-cluster",
            "node_name": "test-node",
        },
        baseline,
    )

    assert result["passed"] is True
    assert result["checks"]["resource_exists"] is True
    assert result["checks"]["unschedulable"] is True
    assert result["checks"]["ready"] is True

def test_eks_node_check_detects_unrecovered_cordon():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="eks-node-cordon",
    )

    discovery = SimpleNamespace()

    check = resolver.resolve(
        experiment,
        discovery=discovery,
    )

    baseline = {
        "exists": True,
        "cluster": "test-cluster",
        "node": "test-node",
        "unschedulable": False,
        "ready": "True",
        "conditions": {
            "Ready": "True",
        },
    }

    check.common_check.adapter.capture = lambda target: {
        "exists": True,
        "cluster": "test-cluster",
        "node": "test-node",
        "unschedulable": True,
        "ready": "True",
        "conditions": {
            "Ready": "True",
        },
    }

    result = check.validate(
        {
            "eks_cluster": "test-cluster",
            "node_name": "test-node",
        },
        baseline,
    )

    assert result["passed"] is False
    assert result["checks"]["resource_exists"] is True
    assert result["checks"]["unschedulable"] is False
    assert result["checks"]["ready"] is True

def test_eks_container_restart_resolves_to_container_restart_check():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="eks-container-restart",
    )

    discovery = SimpleNamespace()

    check = resolver.resolve(
        experiment,
        discovery=discovery,
    )

    assert isinstance(
        check,
        EKSContainerRestartCheck,
    )
    assert check.name == "eks-container-restart"
    assert (
        check.common_check.adapter.name
        == "eks-container-restart-adapter"
    )


def test_eks_container_restart_requires_discovery():
    resolver = CheckResolver()

    experiment = SimpleNamespace(
        id="eks-container-restart",
    )

    with pytest.raises(
        ValueError,
        match="AWS discovery is required",
    ):
        resolver.resolve(experiment)

def test_sns_delete_subscription_uses_subscription_adapter():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="sns-delete-subscription")
    )

    assert isinstance(check, CommonResourceCheck)
    assert isinstance(check.adapter, SNSSubscriptionAdapter)
    assert check.name == "sns-delete-subscription-lifecycle"
    assert check.recovery_supported is False


def test_sns_delete_subscription_detects_deleted_subscription():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="sns-delete-subscription")
    )

    current = {
        "exists": False,
        "identity": {
            "subscription_arn": "arn:aws:sns:eu-central-1:123:subscription"
        },
    }

    baseline = {
        "exists": True,
        "identity": {
            "subscription_arn": "arn:aws:sns:eu-central-1:123:subscription"
        },
    }

    assert (
        check.predicates["subscription_deleted"](
            current,
            baseline,
        )
        is True
    )


def test_sns_delete_subscription_fails_when_subscription_still_exists():
    resolver = CheckResolver()

    check = resolver.resolve(
        SimpleNamespace(id="sns-delete-subscription")
    )

    current = {
        "exists": True,
    }

    baseline = {
        "exists": True,
    }

    assert (
        check.predicates["subscription_deleted"](
            current,
            baseline,
        )
        is False
    )
