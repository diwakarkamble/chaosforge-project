import json
import os
import tempfile
import time

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)

STATE_FILE = os.path.join(tempfile.gettempdir(), "rds_instance_class_actions.json")


def capture_current_instance_class(db_instance_identifier, region):

    client = get_client(region)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    original_class = instance["DBInstanceClass"]

    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "db_instance_identifier": db_instance_identifier,
                "original_class": original_class,
            },
            f,
        )

    print(f"Original Instance Class : {original_class}")


def update_instance_class(db_instance_identifier, region, target_instance_class=None):

    client = get_client(region)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    current_class = instance["DBInstanceClass"]

    print(f"\nCurrent Instance Class : {current_class}")

    print("\nFetching supported instance classes...\n")

    response = client.describe_valid_db_instance_modifications(
        DBInstanceIdentifier=db_instance_identifier
    )

    modifications = response.get("ValidDBInstanceModificationsMessage", {}).get(
        "ValidDBInstanceModifications", []
    )
    all_classes = sorted(
        {
            value
            for modification in modifications
            for value in modification.get("ValidDBInstanceClasses", [])
        }
    )

    if not all_classes:
        raise ValueError(
            "AWS did not return any valid instance class modifications for "
            f"RDS instance '{db_instance_identifier}'."
        )

    family = ".".join(current_class.split(".")[:2])

    same_family = [
        value
        for value in all_classes
        if value.startswith(family) and value != current_class
    ]

    if same_family:
        classes = same_family

        print("Available classes (same family):\n")

    else:
        classes = [value for value in all_classes if value != current_class]

        print("Available classes:\n")

    if target_instance_class:
        if target_instance_class not in classes:
            available = ", ".join(classes) or "none"
            raise ValueError(
                f"Target instance class '{target_instance_class}' is not a valid "
                f"modification for RDS instance '{db_instance_identifier}'. "
                f"Valid target classes: {available}."
            )
        target_class = target_instance_class
    else:
        for index, value in enumerate(classes, start=1):
            print(f"{index}. {value}")

        while True:
            choice = input("\nSelect instance class number: ")
            try:
                choice = int(choice)
                if 1 <= choice <= len(classes):
                    break
            except ValueError:
                pass
            print("Invalid selection.")
        target_class = classes[choice - 1]

    print(f"\nUpdating Instance Class to {target_class}")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        DBInstanceClass=target_class,
        ApplyImmediately=True,
    )

    #
    # Wait until AWS completes the modification
    #

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance["DBInstanceClass"] == target_class,
    )

    print("Instance Class updated successfully.")


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def restore_instance_class(db_instance_identifier, region):

    client = get_client(region)

    with open(STATE_FILE) as f:
        state = json.load(f)

    original = state["original_class"]

    current = client.describe_db_instances(
        DBInstanceIdentifier=db_instance_identifier
    )["DBInstances"][0]["DBInstanceClass"]
    if current == original:
        print("Instance Class was not changed; rollback skipped.")
        return

    print(f"Restoring Instance Class to {original}")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        DBInstanceClass=original,
        ApplyImmediately=True,
    )

    #
    # Wait until restore completes
    #

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: instance["DBInstanceClass"] == original,
    )

    print("Instance Class restored successfully.")
