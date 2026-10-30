import json
import os
import tempfile
import time

import boto3

from chaosforge.interfaces.cli.session import context


def is_http_api():
    return getattr(context, "apigateway_protocol", "REST").upper() == "HTTP"


# ----------------------------------------------------------
# API Gateway Client
# ----------------------------------------------------------


def get_client(region):

    if is_http_api():
        return boto3.client("apigatewayv2", region_name=region)

    return boto3.client("apigateway", region_name=region)


# ----------------------------------------------------------
# Stage Details
# ----------------------------------------------------------


def get_stage(rest_api_id, stage_name, region):

    client = get_client(region)

    if is_http_api():
        return client.get_stage(
            ApiId=rest_api_id,
            StageName=stage_name,
        )

    return client.get_stage(
        restApiId=rest_api_id,
        stageName=stage_name,
    )


# ----------------------------------------------------------
# Update Stage
# ----------------------------------------------------------


def update_stage(rest_api_id, stage_name, patch_operations, region):

    client = get_client(region)

    print("\nApplying Stage Update...")

    if is_http_api():
        kwargs = {
            "ApiId": rest_api_id,
            "StageName": stage_name,
        }

        if "AccessLogSettings" in patch_operations:
            kwargs["AccessLogSettings"] = patch_operations["AccessLogSettings"]

        if "DefaultRouteSettings" in patch_operations:
            kwargs["DefaultRouteSettings"] = patch_operations["DefaultRouteSettings"]

        client.update_stage(**kwargs)

    else:
        client.update_stage(
            restApiId=rest_api_id,
            stageName=stage_name,
            patchOperations=patch_operations,
        )

    print("Stage updated successfully.")


def apply_patch_operations(rest_api_id, stage_name, patch_operations, region):
    update_stage(
        rest_api_id=rest_api_id,
        stage_name=stage_name,
        patch_operations=patch_operations,
        region=region,
    )


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"\nWaiting for {duration} seconds...")

    time.sleep(duration)


def get_state_file(experiment_name):

    return os.path.join(tempfile.gettempdir(), f"{experiment_name}.json")


def save_state(experiment_name, data):

    with open(get_state_file(experiment_name), "w") as fp:
        json.dump(data, fp, indent=2)


def load_state(experiment_name):

    state_file = get_state_file(experiment_name)

    if not os.path.exists(state_file):
        raise FileNotFoundError("State file not found")

    with open(state_file) as fp:
        return json.load(fp)


def delete_state(experiment_name):

    state = get_state_file(experiment_name)

    if os.path.exists(state):
        os.remove(state)


def print_header(title):
    print("=" * 60)
    print(title)
    print("=" * 60)
    print()


def print_stage_summary(stage):
    print("\nStage Summary")
    print("-" * 60)

    for key, value in stage.items():
        print(f"{key}: {value}")

    print()
