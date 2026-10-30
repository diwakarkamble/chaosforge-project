import json
import os
import tempfile
import time

import boto3

STATE_FILE = os.path.join(
    tempfile.gettempdir(), "elasticache_security_group_actions.json"
)


def get_client(region):
    return boto3.client("elasticache", region_name=region)


def capture_current_security_group(serverless_cache_name, region):

    client = get_client(region)

    response = client.describe_serverless_caches(
        ServerlessCacheName=serverless_cache_name
    )

    cache = response["ServerlessCaches"][0]

    original_sgs = cache["SecurityGroupIds"]

    with open(STATE_FILE, "w") as f:
        json.dump({"original_sgs": original_sgs}, f)

    print(f"Current Security Groups : {original_sgs}")


def update_security_group(serverless_cache_name, region, target_security_group_id=None):

    client = get_client(region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    print("\nCurrent Security Groups:")

    for sg in state["original_sgs"]:
        print(f" - {sg}")

    target_sg = (target_security_group_id or "").strip()
    if not target_sg:
        target_sg = input("\nEnter Temporary Security Group ID: ").strip()
    if not target_sg:
        raise ValueError("Temporary security group ID is required.")

    print(f"\nUpdating Security Group to {target_sg}")

    client.modify_serverless_cache(
        ServerlessCacheName=serverless_cache_name, SecurityGroupIds=[target_sg]
    )

    wait_for_available(client, serverless_cache_name)

    print("Security Group updated.")


def wait_for_duration(wait_seconds):

    print(f"\nWaiting {wait_seconds} seconds...")

    time.sleep(float(wait_seconds))


def restore_security_group(serverless_cache_name, region):

    client = get_client(region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    print(f"\nRestoring Security Groups {state['original_sgs']}")

    client.modify_serverless_cache(
        ServerlessCacheName=serverless_cache_name,
        SecurityGroupIds=state["original_sgs"],
    )

    wait_for_available(client, serverless_cache_name)

    print("Original Security Groups restored.")


def wait_for_available(client, serverless_cache_name):

    while True:
        response = client.describe_serverless_caches(
            ServerlessCacheName=serverless_cache_name
        )

        status = response["ServerlessCaches"][0]["Status"]

        print(f"Current Status : {status}")

        if status.lower() == "available":
            break

        time.sleep(15)
