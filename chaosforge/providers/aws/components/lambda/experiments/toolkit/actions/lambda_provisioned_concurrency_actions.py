import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(
    tempfile.gettempdir(), "lambda_provisioned_concurrency_actions.json"
)

ALIAS = "provisioned"


def capture_current_provisioned_concurrency(function_name, region):

    client = boto3.client("lambda", region_name=region)

    response = client.get_provisioned_concurrency_config(
        FunctionName=function_name, Qualifier=ALIAS
    )

    current = response["RequestedProvisionedConcurrentExecutions"]

    with open(STATE_FILE, "w") as f:
        json.dump({"value": current}, f)

    print(f"Current Provisioned Concurrency: {current}")


def update_provisioned_concurrency(function_name, provisioned_concurrency, region):

    client = boto3.client("lambda", region_name=region)

    client.put_provisioned_concurrency_config(
        FunctionName=function_name,
        Qualifier=ALIAS,
        ProvisionedConcurrentExecutions=int(provisioned_concurrency),
    )

    print(f"Updated Provisioned Concurrency to {provisioned_concurrency}")


def wait_for_duration(wait_seconds):

    print(f"Waiting {wait_seconds} seconds...")

    time.sleep(int(wait_seconds))


def restore_provisioned_concurrency(function_name, region):

    client = boto3.client("lambda", region_name=region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original = state["value"]

    client.put_provisioned_concurrency_config(
        FunctionName=function_name,
        Qualifier=ALIAS,
        ProvisionedConcurrentExecutions=int(original),
    )

    print(f"Provisioned Concurrency restored to {original}")
