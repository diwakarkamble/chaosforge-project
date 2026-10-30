import json
import os
import time

import boto3

STATE_DIR = "state"


def get_client(region):
    return boto3.client("dynamodb", region_name=region)


def verify_table(table_name, region):
    client = get_client(region)

    client.describe_table(TableName=table_name)

    print(f"{table_name} exists")

    return True


def get_table_details(table_name, region):

    client = get_client(region)

    response = client.describe_table(TableName=table_name)

    table = response["Table"]

    billing_mode = "PROVISIONED"

    if "BillingModeSummary" in table:
        billing_mode = table["BillingModeSummary"].get("BillingMode", "PROVISIONED")

    return {
        "BillingMode": billing_mode,
        "ProvisionedThroughput": table.get("ProvisionedThroughput", {}),
    }


def wait_until_active(table_name, region):

    client = get_client(region)

    while True:
        status = client.describe_table(TableName=table_name)["Table"]["TableStatus"]

        print(f"Table Status : {status}")

        if status == "ACTIVE":
            return

        time.sleep(5)


def save_capacity(table_name, region):

    details = get_table_details(table_name, region)

    if details["BillingMode"] != "PROVISIONED":
        return

    os.makedirs(STATE_DIR, exist_ok=True)

    state = {
        "BillingMode": details["BillingMode"],
        "ReadCapacityUnits": details["ProvisionedThroughput"]["ReadCapacityUnits"],
        "WriteCapacityUnits": details["ProvisionedThroughput"]["WriteCapacityUnits"],
    }

    with open(f"{STATE_DIR}/{table_name}.json", "w") as f:
        json.dump(state, f, indent=4)


def restore_capacity(table_name, region):

    client = get_client(region)

    with open(f"{STATE_DIR}/{table_name}.json") as f:
        state = json.load(f)

    client.update_table(
        TableName=table_name,
        ProvisionedThroughput={
            "ReadCapacityUnits": state["ReadCapacityUnits"],
            "WriteCapacityUnits": state["WriteCapacityUnits"],
        },
    )

    wait_until_active(table_name, region)

    print("Original capacity restored")
