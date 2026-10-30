import json
import os
import tempfile
import time

import boto3

# ----------------------------------------------------------
# ECS Client
# ----------------------------------------------------------


def get_client(region):

    return boto3.client("ecs", region_name=region)


# ----------------------------------------------------------
# Find ECS Service
# ----------------------------------------------------------


def find_service(ecs_service, region, ecs_cluster=None):

    client = get_client(region)

    clusters = [ecs_cluster] if ecs_cluster else client.list_clusters()["clusterArns"]

    for cluster_arn in clusters:
        cluster = cluster_arn.split("/")[-1]

        services = client.list_services(cluster=cluster)["serviceArns"]

        if not services:
            continue

        response = client.describe_services(cluster=cluster, services=services)

        for service in response["services"]:
            if service["serviceName"] == ecs_service:
                return cluster, service

    raise RuntimeError(f"ECS Service '{ecs_service}' not found.")


# ----------------------------------------------------------
# Task Definition
# ----------------------------------------------------------


def describe_task_definition(task_definition, region):

    client = get_client(region)

    response = client.describe_task_definition(taskDefinition=task_definition)

    return response["taskDefinition"]


# ----------------------------------------------------------
# Register Task Definition
# ----------------------------------------------------------


def register_task_definition(task_definition, region):

    client = get_client(region)

    response = client.register_task_definition(
        family=task_definition["family"],
        taskRoleArn=task_definition.get("taskRoleArn"),
        executionRoleArn=task_definition.get("executionRoleArn"),
        networkMode=task_definition["networkMode"],
        containerDefinitions=task_definition["containerDefinitions"],
        volumes=task_definition.get("volumes", []),
        placementConstraints=task_definition.get("placementConstraints", []),
        requiresCompatibilities=task_definition.get("requiresCompatibilities", []),
        cpu=task_definition.get("cpu"),
        memory=task_definition.get("memory"),
        runtimePlatform=task_definition.get("runtimePlatform"),
    )

    return response["taskDefinition"]["taskDefinitionArn"]


# ----------------------------------------------------------
# Update Service
# ----------------------------------------------------------


def update_service(cluster, service, region, **kwargs):

    client = get_client(region)

    client.update_service(cluster=cluster, service=service, **kwargs)


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

    path = os.path.join(tempfile.gettempdir(), f"{experiment_name}.json")

    print(f"STATE FILE : {path}")

    return path


def save_state(experiment_name, data):

    state_file = get_state_file(experiment_name)

    with open(state_file, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)

    print("State saved.")


def load_state(experiment_name):

    state_file = get_state_file(experiment_name)

    if not os.path.exists(state_file):
        raise FileNotFoundError(f"State file not found: {state_file}")

    with open(state_file, encoding="utf-8") as fp:
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


def print_service_summary(service):

    print("\nService Summary")

    print("-" * 60)

    print(f"Service          : {service['serviceName']}")

    print(f"Desired Count    : {service['desiredCount']}")

    print(f"Running Count    : {service['runningCount']}")

    print(f"Task Definition  : {service['taskDefinition']}")

    print()


def get_previous_task_definition(task_definition, region):

    client = get_client(region)

    family = task_definition.split("/")[-1].split(":")[0]

    response = client.list_task_definitions(familyPrefix=family, sort="DESC")

    revisions = response["taskDefinitionArns"]

    if len(revisions) < 2:
        raise RuntimeError("Previous task definition revision not found.")

    return revisions[1]
