import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "lambda_memory_state.json")


def capture_current_memory(function_name, region):
    client = boto3.client("lambda", region_name=region)

    config = client.get_function_configuration(FunctionName=function_name)

    original_memory = config["MemorySize"]

    with open(STATE_FILE, "w") as f:
        json.dump(
            {"function_name": function_name, "original_memory": original_memory}, f
        )

    print(f"Original memory: {original_memory} MB")


def wait_for_duration(wait_seconds):
    # Safely convert the string "20" from the CLI into a float/integer
    duration = float(wait_seconds)
    print(f"Sleeping for {duration} seconds...")
    time.sleep(duration)


def update_memory(function_name, memory_size, region):
    client = boto3.client("lambda", region_name=region)

    client.update_function_configuration(
        FunctionName=function_name, MemorySize=int(memory_size)
    )

    waiter_for_update(client, function_name)

    print(f"Memory updated to {memory_size} MB")


def restore_memory(function_name, region):
    client = boto3.client("lambda", region_name=region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original = state["original_memory"]

    client.update_function_configuration(
        FunctionName=function_name, MemorySize=int(original)
    )

    waiter_for_update(client, function_name)

    print(f"Memory restored to {original} MB")


def waiter_for_update(client, function_name):
    import time

    while True:
        response = client.get_function_configuration(FunctionName=function_name)

        status = response.get("LastUpdateStatus", "Successful")

        if status == "Successful":
            return

        if status == "Failed":
            raise RuntimeError(
                f"Lambda update failed: {response.get('LastUpdateStatusReason')}"
            )

        time.sleep(5)
