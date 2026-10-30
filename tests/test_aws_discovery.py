from unittest.mock import MagicMock, patch

import pytest
from kubernetes.config.config_exception import ConfigException

from chaosforge.providers.aws.discovery import AWSDiscovery


def test_constructor():

    discovery = AWSDiscovery("eu-central-1")

    assert discovery.region == "eu-central-1"

@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_verify_aws_credentials_success(mock_client):

    client = MagicMock()

    client.get_caller_identity.return_value = {
        "Account": "123456789012",
        "Arn": "arn:aws:iam::123456789012:user/test-user",
        "UserId": "AIDATESTUSER",
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.verify_aws_credentials()

    assert result == {
        "authenticated": True,
        "account_id": "123456789012",
        "arn": "arn:aws:iam::123456789012:user/test-user",
        "user_id": "AIDATESTUSER",
        "region": "eu-central-1",
    }

    mock_client.assert_called_once_with(
        "sts",
        region_name="eu-central-1",
    )
    client.get_caller_identity.assert_called_once_with()


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_verify_aws_credentials_failure(mock_client):

    client = MagicMock()

    client.get_caller_identity.side_effect = Exception("Invalid credentials")

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    with pytest.raises(RuntimeError, match="AWS authentication failed"):
        discovery.verify_aws_credentials()


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_lambda_functions(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.list_functions.return_value = {
        "Functions": [{"FunctionName": "demo", "FunctionArn": "arn:lambda"}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_lambda_functions()

    assert result == [{"name": "demo", "arn": "arn:lambda"}]


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_dynamodb_tables(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.list_tables.return_value = {"TableNames": ["Users"]}

    client.describe_table.return_value = {"Table": {"TableArn": "arn:dynamodb"}}

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_dynamodb_tables()

    assert result == [{"name": "Users", "arn": "arn:dynamodb"}]


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_rds_instances(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceIdentifier": "db1", "DBInstanceArn": "arn:rds"}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_rds_instances()

    assert result == [{"name": "db1", "identifier": "db1", "arn": "arn:rds"}]


def test_discover_lambda():

    discovery = AWSDiscovery("eu-central-1")

    discovery.list_lambda_functions = MagicMock(return_value=["ok"])

    result = discovery.discover("lambda")

    assert result == ["ok"]


def test_discover_sns_subscriptions():

    discovery = AWSDiscovery("eu-central-1")

    discovery.list_sns_subscriptions = MagicMock(return_value=["subscription"])

    result = discovery.discover("sns_subscription")

    assert result == ["subscription"]


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_ec2_instances(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.describe_instances.return_value = {
        "Reservations": [
            {
                "OwnerId": "111111111111",
                "Instances": [
                    {
                        "InstanceId": "i-123",
                        "Tags": [{"Key": "Name", "Value": "WebServer"}],
                    }
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_ec2_instances()

    assert result[0]["name"] == "WebServer"
    assert result[0]["id"] == "i-123"
    assert result[0]["arn"] == (
        "arn:aws:ec2:eu-central-1:111111111111:instance/i-123"
    )


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_sns_topics(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.list_topics.return_value = {
        "Topics": [{"TopicArn": "arn:aws:sns:eu-central-1:111:test-topic"}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_sns_topics()

    assert result[0]["name"] == "test-topic"


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_security_groups(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.describe_security_groups.return_value = {
        "SecurityGroups": [
            {
                "GroupName": "default",
                "GroupId": "sg-1",
                "VpcId": "vpc-1",
                "Description": "demo",
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_security_groups()

    assert result[0]["id"] == "sg-1"


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_apigateway_rest_apis(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.get_rest_apis.return_value = {
        "items": [{"id": "abc123", "name": "OrdersAPI"}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_apigateway_rest_apis()

    assert result[0]["id"] == "abc123"


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_apigateway_stages(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.get_stages.return_value = {"item": [{"stageName": "dev"}]}

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_apigateway_stages("abc123")

    assert result[0]["stageName"] == "dev"


@patch("chaosforge.providers.aws.discovery.print")
@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_elasticache_serverless(mock_client, mock_spinner, mock_info, mock_print):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [
            {"ServerlessCacheName": "cache-demo", "ARN": "arn:aws:elasticache:cache"}
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_elasticache_serverless()

    assert result == [{"name": "cache-demo", "arn": "arn:aws:elasticache:cache"}]


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_sns_subscriptions(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    paginator = MagicMock()

    paginator.paginate.return_value = [
        {
            "Subscriptions": [
                {
                    "Protocol": "email",
                    "Endpoint": "abc@test.com",
                    "SubscriptionArn": "arn:subscription",
                }
            ]
        }
    ]

    client.get_paginator.return_value = paginator

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_sns_subscriptions()

    assert result == [{"name": "email -> abc@test.com", "arn": "arn:subscription"}]


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_sns_subscriptions_pending(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    paginator = MagicMock()

    paginator.paginate.return_value = [
        {
            "Subscriptions": [
                {
                    "Protocol": "email",
                    "Endpoint": "abc@test.com",
                    "SubscriptionArn": "PendingConfirmation",
                }
            ]
        }
    ]

    client.get_paginator.return_value = paginator

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_sns_subscriptions()

    assert result == []


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_security_group_rules_single_port(mock_client):

    client = MagicMock()

    client.describe_security_groups.return_value = {
        "SecurityGroups": [
            {
                "IpPermissions": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    }
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    rules = discovery.list_security_group_rules("sg-123")

    assert len(rules) == 1

    assert "TCP" in rules[0]["name"]

    assert "443" in rules[0]["name"]

    assert "0.0.0.0/0" in rules[0]["name"]


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_security_group_rules_all_protocol(mock_client):

    client = MagicMock()

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"IpPermissions": [{"IpProtocol": "-1", "IpRanges": []}]}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    rules = discovery.list_security_group_rules("sg-123")

    assert "ALL" in rules[0]["name"]

    assert "N/A" in rules[0]["name"]


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_security_group_rules_multiple_sources(mock_client):

    client = MagicMock()

    client.describe_security_groups.return_value = {
        "SecurityGroups": [
            {
                "IpPermissions": [
                    {
                        "IpProtocol": "udp",
                        "FromPort": 100,
                        "ToPort": 200,
                        "Ipv6Ranges": [{"CidrIpv6": "::/0"}],
                        "UserIdGroupPairs": [{"GroupId": "sg-999"}],
                        "PrefixListIds": [{"PrefixListId": "pl-123"}],
                    }
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    rules = discovery.list_security_group_rules("sg-123")

    text = rules[0]["name"]

    assert "UDP" in text

    assert "100-200" in text

    assert "::/0" in text

    assert "sg-999" in text

    assert "pl-123" in text


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_route_tables(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.describe_route_tables.return_value = {
        "RouteTables": [
            {
                "RouteTableId": "rtb-123",
                "VpcId": "vpc-123",
                "Tags": [{"Key": "Name", "Value": "Private Routes"}],
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_route_tables()

    assert result == [{"id": "rtb-123", "name": "Private Routes | rtb-123 | vpc-123"}]


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_route_tables_without_name(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.describe_route_tables.return_value = {
        "RouteTables": [{"RouteTableId": "rtb-999", "VpcId": "vpc-999", "Tags": []}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_route_tables()

    assert result[0]["id"] == "rtb-999"

    assert result[0]["name"] == "rtb-999 | rtb-999 | vpc-999"


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_routes_igw(mock_client):

    client = MagicMock()

    client.describe_route_tables.return_value = {
        "RouteTables": [
            {"Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-123"}]}
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    routes = discovery.list_routes("rtb-123")

    assert len(routes) == 1
    assert routes[0]["name"] == "0.0.0.0/0 → IGW : igw-123"


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_routes_skip_local_and_propagated(mock_client):

    client = MagicMock()

    client.describe_route_tables.return_value = {
        "RouteTables": [
            {
                "Routes": [
                    {"Origin": "EnableVgwRoutePropagation"},
                    {"GatewayId": "local"},
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    routes = discovery.list_routes("rtb-123")

    assert routes == []


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_routes_nat_gateway(mock_client):

    client = MagicMock()

    client.describe_route_tables.return_value = {
        "RouteTables": [
            {
                "Routes": [
                    {"DestinationCidrBlock": "10.0.0.0/16", "NatGatewayId": "nat-123"}
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    routes = discovery.list_routes("rtb-123")

    assert "NAT : nat-123" in routes[0]["name"]


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_routes_unknown_target(mock_client):

    client = MagicMock()

    client.describe_route_tables.return_value = {
        "RouteTables": [{"Routes": [{"DestinationCidrBlock": "192.168.0.0/16"}]}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    routes = discovery.list_routes("rtb-123")

    assert routes[0]["name"] == "192.168.0.0/16 → Unknown"


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_network_acls(mock_client):

    client = MagicMock()

    client.describe_network_acls.return_value = {
        "NetworkAcls": [{"NetworkAclId": "acl-123", "VpcId": "vpc-123"}]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_network_acls()

    assert result == [{"id": "acl-123", "name": "acl-123 | vpc-123"}]


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_network_acl_rules(mock_client):

    client = MagicMock()

    client.describe_network_acls.return_value = {
        "NetworkAcls": [
            {
                "Entries": [
                    {
                        "RuleNumber": 100,
                        "Egress": False,
                        "Protocol": "6",
                        "CidrBlock": "0.0.0.0/0",
                        "RuleAction": "allow",
                    }
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    rules = discovery.list_network_acl_rules("acl-123")

    assert len(rules) == 1

    assert "Ingress" in rules[0]["name"]

    assert "Rule 100" in rules[0]["name"]

    assert "allow" in rules[0]["name"]
    assert rules[0]["id"] == 0


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_network_acl_rules_skip_default(mock_client):

    client = MagicMock()

    client.describe_network_acls.return_value = {
        "NetworkAcls": [
            {
                "Entries": [
                    {
                        "RuleNumber": 32767,
                        "Egress": False,
                        "Protocol": "6",
                        "CidrBlock": "0.0.0.0/0",
                        "RuleAction": "deny",
                    }
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    rules = discovery.list_network_acl_rules("acl-123")

    assert rules == []


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_network_acl_rules_ipv6(mock_client):

    client = MagicMock()

    client.describe_network_acls.return_value = {
        "NetworkAcls": [
            {
                "Entries": [
                    {
                        "RuleNumber": 200,
                        "Egress": True,
                        "Protocol": "17",
                        "Ipv6CidrBlock": "::/0",
                        "RuleAction": "deny",
                    }
                ]
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    rules = discovery.list_network_acl_rules("acl-123")

    text = rules[0]["name"]

    assert "Egress" in text

    assert "::/0" in text

    assert "deny" in text


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_internet_gateways(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.describe_internet_gateways.return_value = {
        "InternetGateways": [
            {"InternetGatewayId": "igw-123", "Attachments": [{"VpcId": "vpc-123"}]},
            {"InternetGatewayId": "igw-456", "Attachments": []},
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_internet_gateways()

    assert result[0]["name"] == "igw-123 | vpc-123"

    assert result[1]["name"] == "igw-456 | Not Attached"


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_elb_load_balancers(mock_client):

    client = MagicMock()

    client.describe_load_balancers.return_value = {
        "LoadBalancers": [
            {
                "LoadBalancerName": "test-alb",
                "LoadBalancerArn": (
                    "arn:aws:elasticloadbalancing:"
                    "eu-central-1:123456789012:"
                    "loadbalancer/app/test-alb/abc123"
                ),
                "Type": "application",
                "Scheme": "internet-facing",
                "VpcId": "vpc-123",
                "State": {
                    "Code": "active",
                },
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_elb_load_balancers()

    assert len(result) == 1

    assert result[0]["name"] == "test-alb"
    assert result[0]["type"] == "application"
    assert result[0]["scheme"] == "internet-facing"
    assert result[0]["vpc_id"] == "vpc-123"
    assert result[0]["state"] == "active"

    assert result[0]["arn"] == (
        "arn:aws:elasticloadbalancing:"
        "eu-central-1:123456789012:"
        "loadbalancer/app/test-alb/abc123"
    )

    client.describe_load_balancers.assert_called_once_with()


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_elb_target_groups(mock_client):

    client = MagicMock()

    load_balancer_arn = (
        "arn:aws:elasticloadbalancing:"
        "eu-central-1:123456789012:"
        "loadbalancer/app/test-alb/abc123"
    )

    target_group_arn = (
        "arn:aws:elasticloadbalancing:"
        "eu-central-1:123456789012:"
        "targetgroup/test-targets/def456"
    )

    client.describe_target_groups.return_value = {
        "TargetGroups": [
            {
                "TargetGroupName": "test-targets",
                "TargetGroupArn": target_group_arn,
                "TargetType": "instance",
                "Protocol": "HTTP",
                "Port": 80,
                "VpcId": "vpc-123",
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_elb_target_groups(load_balancer_arn)

    assert len(result) == 1

    assert result[0]["name"] == "test-targets"
    assert result[0]["arn"] == target_group_arn
    assert result[0]["target_type"] == "instance"
    assert result[0]["protocol"] == "HTTP"
    assert result[0]["port"] == 80
    assert result[0]["vpc_id"] == "vpc-123"
    assert result[0]["load_balancer_arn"] == load_balancer_arn

    client.describe_target_groups.assert_called_once_with(
        LoadBalancerArn=load_balancer_arn,
    )


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_elb_targets(mock_client):

    client = MagicMock()

    target_group_arn = (
        "arn:aws:elasticloadbalancing:"
        "eu-central-1:123456789012:"
        "targetgroup/test-targets/def456"
    )

    client.describe_target_health.return_value = {
        "TargetHealthDescriptions": [
            {
                "Target": {
                    "Id": "i-1234567890",
                    "Port": 80,
                },
                "TargetHealth": {
                    "State": "healthy",
                },
            }
        ]
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_elb_targets(target_group_arn)

    assert len(result) == 1

    assert result[0]["id"] == "i-1234567890"
    assert result[0]["target_id"] == "i-1234567890"
    assert result[0]["port"] == 80
    assert result[0]["health"] == "healthy"
    assert result[0]["target_group_arn"] == target_group_arn
    assert "i-1234567890" in result[0]["name"]
    assert "healthy" in result[0]["name"]

    client.describe_target_health.assert_called_once_with(
        TargetGroupArn=target_group_arn,
    )


# ==========================================================
# Additional AWSDiscovery coverage - Batch 1
# ==========================================================


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_ecs_clusters_empty(mock_boto_client):

    client = MagicMock()

    client.list_clusters.return_value = {"clusterArns": []}

    mock_boto_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_ecs_clusters()

    assert result == []

    client.list_clusters.assert_called_once()


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_ecs_services_empty(mock_boto_client):

    client = MagicMock()

    client.list_services.return_value = {"serviceArns": []}

    mock_boto_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_ecs_services("cluster-arn")

    assert result == []

    client.list_services.assert_called_once_with(cluster="cluster-arn")


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_ecs_tasks_empty(mock_boto_client):

    client = MagicMock()

    client.list_tasks.return_value = {"taskArns": []}

    mock_boto_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_ecs_tasks(
        "cluster-arn",
        "service-name",
    )

    assert result == []

    client.list_tasks.assert_called_once_with(
        cluster="cluster-arn",
        serviceName="service-name",
    )


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_dynamodb_tables_empty(mock_boto_client):

    client = MagicMock()

    client.list_tables.return_value = {"TableNames": []}

    mock_boto_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_dynamodb_tables()

    assert result == []

    client.list_tables.assert_called_once()


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_rds_instances_empty(mock_boto_client):

    client = MagicMock()

    client.describe_db_instances.return_value = {"DBInstances": []}

    mock_boto_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_rds_instances()

    assert result == []

    client.describe_db_instances.assert_called_once()


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_rds_instance_classes_returns_valid_modifications(mock_boto_client):
    client = MagicMock()
    client.describe_db_instances.return_value = {"DBInstances": [{"DBInstanceStatus": "available"}]}
    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.t4g.large", "db.t4g.medium"]},
                {"ValidDBInstanceClasses": ["db.t4g.large"]},
            ]
        }
    }
    mock_boto_client.return_value = client

    result = AWSDiscovery("eu-central-1").list_rds_instance_classes("database")

    assert result == [{"name": "db.t4g.large"}, {"name": "db.t4g.medium"}]
    client.describe_valid_db_instance_modifications.assert_called_once_with(
        DBInstanceIdentifier="database"
    )


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_rds_instance_classes_requires_an_available_instance(mock_boto_client):
    client = MagicMock()
    client.describe_db_instances.return_value = {"DBInstances": [{"DBInstanceStatus": "storage-optimization"}]}
    mock_boto_client.return_value = client

    with pytest.raises(RuntimeError, match="storage-optimization"):
        AWSDiscovery("eu-central-1").list_rds_instance_classes("database")

    client.describe_valid_db_instance_modifications.assert_not_called()


@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_elasticache_serverless_empty(mock_boto_client):

    client = MagicMock()

    client.describe_serverless_caches.return_value = {"ServerlessCaches": []}

    mock_boto_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_elasticache_serverless()

    assert result == []

    client.describe_serverless_caches.assert_called_once()


@patch("chaosforge.providers.aws.discovery.info")
@patch("chaosforge.providers.aws.discovery.spinner")
@patch("chaosforge.providers.aws.discovery.boto3.client")
def test_list_kinesis_streams(mock_client, mock_spinner, mock_info):

    mock_spinner.return_value.__enter__.return_value = None
    mock_spinner.return_value.__exit__.return_value = None

    client = MagicMock()

    client.list_streams.return_value = {"StreamNames": ["orders-stream"]}

    client.describe_stream.return_value = {
        "StreamDescription": {
            "StreamName": "orders-stream",
            "StreamARN": (
                "arn:aws:kinesis:eu-central-1:111111111111:stream/orders-stream"
            ),
        }
    }

    mock_client.return_value = client

    discovery = AWSDiscovery("eu-central-1")

    result = discovery.list_kinesis_streams()

    assert result == [
        {
            "name": "orders-stream",
            "arn": ("arn:aws:kinesis:eu-central-1:111111111111:stream/orders-stream"),
        }
    ]

def test_list_eks_nodes_matches_context_by_cluster_name(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        lambda: (
            [
                {
                    "name": "other",
                    "context": {"cluster": "other-cluster"},
                },
                {
                    "name": "Chaos-POC-v2",
                    "context": {"cluster": "some-cluster"},
                },
            ],
            None,
        ),
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.load_kube_config",
        lambda context=None: None,
    )

    class Node:
        def __init__(self, name, uid):
            self.metadata = type(
                "Metadata",
                (),
                {"name": name, "uid": uid},
            )()

    class FakeCore:
        def list_node(self):
            return type(
                "Response",
                (),
                {
                    "items": [
                        Node("node-1", "uid-1"),
                        Node("node-2", "uid-2"),
                    ]
                },
            )()

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.CoreV1Api",
        lambda: FakeCore(),
    )

    result = discovery.list_eks_nodes("Chaos-POC-v2")

    assert result == [
        {
            "name": "node-1",
            "cluster": "Chaos-POC-v2",
            "uid": "uid-1",
        },
        {
            "name": "node-2",
            "cluster": "Chaos-POC-v2",
            "uid": "uid-2",
        },
    ]

def test_list_eks_nodes_raises_when_kubernetes_api_fails(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        lambda: (
            [
                {
                    "name": "cluster",
                    "context": {"cluster": "cluster"},
                }
            ],
            None,
        ),
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.load_kube_config",
        lambda context=None: None,
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.CoreV1Api",
        lambda: (_ for _ in ()).throw(RuntimeError("API failure")),
    )

    with pytest.raises(
        LookupError,
        match="Unable to discover Kubernetes nodes",
    ):
        discovery.list_eks_nodes("cluster")

def test_configure_eks_client_uses_existing_context(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        lambda: (
            [
                {
                    "name": "my-context",
                    "context": {
                        "cluster": "arn:aws:eks:eu-central-1:123:cluster/test"
                    },
                }
            ],
            None,
        ),
    )

    load_calls = []

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.load_kube_config",
        lambda **kwargs: load_calls.append(kwargs),
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.CoreV1Api",
        lambda: object(),
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.AppsV1Api",
        lambda: object(),
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.CustomObjectsApi",
        lambda: object(),
    )

    discovery._configure_eks_kubernetes_client("test")

    assert load_calls == [
        {"context": "my-context"}
    ]
    assert discovery.k8s_core_api is not None
    assert discovery.k8s_apps_api is not None
    assert discovery.k8s_custom_api is not None

def test_configure_eks_client_falls_back_when_kubeconfig_missing(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        lambda: (_ for _ in ()).throw(
            ConfigException("no kubeconfig")
        ),
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.tempfile.mkstemp",
        lambda **kwargs: (123, "temp-kubeconfig"),
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.os.close",
        lambda fd: None,
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.subprocess.run",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        lambda config_file=None: (
            [
                {
                    "name": "test-context",
                    "context": {"cluster": "test"},
                }
            ],
            None,
        ),
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.load_kube_config",
        lambda **kwargs: None,
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.CoreV1Api",
        lambda: object(),
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.AppsV1Api",
        lambda: object(),
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.client.CustomObjectsApi",
        lambda: object(),
    )

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.os.remove",
        lambda path: None,
    )

    discovery._configure_eks_kubernetes_client("test")

    assert discovery.k8s_core_api is not None

def test_list_ec2_ebs_volumes_handles_tags_and_attachments(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeEC2:
        def describe_volumes(self, Filters):
            return {
                "Volumes": [
                    {
                        "VolumeId": "vol-1",
                        "OwnerId": "123456789",
                        "Attachments": [
                            {
                                "InstanceId": "i-123",
                                "Device": "/dev/xvdf",
                            }
                        ],
                        "Tags": [
                            {"Key": "Name", "Value": "data-volume"}
                        ],
                        "State": "in-use",
                        "Size": 100,
                        "VolumeType": "gp3",
                    },
                    {
                        "VolumeId": "vol-2",
                        "Attachments": [
                            {"InstanceId": "different"}
                        ],
                    },
                    {
                        "VolumeId": "vol-3",
                        "Attachments": [
                            {
                                "InstanceId": "i-123",
                                "Device": "/dev/xvdg",
                            }
                        ],
                    },
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeEC2(),
    )

    result = discovery.list_ec2_ebs_volumes("i-123")

    assert len(result) == 2

    assert result[0]["name"] == "data-volume"
    assert result[0]["arn"].endswith("/vol-1")
    assert result[0]["device_name"] == "/dev/xvdf"

    assert result[1]["name"] == "vol-3"
    assert result[1]["arn"] == ""


def test_list_ec2_ebs_volumes_without_owner_id(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeEC2:
        def describe_volumes(self, Filters):
            return {
                "Volumes": [
                    {
                        "VolumeId": "vol-no-owner",
                        "Attachments": [
                            {"InstanceId": "i-123"}
                        ],
                    }
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeEC2(),
    )

    result = discovery.list_ec2_ebs_volumes("i-123")

    assert result[0]["arn"] == ""

@pytest.mark.parametrize(
    "describe_instances_response",
    [
        {"Reservations": []},
        {"Reservations": [{"Instances": []}]},
        {
            "Reservations": [
                {
                    "Instances": [
                        {"Placement": {}}
                    ]
                }
            ]
        },
    ],
)
def test_list_available_ec2_ebs_volumes_empty_cases(
    monkeypatch,
    describe_instances_response,
):
    discovery = AWSDiscovery("eu-central-1")

    class FakeEC2:
        def describe_instances(self, InstanceIds):
            return describe_instances_response

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeEC2(),
    )

    assert discovery.list_available_ec2_ebs_volumes("i-123") == []

def test_list_available_ec2_ebs_volumes_filters_by_az(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeEC2:
        def describe_instances(self, InstanceIds):
            return {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "Placement": {
                                    "AvailabilityZone": "eu-central-1a"
                                }
                            }
                        ]
                    }
                ]
            }

        def describe_volumes(self, Filters):
            assert {
                "Name": "status",
                "Values": ["available"],
            } in Filters

            assert {
                "Name": "availability-zone",
                "Values": ["eu-central-1a"],
            } in Filters

            return {
                "Volumes": [
                    {
                        "VolumeId": "vol-1",
                        "OwnerId": "123",
                        "Tags": [
                            {"Key": "Name", "Value": "available-data"}
                        ],
                        "State": "available",
                        "Size": 50,
                        "VolumeType": "gp3",
                    },
                    {
                        "VolumeId": "vol-2",
                        "State": "available",
                        "Size": 20,
                        "VolumeType": "gp2",
                    },
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeEC2(),
    )

    result = discovery.list_available_ec2_ebs_volumes("i-123")

    assert len(result) == 2
    assert result[0]["name"] == "available-data"
    assert result[1]["name"] == "vol-2"
    assert result[0]["availability_zone"] == "eu-central-1a"

def test_list_ec2_spot_instances_handles_name_tag_and_owner(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeEC2:
        def describe_instances(self, Filters):
            return {
                "Reservations": [
                    {
                        "OwnerId": "123456",
                        "Instances": [
                            {
                                "InstanceId": "i-123",
                                "Tags": [
                                    {"Key": "Name", "Value": "spot-worker"}
                                ],
                            },
                            {
                                "InstanceId": "i-456",
                                "Tags": [],
                            },
                        ]
                    }
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeEC2(),
    )

    result = discovery.list_ec2_spot_instances()

    assert result == [
        {
            "name": "spot-worker",
            "id": "i-123",
            "arn": (
                "arn:aws:ec2:eu-central-1:"
                "123456:instance/i-123"
            ),
        },
        {
            "name": "i-456",
            "id": "i-456",
            "arn": (
                "arn:aws:ec2:eu-central-1:"
                "123456:instance/i-456"
            ),
        },
    ]

def test_list_elb_listeners(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeELB:
        def describe_listeners(self, LoadBalancerArn):
            assert LoadBalancerArn == "lb-arn"

            return {
                "Listeners": [
                    {
                        "ListenerArn": "listener-1",
                        "Protocol": "HTTPS",
                        "Port": 443,
                    },
                    {
                        "ListenerArn": "listener-2",
                    },
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeELB(),
    )

    result = discovery.list_elb_listeners("lb-arn")

    assert result[0]["name"] == "HTTPS:443"
    assert result[0]["id"] == "listener-1"
    assert result[0]["protocol"] == "HTTPS"
    assert result[0]["port"] == 443

    assert result[1]["name"] == "N/A:N/A"

def test_list_availability_zones_skips_zones_without_name(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeEC2:
        def describe_availability_zones(self, Filters):
            return {
                "AvailabilityZones": [
                    {
                        "ZoneName": "eu-central-1a",
                        "ZoneId": "euc1-az1",
                        "State": "available",
                    },
                    {
                        "ZoneId": "euc1-az2",
                        "State": "available",
                    },
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeEC2(),
    )

    result = discovery.list_availability_zones()

    assert len(result) == 1
    assert result[0]["name"] == "eu-central-1a"

def test_list_iam_roles(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeIAM:
        def list_roles(self):
            return {
                "Roles": [
                    {
                        "RoleName": "ChaosForgeRole",
                        "RoleId": "AROAXYZ",
                        "Arn": "arn:aws:iam::123:role/ChaosForgeRole",
                    },
                    {
                        "RoleName": "NoRoleId",
                        "Arn": "arn:aws:iam::123:role/NoRoleId",
                    },
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeIAM(),
    )

    result = discovery.list_iam_roles()

    assert result == [
        {
            "name": "ChaosForgeRole",
            "id": "AROAXYZ",
            "arn": "arn:aws:iam::123:role/ChaosForgeRole",
        },
        {
            "name": "NoRoleId",
            "id": "",
            "arn": "arn:aws:iam::123:role/NoRoleId",
        },
    ]

def test_list_auto_scaling_groups(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeASG:
        def describe_auto_scaling_groups(self):
            return {
                "AutoScalingGroups": [
                    {
                        "AutoScalingGroupName": "asg-1",
                        "AutoScalingGroupARN": "arn:aws:autoscaling:asg-1",
                    }
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeASG(),
    )

    result = discovery.list_auto_scaling_groups()

    assert result == [
        {
            "name": "asg-1",
            "id": "arn:aws:autoscaling:asg-1",
            "arn": "arn:aws:autoscaling:asg-1",
        }
    ]


def test_list_apigateway_apis_returns_rest_and_http(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeRest:
        def get_rest_apis(self):
            return {
                "items": [
                    {
                        "name": "rest-api",
                        "id": "rest-1",
                    }
                ]
            }

    class FakeHTTP:
        def get_apis(self):
            return {
                "Items": [
                    {
                        "Name": "http-api",
                        "ApiId": "http-1",
                        "ProtocolType": "HTTP",
                    }
                ]
            }

    def fake_client(service, **kwargs):
        if service == "apigateway":
            return FakeRest()
        if service == "apigatewayv2":
            return FakeHTTP()
        raise AssertionError(service)

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        fake_client,
    )

    result = discovery.list_apigateway_apis()

    assert result == [
        {
            "name": "rest-api",
            "id": "rest-1",
            "protocol": "REST",
        },
        {
            "name": "http-api",
            "id": "http-1",
            "protocol": "HTTP",
        },
    ]

def test_list_apigateway_stages_http(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeHTTP:
        def get_stages(self, ApiId):
            assert ApiId == "http-1"

            return {
                "Items": [
                    {
                        "StageName": "prod",
                    },
                    {
                        "StageName": "dev",
                    },
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda service, **kwargs: FakeHTTP(),
    )

    result = discovery.list_apigateway_stages(
        "http-1",
        protocol="HTTP",
    )

    assert result == [
        {
            "name": "prod",
            "stageName": "prod",
        },
        {
            "name": "dev",
            "stageName": "dev",
        },
    ]

def test_list_s3_buckets(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeS3:
        def list_buckets(self):
            return {
                "Buckets": [
                    {"Name": "chaosforge-test"},
                    {"Name": "chaosforge-prod"},
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeS3(),
    )

    result = discovery.list_s3_buckets()

    assert result == [
        {
            "id": "chaosforge-test",
            "name": "chaosforge-test",
            "arn": "arn:aws:s3:::chaosforge-test",
        },
        {
            "id": "chaosforge-prod",
            "name": "chaosforge-prod",
            "arn": "arn:aws:s3:::chaosforge-prod",
        },
    ]


def test_fis_target_discovery_lists_global_tables_clusters_replication_groups_and_volumes(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeDynamoDB:
        def list_global_tables(self):
            return {"GlobalTables": [{"GlobalTableName": "orders", "GlobalTableArn": "arn:global:orders"}]}

    class FakeRDS:
        def describe_db_clusters(self):
            return {"DBClusters": [{"DBClusterIdentifier": "orders", "DBClusterArn": "arn:rds:orders"}]}

    class FakeElastiCache:
        def describe_replication_groups(self):
            return {"ReplicationGroups": [{"ReplicationGroupId": "cache", "ARN": "arn:cache"}]}

    class FakeEC2:
        def describe_volumes(self):
            return {"Volumes": [{"VolumeId": "vol-1", "OwnerId": "123"}]}

    clients = {"dynamodb": FakeDynamoDB(), "rds": FakeRDS(), "elasticache": FakeElastiCache(), "ec2": FakeEC2()}
    monkeypatch.setattr("chaosforge.providers.aws.discovery.boto3.client", lambda service, **_: clients[service])

    assert discovery.list_dynamodb_global_tables() == [{"name": "orders", "arn": "arn:global:orders"}]
    assert discovery.list_rds_clusters() == [{"name": "orders", "arn": "arn:rds:orders"}]
    assert discovery.list_elasticache_replication_groups() == [{"name": "cache", "arn": "arn:cache"}]
    assert discovery.list_ec2_ebs_volumes_all() == [
        {"name": "vol-1", "id": "vol-1", "arn": "arn:aws:ec2:eu-central-1:123:volume/vol-1"}
    ]

def test_list_all_ecs_tasks(monkeypatch):
    discovery = AWSDiscovery("eu-central-1")

    class FakeECS:
        def list_clusters(self):
            return {
                "clusterArns": [
                    "arn:aws:ecs:eu-central-1:123:cluster/cluster-a",
                    "arn:aws:ecs:eu-central-1:123:cluster/cluster-b",
                ]
            }

        def list_tasks(self, cluster, desiredStatus):
            if cluster == "cluster-a":
                return {
                    "taskArns": [
                        "arn:aws:ecs:eu-central-1:123:task/task-123456789"
                    ]
                }

            return {"taskArns": []}

        def describe_tasks(self, cluster, tasks):
            return {
                "tasks": [
                    {
                        "taskArn": tasks[0],
                    }
                ]
            }

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.boto3.client",
        lambda *args, **kwargs: FakeECS(),
    )

    result = discovery.list_all_ecs_tasks()

    assert result == [
        {
            "name": "cluster-a / task-1234567",
            "arn": "arn:aws:ecs:eu-central-1:123:task/task-123456789",
        }
    ]
