from unittest.mock import MagicMock, patch

from chaosforge.lifecycle.checks.aws_adapters import (
    APIGatewayStageAdapter,
    S3BucketAdapter,
)


def test_api_gateway_stage_adapter():
    client = MagicMock()

    client.get_stage.return_value = {
        "deploymentId": "deployment-123",
        "cacheClusterEnabled": True,
        "cacheClusterSize": "0.5",
        "tracingEnabled": True,
        "variables": {
            "environment": "test",
        },
        "accessLogSettings": {
            "destinationArn": "arn:aws:logs:test",
            "format": "$context.requestId",
        },
        "methodSettings": {
            "*/*": {
                "cacheTtlInSeconds": 300,
                "throttlingRateLimit": 100,
                "throttlingBurstLimit": 200,
            }
        },
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = APIGatewayStageAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "api_gateway": "test-api",
                "stage": "test",
            }
        )

    assert result["exists"] is True
    assert result["identity"]["rest_api_id"] == "test-api"
    assert result["identity"]["stage"] == "test"

    assert (
        result["configuration"]["tracing_enabled"]
        is True
    )

    assert (
        result["configuration"]["cache_cluster_enabled"]
        is True
    )

    assert (
        result["configuration"]["cache_cluster_size"]
        == "0.5"
    )

    assert (
        result["configuration"]["variables"]["environment"]
        == "test"
    )


def test_api_gateway_stage_adapter_accepts_form_variable_names():
    client = MagicMock()
    client.get_stage.return_value = {}

    with patch("chaosforge.lifecycle.checks.aws_adapters.boto3.client", return_value=client):
        APIGatewayStageAdapter().capture(
            {"aws_region": "eu-central-1", "rest_api_id": "api", "stage_name": "prod"}
        )

    client.get_stage.assert_called_once_with(restApiId="api", stageName="prod")


def test_s3_bucket_adapter():
    client = MagicMock()

    client.head_bucket.return_value = {}

    client.get_bucket_encryption.return_value = {
        "ServerSideEncryptionConfiguration": {
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256",
                    }
                }
            ]
        }
    }

    client.get_bucket_versioning.return_value = {
        "Status": "Enabled",
    }

    client.get_public_access_block.return_value = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }
    }

    client.get_bucket_lifecycle_configuration.return_value = {
        "Rules": [
            {
                "ID": "test-rule",
                "Status": "Enabled",
            }
        ]
    }

    client.get_bucket_policy.return_value = {
        "Policy": '{"Version":"2012-10-17"}',
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = S3BucketAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "bucket_name": "test-bucket",
            }
        )

    assert result["exists"] is True
    assert (
        result["identity"]["bucket"]
        == "test-bucket"
    )

    assert (
        result["configuration"]["versioning"]
        == "Enabled"
    )

    assert (
        result["configuration"]["policy"]
        == '{"Version":"2012-10-17"}'
    )

    assert (
        result["configuration"]["public_access_block"][
            "BlockPublicAcls"
        ]
        is True
    )

    assert (
        result["configuration"]["lifecycle"][0]["ID"]
        == "test-rule"
    )
