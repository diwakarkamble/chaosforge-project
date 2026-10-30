from typing import Any

import boto3

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class LambdaResourceAdapter(ResourceAdapter):
    """
    Adapter for reading an AWS Lambda function.

    The adapter converts Lambda configuration and related
    concurrency/invoke settings into a normalized resource
    snapshot consumed by CommonResourceCheck.
    """

    name = "lambda-resource-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        function_name = target["lambda_name"]
        region = target["aws_region"]

        client = boto3.client("lambda", region_name=region)

        response = client.get_function(
            FunctionName=function_name,
        )

        configuration = response.get("Configuration", {})

        snapshot = {
            "exists": True,
            "identity": {
                "name": configuration.get("FunctionName"),
                "arn": configuration.get("FunctionArn"),
            },
            "state": {
                "state": configuration.get("State"),
                "state_reason": configuration.get("StateReason"),
                "last_update_status": configuration.get(
                    "LastUpdateStatus"
                ),
            },
            "configuration": {
                "runtime": configuration.get("Runtime"),
                "handler": configuration.get("Handler"),
                "memory_size": configuration.get("MemorySize"),
                "timeout": configuration.get("Timeout"),
                "role": configuration.get("Role"),
                "architectures": configuration.get("Architectures"),
                "package_type": configuration.get("PackageType"),
            },
        }

        concurrency = client.get_function_concurrency(
            FunctionName=function_name,
        )

        snapshot["concurrency"] = {
            "reserved_concurrency": concurrency.get(
                "ReservedConcurrentExecutions"
            ),
        }

        try:
            provisioned = client.get_provisioned_concurrency_config(
                FunctionName=function_name,
                Qualifier="provisioned",
            )
        except client.exceptions.ResourceNotFoundException:
            provisioned = {}

        snapshot["provisioned_concurrency"] = {
            "allocated": provisioned.get(
                "AllocatedProvisionedConcurrentExecutions"
            ),
            "requested": provisioned.get(
                "RequestedProvisionedConcurrentExecutions"
            ),
            "status": provisioned.get("Status"),
        }

        try:
            invoke_config = client.get_function_event_invoke_config(
                FunctionName=function_name,
            )
        except client.exceptions.ResourceNotFoundException:
            invoke_config = {}

        snapshot["async_invoke"] = {
            "maximum_retry_attempts": invoke_config.get(
                "MaximumRetryAttempts",
                2,
            ),
            "maximum_event_age": invoke_config.get(
                "MaximumEventAgeInSeconds"
            ),
        }

        return snapshot
