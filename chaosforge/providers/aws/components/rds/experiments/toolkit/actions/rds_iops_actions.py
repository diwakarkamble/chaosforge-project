import json
import os
import tempfile

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)

STATE_FILE = os.path.join(tempfile.gettempdir(), "rds_iops_state.json")


def capture_and_reduce_iops(db_instance_identifier, region, threshold_percent):

    client = get_client(region)

    # A failed preflight must not let a prior run's journal trigger a rollback.
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    storage_type = instance["StorageType"]

    if storage_type not in ["io1", "io2", "gp3"]:
        raise ValueError(
            f"Storage type '{storage_type}' "
            "does not support Provisioned "
            "IOPS modification."
        )

    original_iops = instance["Iops"]

    if original_iops <= 1000:
        raise ValueError(
            f"Current IOPS is {original_iops}. "
            "Provisioned IOPS cannot be reduced "
            "below 1000."
        )

    target_iops = max(1000, int(original_iops * int(threshold_percent) / 100))

    if target_iops >= original_iops:
        raise ValueError(
            f"Target IOPS ({target_iops}) "
            f"must be lower than current "
            f"IOPS ({original_iops})."
        )

    allocated_storage = instance["AllocatedStorage"]

    print(f"Original IOPS : {original_iops}")

    print(f"Target IOPS   : {target_iops}")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "db_instance_identifier": db_instance_identifier,
                "region": region,
                "original_iops": original_iops,
                "allocated_storage": allocated_storage,
            },
            fp,
        )

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        AllocatedStorage=allocated_storage,
        Iops=target_iops,
        ApplyImmediately=True,
    )

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance["Iops"] == target_iops,
    )

    print("IOPS modification completed.")


def wait_for_duration(wait_seconds):

    import time

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def rollback_iops():

    if not os.path.exists(STATE_FILE):
        print("IOPS was not changed; rollback skipped.")
        return

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])
    allocated_storage = state.get("allocated_storage")
    if allocated_storage is None:
        # Journals written before AllocatedStorage was captured remain recoverable.
        instance = client.describe_db_instances(
            DBInstanceIdentifier=state["db_instance_identifier"]
        )["DBInstances"][0]
        allocated_storage = instance["AllocatedStorage"]

    print(f"Rolling back to {state['original_iops']} IOPS...")

    client.modify_db_instance(
        DBInstanceIdentifier=state["db_instance_identifier"],
        AllocatedStorage=allocated_storage,
        Iops=state["original_iops"],
        ApplyImmediately=True,
    )

    wait_for_db_available(
        client,
        state["db_instance_identifier"],
        expected_instance=lambda instance: instance["Iops"] == state["original_iops"],
    )

    os.remove(STATE_FILE)

    print("Rollback completed.")
