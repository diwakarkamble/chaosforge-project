import json
import os
import tempfile
import time

import boto3

# ----------------------------------------------------------
# EC2 Client
# ----------------------------------------------------------


def get_client(region):
    return boto3.client("ec2", region_name=region)


# ----------------------------------------------------------
# Describe Instance
# ----------------------------------------------------------


def describe_instance(instance_id, region):

    client = get_client(region)

    response = client.describe_instances(InstanceIds=[instance_id])

    reservations = response.get("Reservations", [])

    if not reservations:
        raise RuntimeError(f"EC2 Instance '{instance_id}' not found.")

    instances = reservations[0].get("Instances", [])

    if not instances:
        raise RuntimeError(f"EC2 Instance '{instance_id}' not found.")

    return instances[0]


# ----------------------------------------------------------
# Instance State
# ----------------------------------------------------------


def get_instance_state(instance_id, region):

    instance = describe_instance(
        instance_id,
        region,
    )

    return instance["State"]["Name"]


# ----------------------------------------------------------
# Wait
# ----------------------------------------------------------


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"\nWaiting for {duration} seconds...")

    time.sleep(duration)


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


# ----------------------------------------------------------
# Console
# ----------------------------------------------------------


def print_header(title):

    print("=" * 60)

    print(title)

    print("=" * 60)

    print()


def print_instance_summary(instance):

    print("\nEC2 Instance Summary")

    print("-" * 60)

    print(f"Instance ID     : {instance['InstanceId']}")

    print(f"Instance Type   : {instance.get('InstanceType', '-')}")

    print(f"State           : {instance['State']['Name']}")

    print(
        f"Availability Zone: "
        f"{instance.get('Placement', {}).get('AvailabilityZone', '-')}"
    )

    print()


# ----------------------------------------------------------
# EBS Volume
# ----------------------------------------------------------


def describe_volume(volume_id, region):

    client = get_client(region)

    response = client.describe_volumes(VolumeIds=[volume_id])

    volumes = response.get("Volumes", [])

    if not volumes:
        raise RuntimeError(f"EBS volume '{volume_id}' not found.")

    return volumes[0]


# ----------------------------------------------------------
# Root Device
# ----------------------------------------------------------


def get_root_device(instance_id, region):

    instance = describe_instance(
        instance_id,
        region,
    )

    return instance.get("RootDeviceName")


def wait_for_seconds(seconds):

    time.sleep(float(seconds))
