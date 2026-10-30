import json
import os
import tempfile
import time

import boto3

# ----------------------------------------------------------
# ELBv2 Client
# ----------------------------------------------------------


def get_client(region):
    return boto3.client(
        "elbv2",
        region_name=region,
    )


# ----------------------------------------------------------
# Target Registration
# ----------------------------------------------------------


def get_target_registration(
    target_group_arn,
    target_id,
    region,
):
    client = get_client(region)

    response = client.describe_target_health(
        TargetGroupArn=target_group_arn,
        Targets=[
            {
                "Id": target_id,
            }
        ],
    )

    descriptions = response.get(
        "TargetHealthDescriptions",
        [],
    )

    if not descriptions:
        raise RuntimeError(
            f"ELB target '{target_id}' not found in target group '{target_group_arn}'."
        )

    target = descriptions[0].get(
        "Target",
        {},
    )

    if not target.get("Id"):
        raise RuntimeError(f"ELB target '{target_id}' has no target registration.")

    return {
        "target_group_arn": target_group_arn,
        "target_id": target["Id"],
        "port": target.get("Port"),
    }


# ----------------------------------------------------------
# Wait
# ----------------------------------------------------------


def wait_for_seconds(seconds):
    time.sleep(float(seconds))


# ----------------------------------------------------------
# State File
# ----------------------------------------------------------


def get_state_file(experiment_name):

    path = os.path.join(
        tempfile.gettempdir(),
        f"{experiment_name}.json",
    )

    print(f"STATE FILE : {path}")

    return path


def save_state(experiment_name, data):

    state_file = get_state_file(experiment_name)

    with open(
        state_file,
        "w",
        encoding="utf-8",
    ) as fp:
        json.dump(
            data,
            fp,
            indent=2,
        )

    print("State saved.")


def load_state(experiment_name):

    state_file = get_state_file(experiment_name)

    if not os.path.exists(state_file):
        raise FileNotFoundError(f"State file not found: {state_file}")

    with open(
        state_file,
        encoding="utf-8",
    ) as fp:
        return json.load(fp)


def delete_state(experiment_name):

    state_file = get_state_file(experiment_name)

    if os.path.exists(state_file):
        os.remove(state_file)

        print("State deleted.")
