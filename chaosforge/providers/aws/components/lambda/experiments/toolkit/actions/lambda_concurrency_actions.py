import json
import os
import tempfile
import time

import boto3
from botocore.exceptions import ClientError

STATE_FILE = os.path.join(tempfile.gettempdir(), "lambda_concurrency_actions.json")


def capture_current_concurrency(function_name, region):
    client = boto3.client("lambda", region_name=region)

    state = {
        "function_name": function_name,
        "had_reserved_concurrency": False,
        "original_concurrency": None,
        "original_provisioned": [],
    }

    # Capture Reserved Concurrency
    try:
        response = client.get_function_concurrency(FunctionName=function_name)

        if "ReservedConcurrentExecutions" in response:
            state["had_reserved_concurrency"] = True
            state["original_concurrency"] = response["ReservedConcurrentExecutions"]

    except client.exceptions.ResourceNotFoundException:
        pass

    # Capture Provisioned Concurrency
    try:
        response = client.list_provisioned_concurrency_configs(
            FunctionName=function_name
        )

        for config in response.get("ProvisionedConcurrencyConfigs", []):
            state["original_provisioned"].append(
                {
                    "Qualifier": config["Qualifier"],
                    "Allocated": config["AllocatedProvisionedConcurrentExecutions"],
                }
            )

    except ClientError as e:
        print(f"Warning capturing Provisioned Concurrency: {e}")

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

    if state["had_reserved_concurrency"]:
        print(f"Original Reserved Concurrency: {state['original_concurrency']}")
    else:
        print("Original Reserved Concurrency: UNLIMITED")

    if state["original_provisioned"]:
        print(f"Captured Provisioned Concurrency: {state['original_provisioned']}")

    return state


def update_concurrency(function_name, concurrency_value, region):
    client = boto3.client("lambda", region_name=region)

    target_val = int(concurrency_value)

    with open(STATE_FILE) as f:
        state = json.load(f)

    #
    # STEP 1 - Delete Reserved Concurrency
    #
    try:
        client.delete_function_concurrency(FunctionName=function_name)

        print("Reserved Concurrency deleted. Function is now UNLIMITED.")

    except client.exceptions.ResourceNotFoundException:
        print("Reserved Concurrency already UNLIMITED.")

    #
    # STEP 2 - Delete Provisioned Concurrency
    #
    for prov in state.get("original_provisioned", []):
        qualifier = prov["Qualifier"]

        try:
            print(f"Deleting Provisioned Concurrency for qualifier {qualifier}")

            client.delete_provisioned_concurrency_config(
                FunctionName=function_name, Qualifier=qualifier
            )

        except ClientError as e:
            print(f"Warning deleting Provisioned Concurrency: {e}")

    #
    # STEP 3 - Wait until AWS confirms
    # Provisioned Concurrency is gone
    #
    for prov in state.get("original_provisioned", []):
        qualifier = prov["Qualifier"]

        print(f"Waiting for Provisioned Concurrency deletion on {qualifier}")

        while True:
            try:
                response = client.get_provisioned_concurrency_config(
                    FunctionName=function_name, Qualifier=qualifier
                )

                status = response.get("Status", "UNKNOWN")

                print(
                    f"Provisioned Concurrency "
                    f"still exists for "
                    f"{qualifier}. "
                    f"Status={status}"
                )

                time.sleep(10)

            except client.exceptions.ProvisionedConcurrencyConfigNotFoundException:
                print(f"Provisioned Concurrency fully deleted for {qualifier}")

                break

    #
    # STEP 4 - Verify remaining provisioned concurrency
    #
    total_provisioned = 0

    try:
        response = client.list_provisioned_concurrency_configs(
            FunctionName=function_name
        )

        for config in response.get("ProvisionedConcurrencyConfigs", []):
            total_provisioned += config["AllocatedProvisionedConcurrentExecutions"]

    except ClientError as e:
        print(f"Warning capturing Provisioned Concurrency: {e}")

    print(f"Remaining Provisioned Concurrency: {total_provisioned}")

    if total_provisioned > target_val:
        raise RuntimeError(
            f"Cannot set Reserved Concurrency "
            f"to {target_val}. "
            f"Provisioned Concurrency still "
            f"exists: {total_provisioned}"
        )

    #
    # STEP 5 - Apply chaos value
    #
    client.put_function_concurrency(
        FunctionName=function_name, ReservedConcurrentExecutions=target_val
    )

    print(f"Reserved Concurrency changed to {target_val}")

    return {"new_concurrency": target_val}


def wait_for_duration(wait_seconds):
    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)

    print("Wait completed.")

    return {"waited_seconds": duration}


def restore_concurrency(function_name, region):
    client = boto3.client("lambda", region_name=region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    #
    # Restore Reserved Concurrency
    #
    if state["had_reserved_concurrency"]:
        client.put_function_concurrency(
            FunctionName=function_name,
            ReservedConcurrentExecutions=int(state["original_concurrency"]),
        )

        print(f"Restored Reserved Concurrency to {state['original_concurrency']}")

    else:
        client.delete_function_concurrency(FunctionName=function_name)

        print("Restored UNLIMITED concurrency")

    #
    # Restore Provisioned Concurrency
    #
    for prov in state.get("original_provisioned", []):
        try:
            print(
                f"Restoring Provisioned "
                f"Concurrency {prov['Allocated']} "
                f"for qualifier "
                f"{prov['Qualifier']}"
            )

            client.put_provisioned_concurrency_config(
                FunctionName=function_name,
                Qualifier=prov["Qualifier"],
                ProvisionedConcurrentExecutions=prov["Allocated"],
            )

        except ClientError as e:
            print(f"Failed restoring Provisioned Concurrency: {e!s}")

    return True
