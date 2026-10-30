import json
import os
import tempfile
import time

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)

STATE_FILE = os.path.join(tempfile.gettempdir(), "rds_backup_retention_actions.json")


def capture_current_backup_retention(db_instance_identifier, region):

    client = get_client(region)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    original_retention = instance["BackupRetentionPeriod"]

    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "db_instance_identifier": db_instance_identifier,
                "original_retention": original_retention,
            },
            f,
        )

    print(f"Original Backup Retention : {original_retention} day(s)")


def modify_backup_retention(db_instance_identifier, region, backup_retention_period):

    client = get_client(region)

    print(f"Updating Backup Retention to {backup_retention_period} day(s)")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        BackupRetentionPeriod=int(backup_retention_period),
        ApplyImmediately=True,
    )

    #
    # Wait until AWS finishes applying the change
    #

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: (
            instance["BackupRetentionPeriod"] == int(backup_retention_period)
        ),
    )

    print("Backup Retention updated successfully.")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def restore_backup_retention(db_instance_identifier, region):

    client = get_client(region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original = state["original_retention"]

    print(f"Restoring Backup Retention to {original} day(s)")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        BackupRetentionPeriod=original,
        ApplyImmediately=True,
    )

    #
    # Wait until restore completes
    #

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance["BackupRetentionPeriod"] == original,
    )

    print("Backup Retention restored successfully.")
