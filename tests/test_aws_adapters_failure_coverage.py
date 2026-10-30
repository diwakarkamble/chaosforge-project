from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from chaosforge.lifecycle.checks.aws_adapters import (
    EC2AutoScalingGroupAdapter,
    EC2ResourceAdapter,
    ECSServiceAdapter,
    ElastiCacheClusterAdapter,
    ELBListenerAdapter,
    ELBLoadBalancerAdapter,
    ELBTargetGroupAdapter,
    S3BucketAdapter,
    SNSSubscriptionAdapter,
    VPCResourceAdapter,
)

MODULE_CLIENT = "chaosforge.lifecycle.checks.aws_adapters.boto3.client"


def client_error(code="AccessDenied", operation="Operation"):
    return ClientError({"Error": {"Code": code, "Message": "failed"}}, operation)


@patch(MODULE_CLIENT)
def test_ec2_adapter_normalizes_ids_and_collects_only_ebs_mappings(mock_client):
    ec2 = mock_client.return_value
    ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-2",
                        "State": {"Name": "running"},
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/xvda",
                                "Ebs": {"VolumeId": "vol-1", "Status": "attached"},
                            },
                            {"DeviceName": "ephemeral0"},
                        ],
                    }
                ]
            }
        ]
    }

    result = EC2ResourceAdapter().capture(
        {"aws_region": "eu-west-1", "instance_ids": [" i-2 ", "", None]}
    )

    ec2.describe_instances.assert_called_once_with(InstanceIds=["i-2", "None"])
    assert result == {
        "exists": True,
        "identity": {"instance_ids": ["i-2", "None"]},
        "state": {"instance_states": {"i-2": "running"}},
        "configuration": {
            "block_device_mappings": {
                "i-2": [
                    {
                        "volume_id": "vol-1",
                        "device_name": "/dev/xvda",
                        "attachment_state": "attached",
                    }
                ]
            }
        },
    }


@patch(MODULE_CLIENT)
def test_ec2_adapter_accepts_legacy_single_id_and_reports_missing(mock_client):
    mock_client.return_value.describe_instances.return_value = {"Reservations": []}

    result = EC2ResourceAdapter().capture(
        {"aws_region": "eu-west-1", "instance_id": "i-legacy"}
    )

    assert result["exists"] is False
    assert result["identity"] == {"instance_ids": ["i-legacy"]}


@patch(MODULE_CLIENT)
def test_ec2_adapter_accepts_instance_ids_as_a_string(mock_client):
    mock_client.return_value.describe_instances.return_value = {"Reservations": []}

    result = EC2ResourceAdapter().capture(
        {"aws_region": "eu-west-1", "instance_ids": "i-direct"}
    )

    assert result["identity"] == {"instance_ids": ["i-direct"]}


@pytest.mark.parametrize("target", [{"instance_ids": []}, {"instance_id": ""}])
def test_ec2_adapter_requires_an_instance_id(target):
    with pytest.raises(ValueError, match="At least one EC2 instance ID"):
        EC2ResourceAdapter().capture({"aws_region": "eu-west-1", **target})


@patch(MODULE_CLIENT)
def test_asg_adapter_filters_instances_and_sorts_volume_mappings(mock_client):
    autoscaling = MagicMock()
    ec2 = MagicMock()
    mock_client.side_effect = [autoscaling, ec2]
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "Instances": [
                    {"InstanceId": "i-2", "LifecycleState": "InService"},
                    {"InstanceId": "i-1", "LifecycleState": "InService"},
                    {"InstanceId": "i-old", "LifecycleState": "Terminating"},
                    {"LifecycleState": "InService"},
                ]
            }
        ]
    }
    ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-2",
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/xvdb",
                                "Ebs": {"VolumeId": "vol-b", "DeleteOnTermination": False},
                            },
                            {
                                "DeviceName": "/dev/xvda",
                                "Ebs": {"VolumeId": "vol-a", "DeleteOnTermination": True},
                            },
                            {"DeviceName": "ephemeral0"},
                        ],
                    }
                ]
            }
        ]
    }

    result = EC2AutoScalingGroupAdapter().capture(
        {"aws_region": "eu-west-1", "autoscaling_group": "web"}
    )

    assert result["state"]["instance_ids"] == ["i-1", "i-2"]
    assert [
        item["volume_id"]
        for item in result["configuration"]["block_device_mappings"]["i-2"]
    ] == ["vol-a", "vol-b"]


@patch(MODULE_CLIENT)
def test_asg_adapter_returns_absent_without_describing_instances(mock_client):
    autoscaling = MagicMock()
    ec2 = MagicMock()
    mock_client.side_effect = [autoscaling, ec2]
    autoscaling.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": []}

    result = EC2AutoScalingGroupAdapter().capture(
        {"aws_region": "eu-west-1", "autoscaling_group": "gone"}
    )

    assert result == {
        "exists": False,
        "identity": {"name": "gone"},
        "state": {},
        "configuration": {},
    }
    ec2.describe_instances.assert_not_called()


@patch(MODULE_CLIENT)
def test_elasticache_cluster_adapter_present_and_absent(mock_client):
    cache = mock_client.return_value
    cache.describe_cache_clusters.side_effect = [
        {
            "CacheClusters": [
                {
                    "CacheClusterId": "cache-1",
                    "ARN": "cache-arn",
                    "CacheClusterStatus": "available",
                    "Engine": "redis",
                    "EngineVersion": "7.1",
                    "NumCacheNodes": 2,
                    "PreferredAvailabilityZone": "eu-west-1a",
                }
            ]
        },
        {"CacheClusters": []},
    ]
    adapter = ElastiCacheClusterAdapter()

    present = adapter.capture({"aws_region": "eu-west-1", "cache_cluster_id": "cache-1"})
    absent = adapter.capture({"aws_region": "eu-west-1", "cache_cluster_id": "gone"})

    assert present["configuration"] == {
        "engine": "redis",
        "engine_version": "7.1",
        "num_cache_nodes": 2,
        "preferred_availability_zone": "eu-west-1a",
    }
    assert absent["exists"] is False


@pytest.mark.parametrize(
    ("adapter", "target", "response_method", "response_key", "identity"),
    [
        (
            ECSServiceAdapter(),
            {"ecs_cluster": "cluster", "ecs_service": "service"},
            "describe_services",
            "services",
            {"cluster": "cluster", "name": "service"},
        ),
        (
            ELBTargetGroupAdapter(),
            {"target_group": "tg-arn"},
            "describe_target_groups",
            "TargetGroups",
            {"arn": "tg-arn"},
        ),
        (
            ELBLoadBalancerAdapter(),
            {"load_balancer": "lb-arn"},
            "describe_load_balancers",
            "LoadBalancers",
            {"arn": "lb-arn"},
        ),
        (
            ELBListenerAdapter(),
            {"listener": "listener-arn"},
            "describe_listeners",
            "Listeners",
            {"arn": "listener-arn"},
        ),
    ],
)
@patch(MODULE_CLIENT)
def test_adapters_report_absent_resources(
    mock_client, adapter, target, response_method, response_key, identity
):
    getattr(mock_client.return_value, response_method).return_value = {response_key: []}

    result = adapter.capture({"aws_region": "eu-west-1", **target})

    assert result == {
        "exists": False,
        "identity": identity,
        "state": {},
        "configuration": {},
    }


@patch(MODULE_CLIENT)
def test_s3_head_failure_returns_error_without_optional_requests(mock_client):
    s3 = mock_client.return_value
    s3.head_bucket.side_effect = client_error("NoSuchBucket", "HeadBucket")

    result = S3BucketAdapter().capture(
        {"aws_region": "eu-west-1", "bucket": "missing"}
    )

    assert result["exists"] is False
    assert result["identity"] == {"bucket": "missing"}
    assert "NoSuchBucket" in result["error"]
    s3.get_bucket_encryption.assert_not_called()


@patch(MODULE_CLIENT)
def test_s3_optional_configuration_failures_use_safe_defaults(mock_client):
    s3 = mock_client.return_value
    s3.head_bucket.return_value = {}
    for method in (
        "get_bucket_encryption",
        "get_bucket_versioning",
        "get_public_access_block",
        "get_bucket_lifecycle_configuration",
        "get_bucket_policy",
    ):
        getattr(s3, method).side_effect = client_error(operation=method)

    result = S3BucketAdapter().capture(
        {"aws_region": "eu-west-1", "bucket": "restricted"}
    )

    assert result["configuration"] == {
        "encryption": None,
        "versioning": None,
        "public_access_block": None,
        "lifecycle": [],
        "policy": None,
    }


@pytest.mark.parametrize("code", ["NotFound", "NotFoundException"])
@patch(MODULE_CLIENT)
def test_sns_subscription_not_found_is_absent(mock_client, code):
    mock_client.return_value.get_subscription_attributes.side_effect = client_error(
        code, "GetSubscriptionAttributes"
    )

    result = SNSSubscriptionAdapter().capture(
        {"aws_region": "eu-west-1", "subscription_arn": "sub-arn"}
    )

    assert result["exists"] is False


@patch(MODULE_CLIENT)
def test_sns_subscription_propagates_non_not_found_errors(mock_client):
    error = client_error("AccessDenied", "GetSubscriptionAttributes")
    mock_client.return_value.get_subscription_attributes.side_effect = error

    with pytest.raises(ClientError) as exc_info:
        SNSSubscriptionAdapter().capture(
            {"aws_region": "eu-west-1", "subscription_arn": "sub-arn"}
        )

    assert exc_info.value is error


@pytest.mark.parametrize(
    ("resource_type", "target", "method", "key"),
    [
        ("security-group", {"security_group_id": "sg-1"}, "describe_security_groups", "SecurityGroups"),
        ("route-table", {"route_table_id": "rt-1"}, "describe_route_tables", "RouteTables"),
        ("network-acl", {"network_acl_id": "acl-1"}, "describe_network_acls", "NetworkAcls"),
        (
            "internet-gateway",
            {"internet_gateway_id": "igw-1"},
            "describe_internet_gateways",
            "InternetGateways",
        ),
    ],
)
@patch(MODULE_CLIENT)
def test_vpc_resource_variants_report_absence(
    mock_client, resource_type, target, method, key
):
    getattr(mock_client.return_value, method).return_value = {key: []}

    result = VPCResourceAdapter().capture(
        {"aws_region": "eu-west-1", "resource_type": resource_type, **target}
    )

    assert result["exists"] is False
    assert result["identity"] == {"id": next(iter(target.values()))}


@patch(MODULE_CLIENT)
def test_vpc_resource_rejects_unknown_type(mock_client):
    with pytest.raises(ValueError, match="Unsupported VPC resource type: subnet"):
        VPCResourceAdapter().capture(
            {"aws_region": "eu-west-1", "resource_type": "subnet"}
        )
