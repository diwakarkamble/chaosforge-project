import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "dynamodb_stream_actions.json")


def get_client(region):
    return boto3.client("dynamodb", region_name=region)


def capture_current_stream(table_name, region):

    client = get_client(region)

    table = client.describe_table(TableName=table_name)["Table"]

    stream_spec = table.get("StreamSpecification", {})

    state = {
        "stream_enabled": stream_spec.get("StreamEnabled", False),
        "stream_view_type": stream_spec.get("StreamViewType"),
    }

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

    print(f"Current Stream Enabled : {state['stream_enabled']}")

    if state["stream_enabled"]:
        print(f"Current Stream View Type : {state['stream_view_type']}")


def disable_stream(table_name, region):

    with open(STATE_FILE) as f:
        state = json.load(f)

    if not state["stream_enabled"]:
        print("Streams are already disabled.")
        return

    client = get_client(region)

    print("Disabling DynamoDB Streams...")

    client.update_table(
        TableName=table_name, StreamSpecification={"StreamEnabled": False}
    )

    wait_until_active(client, table_name)

    print("Streams disabled successfully.")


def restore_stream(table_name, region):

    with open(STATE_FILE) as f:
        state = json.load(f)

    if not state["stream_enabled"]:
        print("Nothing to restore.")
        return

    client = get_client(region)

    print("Restoring DynamoDB Streams...")

    client.update_table(
        TableName=table_name,
        StreamSpecification={
            "StreamEnabled": True,
            "StreamViewType": state["stream_view_type"],
        },
    )

    wait_until_active(client, table_name)

    print("Streams restored successfully.")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def wait_until_active(client, table_name):

    while True:
        response = client.describe_table(TableName=table_name)

        status = response["Table"]["TableStatus"]

        if status == "ACTIVE":
            return

        print(f"Waiting... Table Status = {status}")

        time.sleep(5)
