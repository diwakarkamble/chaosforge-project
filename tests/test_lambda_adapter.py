from unittest.mock import MagicMock, patch

from chaosforge.lifecycle.checks.lambda_adapter import LambdaResourceAdapter


class FakeResourceNotFoundException(Exception):
    pass


def test_lambda_adapter_capture():
    client = MagicMock()

    client.get_function.return_value = {
        "Configuration": {
            "FunctionName": "chaos-test-lambda",
            "FunctionArn": (
                "arn:aws:lambda:eu-central-1:111111111111:"
                "function:chaos-test-lambda"
            ),
            "State": "Active",
            "StateReason": "Idle",
            "LastUpdateStatus": "Successful",
            "Runtime": "python3.12",
            "Handler": "app.lambda_handler",
            "MemorySize": 512,
            "Timeout": 30,
            "Role": "arn:aws:iam::111111111111:role/test-role",
            "Architectures": ["x86_64"],
            "PackageType": "Zip",
        }
    }

    client.get_function_concurrency.return_value = {
        "ReservedConcurrentExecutions": 25,
    }

    client.get_provisioned_concurrency_config.return_value = {
        "AllocatedProvisionedConcurrentExecutions": 10,
        "RequestedProvisionedConcurrentExecutions": 10,
        "Status": "READY",
    }

    client.get_function_event_invoke_config.return_value = {
        "MaximumRetryAttempts": 2,
        "MaximumEventAgeInSeconds": 3600,
    }

    with patch(
        "chaosforge.lifecycle.checks.lambda_adapter.boto3.client",
        return_value=client,
    ) as mock_client:
        adapter = LambdaResourceAdapter()

        result = adapter.capture(
            {
                "lambda_name": "chaos-test-lambda",
                "aws_region": "eu-central-1",
            }
        )

    mock_client.assert_called_once_with(
        "lambda",
        region_name="eu-central-1",
    )

    client.get_function.assert_called_once_with(
        FunctionName="chaos-test-lambda",
    )

    client.get_function_concurrency.assert_called_once_with(
        FunctionName="chaos-test-lambda",
    )

    client.get_provisioned_concurrency_config.assert_called_once_with(
        FunctionName="chaos-test-lambda",
        Qualifier="provisioned",
    )

    client.get_function_event_invoke_config.assert_called_once_with(
        FunctionName="chaos-test-lambda",
    )

    assert result["exists"] is True
    assert result["identity"]["name"] == "chaos-test-lambda"

    assert result["state"]["state"] == "Active"
    assert result["state"]["last_update_status"] == "Successful"

    assert result["configuration"]["runtime"] == "python3.12"
    assert result["configuration"]["memory_size"] == 512
    assert result["configuration"]["timeout"] == 30

    assert result["concurrency"]["reserved_concurrency"] == 25

    assert (
        result["provisioned_concurrency"]["allocated"]
        == 10
    )
    assert (
        result["provisioned_concurrency"]["requested"]
        == 10
    )
    assert result["provisioned_concurrency"]["status"] == "READY"

    assert result["async_invoke"]["maximum_retry_attempts"] == 2
    assert result["async_invoke"]["maximum_event_age"] == 3600


def test_lambda_adapter_handles_missing_optional_configuration():
    client = MagicMock()

    client.exceptions.ResourceNotFoundException = (
        FakeResourceNotFoundException
    )

    client.get_function.return_value = {
        "Configuration": {
            "FunctionName": "demo",
        }
    }

    client.get_function_concurrency.return_value = {}

    client.get_provisioned_concurrency_config.side_effect = (
        FakeResourceNotFoundException(
            "No provisioned concurrency configuration"
        )
    )

    client.get_function_event_invoke_config.side_effect = (
        FakeResourceNotFoundException(
            "No event invoke configuration"
        )
    )

    with patch(
        "chaosforge.lifecycle.checks.lambda_adapter.boto3.client",
        return_value=client,
    ):
        adapter = LambdaResourceAdapter()

        result = adapter.capture(
            {
                "lambda_name": "demo",
                "aws_region": "ap-south-1",
            }
        )

    client.get_function.assert_called_once_with(
        FunctionName="demo",
    )

    assert result["exists"] is True
    assert result["identity"]["name"] == "demo"
    assert result["concurrency"]["reserved_concurrency"] is None
    assert result["provisioned_concurrency"]["allocated"] is None
    assert result["provisioned_concurrency"]["requested"] is None
    assert result["provisioned_concurrency"]["status"] is None
    assert result["async_invoke"]["maximum_retry_attempts"] == 2
    assert result["async_invoke"]["maximum_event_age"] is None
