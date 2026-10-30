import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "dynamodb_pitr_actions.json")


def get_client(region):
    return boto3.client("dynamodb", region_name=region)


def capture_current_pitr(table_name, region):

    client = get_client(region)

    response = client.describe_continuous_backups(TableName=table_name)

    description = response["ContinuousBackupsDescription"]

    pitr = description["PointInTimeRecoveryDescription"]

    status = pitr["PointInTimeRecoveryStatus"]

    with open(STATE_FILE, "w") as f:
        json.dump({"table_name": table_name, "original_status": status}, f)

    print(f"Original PITR Status : {status}")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def disable_pitr(table_name, region):
    with open(STATE_FILE) as f:
        state = json.load(f)

    if state["original_status"] == "DISABLED":
        print("PITR is already disabled.")

        return

    client = get_client(region)

    print(f"Disabling PITR for '{table_name}'")

    client.update_continuous_backups(
        TableName=table_name,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": False},
    )

    wait_for_pitr_status(client, table_name, "DISABLED")

    print("PITR disabled successfully.")


def restore_pitr(table_name, region):
    with open(STATE_FILE) as f:
        state = json.load(f)

    if state["original_status"] == "DISABLED":
        print("Nothing to restore.")

        return

    client = get_client(region)

    print(f"Restoring PITR for '{table_name}'")

    client.update_continuous_backups(
        TableName=table_name,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
    )

    wait_for_pitr_status(client, table_name, "ENABLED")

    print("PITR restored successfully.")


def wait_for_pitr_status(client, table_name, expected_status):

    while True:
        response = client.describe_continuous_backups(TableName=table_name)

        status = response["ContinuousBackupsDescription"][
            "PointInTimeRecoveryDescription"
        ]["PointInTimeRecoveryStatus"]

        print(f"Current PITR Status : {status}")

        if status == expected_status:
            return

        time.sleep(5)
