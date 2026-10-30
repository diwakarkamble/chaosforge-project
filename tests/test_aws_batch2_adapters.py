from unittest.mock import MagicMock, patch

from chaosforge.lifecycle.checks.aws_adapters import (
    ECSServiceAdapter,
    ELBListenerAdapter,
    ELBLoadBalancerAdapter,
    ELBTargetGroupAdapter,
)


def test_ecs_service_adapter():
    client = MagicMock()

    client.describe_services.return_value = {
        "services": [
            {
                "serviceName": "test-service",
                "serviceArn": "arn:aws:ecs:test",
                "status": "ACTIVE",
                "runningCount": 2,
                "pendingCount": 0,
                "desiredCount": 2,
                "taskDefinition": "arn:aws:ecs:test-task:3",
            }
        ]
    }

    client.describe_task_definition.return_value = {
        "taskDefinition": {
            "revision": 3,
            "cpu": "512",
            "memory": "1024",
            "containerDefinitions": [
                {
                    "name": "app",
                    "cpu": 512,
                    "memory": 1024,
                    "memoryReservation": 512,
                }
            ],
        }
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = ECSServiceAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "ecs_cluster": "test-cluster",
                "ecs_service": "test-service",
            }
        )

    assert result["exists"] is True
    assert result["identity"]["name"] == "test-service"
    assert result["state"]["status"] == "ACTIVE"
    assert result["state"]["running_count"] == 2
    assert result["configuration"]["desired_count"] == 2
    assert (
        result["configuration"]["task_definition"]
        == "arn:aws:ecs:test-task:3"
    )

    assert (
        result["configuration"]["task_definition_cpu"]
        == "512"
    )

    assert (
        result["configuration"]["task_definition_memory"]
        == "1024"
    )

    assert (
        result["configuration"]["containers"][0]["name"]
        == "app"
    )

    assert (
        result["configuration"]["containers"][0]["cpu"]
        == 512
    )

    assert (
        result["configuration"]["containers"][0]["memory"]
        == 1024
    )

    assert (
        result["configuration"]["task_definition_memory"]
        == "1024"
    )

    assert (
        result["configuration"]["task_definition_revision"]
        == 3
    )




def test_elb_target_group_adapter():
    client = MagicMock()

    client.describe_target_groups.return_value = {
        "TargetGroups": [
            {
                "TargetGroupName": "test-target-group",
                "TargetType": "ip",
            }
        ]
    }

    client.describe_target_group_attributes.return_value = {
        "Attributes": [
            {
                "Key": "deregistration_delay.timeout_seconds",
                "Value": "300",
            },
            {
                "Key": "load_balancing.cross_zone.enabled",
                "Value": "true",
            },
            {
                "Key": "stickiness.enabled",
                "Value": "false",
            },
        ]
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = ELBTargetGroupAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "target_group": "arn:aws:elasticloadbalancing:test",
            }
        )

    assert result["exists"] is True
    assert result["identity"]["name"] == "test-target-group"
    assert (
        result["configuration"]["deregistration_delay"]
        == "300"
    )
    assert (
        result["configuration"]["cross_zone"]
        == "true"
    )
    assert (
        result["configuration"]["stickiness_enabled"]
        == "false"
    )


def test_elb_load_balancer_adapter():
    client = MagicMock()

    client.describe_load_balancers.return_value = {
        "LoadBalancers": [
            {
                "LoadBalancerName": "test-alb",
                "State": {
                    "Code": "active",
                },
            }
        ]
    }

    client.describe_load_balancer_attributes.return_value = {
        "Attributes": [
            {
                "Key": "deletion_protection.enabled",
                "Value": "false",
            },
            {
                "Key": "routing.http.drop_invalid_header_fields.enabled",
                "Value": "false",
            },
        ]
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = ELBLoadBalancerAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "load_balancer": "arn:aws:elasticloadbalancing:test",
            }
        )

    assert result["exists"] is True
    assert result["identity"]["name"] == "test-alb"
    assert result["state"]["state"] == "active"

    assert (
        result["configuration"]["attributes"][
            "deletion_protection.enabled"
        ]
        == "false"
    )


def test_elb_listener_adapter():
    client = MagicMock()

    client.describe_listeners.return_value = {
        "Listeners": [
            {
                "Port": 443,
                "Protocol": "HTTPS",
                "SslPolicy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
                "DefaultActions": [
                    {
                        "Type": "forward",
                    }
                ],
            }
        ]
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = ELBListenerAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "listener": "arn:aws:elasticloadbalancing:test",
            }
        )

    assert result["exists"] is True
    assert result["configuration"]["port"] == 443
    assert result["configuration"]["protocol"] == "HTTPS"
    assert (
        result["configuration"]["ssl_policy"]
        == "ELBSecurityPolicy-TLS13-1-2-2021-06"
    )
