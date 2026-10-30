from unittest.mock import MagicMock, patch

from chaosforge.lifecycle.checks.aws_adapters import (
    SNSSubscriptionAdapter,
    SNSTopicAdapter,
    VPCResourceAdapter,
)


@patch("chaosforge.lifecycle.checks.aws_adapters.boto3.client")
def test_sns_topic_adapter(mock_boto_client):
    client = MagicMock()
    mock_boto_client.return_value = client

    client.get_topic_attributes.return_value = {
        "Attributes": {
            "TopicArn": "arn:aws:sns:eu-central-1:123456789012:test-topic",
            "Owner": "123456789012",
            "Policy": "{\"Version\":\"2012-10-17\"}",
            "DeliveryPolicy": "{\"healthyRetryPolicy\":{}}",
            "DisplayName": "test-topic",
            "KmsMasterKeyId": "alias/test-key",
        }
    }

    adapter = SNSTopicAdapter()

    result = adapter.capture({
        "aws_region": "eu-central-1",
        "topic_arn": (
            "arn:aws:sns:eu-central-1:"
            "123456789012:test-topic"
        ),
    })

    assert result["exists"] is True
    assert result["identity"]["topic_arn"].endswith(":test-topic")
    assert result["state"]["owner"] == "123456789012"
    assert result["configuration"]["display_name"] == "test-topic"

    mock_boto_client.assert_called_once_with(
        "sns",
        region_name="eu-central-1",
    )


@patch("chaosforge.lifecycle.checks.aws_adapters.boto3.client")
def test_sns_subscription_adapter(mock_boto_client):
    client = MagicMock()
    mock_boto_client.return_value = client

    subscription_arn = (
        "arn:aws:sns:eu-central-1:"
        "123456789012:test-topic:sub-id"
    )

    client.get_subscription_attributes.return_value = {
        "Attributes": {
            "SubscriptionArn": subscription_arn,
            "FilterPolicy": "{\"event\":[\"test\"]}",
            "FilterPolicyScope": "MessageAttributes",
            "DeliveryPolicy": "{\"healthyRetryPolicy\":{}}",
            "RawMessageDelivery": "false",
            "RedrivePolicy": "{\"deadLetterTargetArn\":\"test\"}",
        }
    }

    adapter = SNSSubscriptionAdapter()

    result = adapter.capture({
        "aws_region": "eu-central-1",
        "subscription_arn": subscription_arn,
    })

    assert result["exists"] is True
    assert result["identity"]["subscription_arn"].endswith("sub-id")
    assert (
        result["configuration"]["filter_policy"]
        == "{\"event\":[\"test\"]}"
    )
    assert (
        result["configuration"]["filter_policy_scope"]
        == "MessageAttributes"
    )

    mock_boto_client.assert_called_once_with(
        "sns",
        region_name="eu-central-1",
    )


@patch("chaosforge.lifecycle.checks.aws_adapters.boto3.client")
def test_vpc_security_group_adapter(mock_boto_client):
    client = MagicMock()
    mock_boto_client.return_value = client

    client.describe_security_groups.return_value = {
        "SecurityGroups": [
            {
                "GroupId": "sg-123456",
                "GroupName": "test-sg",
                "VpcId": "vpc-123456",
                "Description": "Test security group",
                "IpPermissions": [],
                "IpPermissionsEgress": [],
            }
        ]
    }

    adapter = VPCResourceAdapter()

    result = adapter.capture({
        "aws_region": "eu-central-1",
        "resource_type": "security-group",
        "security_group_id": "sg-123456",
    })

    assert result["exists"] is True
    assert result["identity"]["id"] == "sg-123456"
    assert result["identity"]["name"] == "test-sg"
    assert result["identity"]["vpc_id"] == "vpc-123456"
    assert result["configuration"]["description"] == "Test security group"

    client.describe_security_groups.assert_called_once_with(
        GroupIds=["sg-123456"],
    )


@patch("chaosforge.lifecycle.checks.aws_adapters.boto3.client")
def test_vpc_route_table_adapter(mock_boto_client):
    client = MagicMock()
    mock_boto_client.return_value = client

    client.describe_route_tables.return_value = {
        "RouteTables": [
            {
                "RouteTableId": "rtb-123456",
                "VpcId": "vpc-123456",
                "Routes": [],
                "Associations": [],
                "PropagatingVgws": [],
            }
        ]
    }

    adapter = VPCResourceAdapter()

    result = adapter.capture({
        "aws_region": "eu-central-1",
        "resource_type": "route-table",
        "route_table_id": "rtb-123456",
    })

    assert result["exists"] is True
    assert result["identity"]["id"] == "rtb-123456"
    assert result["identity"]["vpc_id"] == "vpc-123456"
    assert result["configuration"]["routes"] == []
    assert result["configuration"]["associations"] == []

    client.describe_route_tables.assert_called_once_with(
        RouteTableIds=["rtb-123456"],
    )


@patch("chaosforge.lifecycle.checks.aws_adapters.boto3.client")
def test_vpc_network_acl_adapter(mock_boto_client):
    client = MagicMock()
    mock_boto_client.return_value = client

    client.describe_network_acls.return_value = {
        "NetworkAcls": [
            {
                "NetworkAclId": "acl-123456",
                "VpcId": "vpc-123456",
                "Entries": [],
                "Associations": [],
            }
        ]
    }

    adapter = VPCResourceAdapter()

    result = adapter.capture({
        "aws_region": "eu-central-1",
        "resource_type": "network-acl",
        "network_acl_id": "acl-123456",
    })

    assert result["exists"] is True
    assert result["identity"]["id"] == "acl-123456"
    assert result["identity"]["vpc_id"] == "vpc-123456"
    assert result["configuration"]["entries"] == []
    assert result["configuration"]["associations"] == []

    client.describe_network_acls.assert_called_once_with(
        NetworkAclIds=["acl-123456"],
    )


@patch("chaosforge.lifecycle.checks.aws_adapters.boto3.client")
def test_vpc_internet_gateway_adapter(mock_boto_client):
    client = MagicMock()
    mock_boto_client.return_value = client

    client.describe_internet_gateways.return_value = {
        "InternetGateways": [
            {
                "InternetGatewayId": "igw-123456",
                "Attachments": [
                    {
                        "VpcId": "vpc-123456",
                        "State": "available",
                    }
                ],
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": "test-igw",
                    }
                ],
            }
        ]
    }

    adapter = VPCResourceAdapter()

    result = adapter.capture({
        "aws_region": "eu-central-1",
        "resource_type": "internet-gateway",
        "internet_gateway_id": "igw-123456",
    })

    assert result["exists"] is True
    assert result["identity"]["id"] == "igw-123456"
    assert result["configuration"]["attachments"][0]["VpcId"] == "vpc-123456"
    assert result["configuration"]["tags"][0]["Value"] == "test-igw"

    client.describe_internet_gateways.assert_called_once_with(
        InternetGatewayIds=["igw-123456"],
    )
