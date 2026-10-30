import json
import os
import tempfile

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)

STATE_FILE = os.path.join(tempfile.gettempdir(), "rds_parameter_group_state.json")


def capture_and_change_parameter_group(
    db_instance_identifier, region, chaos_parameter_group
):

    client = get_client(region)

    response = client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)

    instance = response["DBInstances"][0]

    current_parameter_group = instance["DBParameterGroups"][0]["DBParameterGroupName"]

    print(f"Current Parameter Group : {current_parameter_group}")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "db_instance_identifier": db_instance_identifier,
                "region": region,
                "original_parameter_group": current_parameter_group,
            },
            fp,
        )

    print(f"Switching to {chaos_parameter_group}")

    client.modify_db_instance(
        DBInstanceIdentifier=db_instance_identifier,
        DBParameterGroupName=chaos_parameter_group,
        ApplyImmediately=True,
    )

    #
    # Wait until AWS completes the modification
    #

    wait_for_db_available(
        client,
        db_instance_identifier,
        expected_instance=lambda instance: (
            instance["DBParameterGroups"][0]["DBParameterGroupName"]
            == chaos_parameter_group
        ),
    )

    print("Parameter Group modification completed.")


def wait_for_duration(wait_seconds):

    import time

    duration = float(wait_seconds)

    print(f"Sleeping for {duration} seconds...")

    time.sleep(duration)


def rollback_parameter_group():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    print(f"Restoring Parameter Group : {state['original_parameter_group']}")

    client.modify_db_instance(
        DBInstanceIdentifier=state["db_instance_identifier"],
        DBParameterGroupName=state["original_parameter_group"],
        ApplyImmediately=True,
    )

    #
    # Wait until restore completes
    #

    wait_for_db_available(
        client,
        state["db_instance_identifier"],
        expected_instance=lambda instance: (
            instance["DBParameterGroups"][0]["DBParameterGroupName"]
            == state["original_parameter_group"]
        ),
    )

    os.remove(STATE_FILE)

    print("Rollback completed.")
