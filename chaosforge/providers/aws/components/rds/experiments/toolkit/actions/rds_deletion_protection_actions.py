import json
import os
import tempfile
import time

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)

STATE_FILE = os.path.join(tempfile.gettempdir(), "rds_deletion_protection_actions.json")


def capture_current_deletion_protection(db_instance_identifier, region):

    client = get_client(region)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    original_value = instance["DeletionProtection"]

    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "db_instance_identifier": db_instance_identifier,
                "original_value": original_value,
            },
            f,
        )

    print(f"Original Deletion Protection : {original_value}")


def wait_for_deletion_protection(client, db_instance_identifier, expected_value):
    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance["DeletionProtection"] == expected_value,
    )


def update_deletion_protection(db_instance_identifier, region, deletion_protection):

    client = get_client(region)

    value = str(deletion_protection).lower() == "true"
    current = client.describe_db_instances(
        DBInstanceIdentifier=db_instance_identifier
    )["DBInstances"][0]["DeletionProtection"]
    if current == value:
        raise ValueError(
            "Target Deletion Protection already matches the requested value."
        )

    print(f"Updating Deletion Protection to {value}")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        DeletionProtection=value,
        ApplyImmediately=True,
    )

    wait_for_deletion_protection(client, db_instance_identifier, value)

    print("Deletion Protection updated successfully.")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def restore_deletion_protection(db_instance_identifier, region):

    client = get_client(region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original = state["original_value"]

    print(f"Restoring Deletion Protection to {original}")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        DeletionProtection=original,
        ApplyImmediately=True,
    )

    wait_for_deletion_protection(client, db_instance_identifier, original)

    print("Deletion Protection restored successfully.")
