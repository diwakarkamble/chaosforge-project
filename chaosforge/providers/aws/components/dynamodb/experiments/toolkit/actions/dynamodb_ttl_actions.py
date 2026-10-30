import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "dynamodb_ttl_actions.json")


def get_client(region):
    return boto3.client("dynamodb", region_name=region)


def capture_current_ttl(table_name, region):

    client = get_client(region)

    response = client.describe_time_to_live(TableName=table_name)

    ttl = response["TimeToLiveDescription"]

    original_status = ttl.get("TimeToLiveStatus", "DISABLED")

    attribute_name = ttl.get("AttributeName")

    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "table_name": table_name,
                "original_status": original_status,
                "attribute_name": attribute_name,
            },
            f,
        )

    print(f"Original TTL Status : {original_status}")

    print(f"TTL Attribute       : {attribute_name}")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def disable_ttl(table_name, region):
    with open(STATE_FILE) as f:
        state = json.load(f)

    original_status = state["original_status"]

    if original_status == "DISABLED":
        print("TTL is already disabled.")

        return

    client = get_client(region)

    print(f"Disabling TTL for '{table_name}'")

    client.update_time_to_live(
        TableName=table_name,
        TimeToLiveSpecification={
            "Enabled": False,
            "AttributeName": state["attribute_name"],
        },
    )

    wait_for_ttl_status(client, table_name, "DISABLED")

    print("TTL disabled successfully.")


def restore_ttl(table_name, region):
    with open(STATE_FILE) as f:
        state = json.load(f)

    original_status = state["original_status"]

    if original_status == "DISABLED":
        print("Nothing to restore.")

        return

    client = get_client(region)

    print(f"Restoring TTL for '{table_name}'")

    client.update_time_to_live(
        TableName=table_name,
        TimeToLiveSpecification={
            "Enabled": True,
            "AttributeName": state["attribute_name"],
        },
    )

    wait_for_ttl_status(client, table_name, "ENABLED")

    print("TTL restored successfully.")


def wait_for_ttl_status(client, table_name, expected_status):

    while True:
        response = client.describe_time_to_live(TableName=table_name)

        status = response["TimeToLiveDescription"]["TimeToLiveStatus"]

        print(f"Current TTL Status : {status}")

        if status == expected_status:
            return

        time.sleep(5)
