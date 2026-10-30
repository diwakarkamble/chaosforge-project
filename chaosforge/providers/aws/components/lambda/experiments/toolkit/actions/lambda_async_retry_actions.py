import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "lambda_async_retry_actions.json")


def capture_current_retry_attempts(function_name, region):
    client = boto3.client("lambda", region_name=region)

    try:
        response = client.get_function_event_invoke_config(FunctionName=function_name)

        original_retry_attempts = response.get("MaximumRetryAttempts", 2)

    except client.exceptions.ResourceNotFoundException:
        original_retry_attempts = 2

    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "function_name": function_name,
                "original_retry_attempts": original_retry_attempts,
            },
            f,
        )

    print(f"Original retry attempts: {original_retry_attempts}")

    return {"original_retry_attempts": original_retry_attempts}


def update_retry_attempts(function_name, retry_attempts, region):
    retry_attempts = int(retry_attempts)

    if retry_attempts < 0 or retry_attempts > 2:
        raise ValueError("MaximumRetryAttempts must be between 0 and 2")

    client = boto3.client("lambda", region_name=region)

    client.put_function_event_invoke_config(
        FunctionName=function_name, MaximumRetryAttempts=retry_attempts
    )

    print(f"Updated retry attempts to {retry_attempts}")

    return {"retry_attempts": retry_attempts}


def wait_for_duration(wait_seconds):
    wait_seconds = int(wait_seconds)

    print(f"Waiting {wait_seconds} seconds...")

    time.sleep(wait_seconds)

    print("Wait completed.")

    return {"waited_seconds": wait_seconds}


def restore_retry_attempts(function_name, region):
    client = boto3.client("lambda", region_name=region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original_retry_attempts = state["original_retry_attempts"]

    client.put_function_event_invoke_config(
        FunctionName=function_name, MaximumRetryAttempts=original_retry_attempts
    )

    print(f"Restored retry attempts to {original_retry_attempts}")

    return {"restored_retry_attempts": original_retry_attempts}
