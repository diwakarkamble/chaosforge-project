import json
import os
import tempfile
import time

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)

STATE_FILE = os.path.join(tempfile.gettempdir(), "rds_storage_autoscaling_state.json")


def capture_and_reduce_max_allocated_storage(
    db_instance_identifier, region, threshold_percent
):

    client = get_client(region)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    original_max_storage = instance.get("MaxAllocatedStorage")

    if original_max_storage is None:
        raise ValueError("Storage Autoscaling is not enabled on this RDS instance.")

    allocated_storage = instance["AllocatedStorage"]

    target_storage = int(original_max_storage * int(threshold_percent) / 100)

    #
    # AWS requires:
    # MaxAllocatedStorage >= AllocatedStorage
    #

    target_storage = max(target_storage, allocated_storage)

    print(f"Allocated Storage   : {allocated_storage} GB")

    print(f"Current Max Storage : {original_max_storage} GB")

    print(f"Target Max Storage  : {target_storage} GB")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "db_instance_identifier": db_instance_identifier,
                "region": region,
                "original_max_storage": original_max_storage,
            },
            fp,
        )

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        MaxAllocatedStorage=target_storage,
        ApplyImmediately=True,
    )

    #
    # Wait until MaxAllocatedStorage changes
    #

    wait_for_max_allocated_storage(client, db_instance_identifier, target_storage)

    print("Storage Autoscaling modification completed.")


def wait_for_max_allocated_storage(client, db_instance_identifier, expected_value):
    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance.get("MaxAllocatedStorage") == expected_value,
    )


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def rollback_max_allocated_storage():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    print(f"Restoring MaxAllocatedStorage to {state['original_max_storage']} GB")

    client.modify_db_instance(
        DBInstanceIdentifier=state["db_instance_identifier"],
        MaxAllocatedStorage=state["original_max_storage"],
        ApplyImmediately=True,
    )

    #
    # Wait until original value is restored
    #

    wait_for_max_allocated_storage(
        client, state["db_instance_identifier"], state["original_max_storage"]
    )

    os.remove(STATE_FILE)

    print("Rollback completed.")
