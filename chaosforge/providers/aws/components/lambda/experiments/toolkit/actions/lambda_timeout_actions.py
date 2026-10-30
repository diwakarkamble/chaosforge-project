import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "lambda_timeout_state.json")


def capture_current_timeout(function_name, region):

    client = boto3.client("lambda", region_name=region)

    config = client.get_function_configuration(FunctionName=function_name)

    original_timeout = config["Timeout"]

    with open(STATE_FILE, "w") as f:
        json.dump(
            {"function_name": function_name, "original_timeout": original_timeout}, f
        )

    print(f"Original timeout: {original_timeout} seconds")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def update_timeout(function_name, timeout_value, region):

    client = boto3.client("lambda", region_name=region)

    current = client.get_function_configuration(FunctionName=function_name)

    current_timeout = current["Timeout"]

    print(
        f"Updating Lambda '{function_name}' "
        f"in region '{region}' "
        f"from {current_timeout}s "
        f"to {timeout_value}s"
    )

    client.update_function_configuration(
        FunctionName=function_name, Timeout=int(timeout_value)
    )

    waiter_for_update(client, function_name)

    print(f"Timeout updated successfully from {current_timeout}s to {timeout_value}s")


def restore_timeout(function_name, region):

    client = boto3.client("lambda", region_name=region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original = state["original_timeout"]

    print(f"Restoring Lambda '{function_name}' timeout back to {original}s")

    client.update_function_configuration(
        FunctionName=function_name, Timeout=int(original)
    )

    waiter_for_update(client, function_name)

    print(f"Timeout restored to {original} seconds")


def waiter_for_update(client, function_name):

    max_attempts = 15  # 15 x 2 = ~30 seconds
    attempt = 1

    while attempt <= max_attempts:
        response = client.get_function_configuration(FunctionName=function_name)

        status = response.get("LastUpdateStatus", "Successful")

        print(f"Waiting for Lambda update ({attempt}/{max_attempts}) Status = {status}")

        if status == "Successful":
            return

        if status == "Failed":
            raise RuntimeError(
                response.get("LastUpdateStatusReason", "Lambda update failed.")
            )

        attempt += 1

        time.sleep(2)

    print("WARNING: Lambda update still in progress.")

    print("Continuing without waiting further.")
