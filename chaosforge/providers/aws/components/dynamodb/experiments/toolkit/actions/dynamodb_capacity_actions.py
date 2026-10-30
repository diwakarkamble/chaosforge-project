import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "dynamodb_capacity_actions.json")


def _client(region):
    return boto3.client("dynamodb", region_name=region)


def capture_current_capacity(table_name, region):
    client = _client(region)

    table = client.describe_table(TableName=table_name)["Table"]

    billing_mode = table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")

    if billing_mode == "PAY_PER_REQUEST":
        print("=" * 58)
        print(" DynamoDB Provisioned Capacity Chaos")
        print("=" * 58)
        print(f"Table Name   : {table_name}")
        print(f"Region       : {region}")
        print(f"Billing Mode : {billing_mode}")
        print()
        print("INFO:")
        print("This table uses PAY_PER_REQUEST (On-Demand).")
        print("Provisioned Capacity Reduction is not applicable.")
        print("No changes will be made.")
        print("=" * 58)

        with open(STATE_FILE, "w") as f:
            json.dump({"skip": True}, f)
        return

    throughput = table["ProvisionedThroughput"]

    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "skip": False,
                "table_name": table_name,
                "read": throughput["ReadCapacityUnits"],
                "write": throughput["WriteCapacityUnits"],
            },
            f,
        )

    print(f"Original RCU : {throughput['ReadCapacityUnits']}")
    print(f"Original WCU : {throughput['WriteCapacityUnits']}")


def wait_for_duration(wait_seconds):
    duration = float(wait_seconds)
    print(f"Sleeping for {duration} seconds...")
    time.sleep(duration)


def update_capacity(table_name, region, target_rcu, target_wcu):
    with open(STATE_FILE) as f:
        state = json.load(f)

    if state.get("skip"):
        print("Skipping capacity update.")
        return

    client = _client(region)

    print(
        f"Updating '{table_name}' "
        f"RCU {state['read']} -> {target_rcu}, "
        f"WCU {state['write']} -> {target_wcu}"
    )

    client.update_table(
        TableName=table_name,
        ProvisionedThroughput={
            "ReadCapacityUnits": int(target_rcu),
            "WriteCapacityUnits": int(target_wcu),
        },
    )

    wait_until_active(client, table_name)
    print("Capacity updated successfully.")


def restore_capacity(table_name, region):
    with open(STATE_FILE) as f:
        state = json.load(f)

    if state.get("skip"):
        print("Nothing to restore.")
        return

    client = _client(region)

    print(f"Restoring capacity to RCU={state['read']} WCU={state['write']}")

    client.update_table(
        TableName=table_name,
        ProvisionedThroughput={
            "ReadCapacityUnits": state["read"],
            "WriteCapacityUnits": state["write"],
        },
    )

    wait_until_active(client, table_name)
    print("Capacity restored successfully.")


def wait_until_active(client, table_name):
    while True:
        status = client.describe_table(TableName=table_name)["Table"]["TableStatus"]

        if status == "ACTIVE":
            return

        print(f"Waiting... Table Status={status}")
        time.sleep(5)
