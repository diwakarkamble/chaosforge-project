import json
import os
import tempfile
import time

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)

STATE_FILE = os.path.join(
    tempfile.gettempdir(), "rds_auto_minor_version_upgrade_actions.json"
)


def capture_current_auto_minor_upgrade(db_instance_identifier, region):

    client = get_client(region)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    original_value = instance["AutoMinorVersionUpgrade"]

    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "db_instance_identifier": db_instance_identifier,
                "original_value": original_value,
            },
            f,
        )

    print(f"Original Auto Minor Version Upgrade : {original_value}")


def update_auto_minor_upgrade(
    db_instance_identifier, region, auto_minor_version_upgrade
):

    client = get_client(region)

    value = str(auto_minor_version_upgrade).lower() == "true"
    current = client.describe_db_instances(
        DBInstanceIdentifier=db_instance_identifier
    )["DBInstances"][0]["AutoMinorVersionUpgrade"]
    if current == value:
        raise ValueError(
            "Target Auto Minor Version Upgrade already matches the current value "
            f"({current}). Choose {not current} to apply the fault."
        )

    print(f"Updating Auto Minor Version Upgrade to {value}")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        AutoMinorVersionUpgrade=value,
        ApplyImmediately=True,
    )

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance["AutoMinorVersionUpgrade"] == value,
    )

    print("Auto Minor Version Upgrade updated successfully.")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def restore_auto_minor_upgrade(db_instance_identifier, region):

    client = get_client(region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original = state["original_value"]

    current = client.describe_db_instances(
        DBInstanceIdentifier=db_instance_identifier
    )["DBInstances"][0]["AutoMinorVersionUpgrade"]
    if current == original:
        print("Auto Minor Version Upgrade was not changed; rollback skipped.")
        return

    print(f"Restoring Auto Minor Version Upgrade to {original}")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        AutoMinorVersionUpgrade=original,
        ApplyImmediately=True,
    )

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance["AutoMinorVersionUpgrade"] == original,
    )

    print("Auto Minor Version Upgrade restored successfully.")
