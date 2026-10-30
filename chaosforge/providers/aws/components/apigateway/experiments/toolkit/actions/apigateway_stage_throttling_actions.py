import json
import os
import tempfile

import boto3

from chaosforge.interfaces.cli.session import context

STATE_FILE = os.path.join(
    tempfile.gettempdir(),
    "apigateway_stage_throttling_state.json",
)


def get_client(region):
    return boto3.client("apigateway", region_name=region)


def capture_and_update_throttling(
    rest_api_id,
    stage_name,
    region,
    throttle_rate,
    throttle_burst,
):
    #
    # HTTP APIs do not support REST-style stage throttling.
    #
    if getattr(context, "apigateway_protocol", "REST").upper() == "HTTP":
        raise RuntimeError(
            "Stage Throttling Modification is supported only for REST APIs. "
            "The selected API is an HTTP API."
        )

    client = get_client(region)

    stage = client.get_stage(
        restApiId=rest_api_id,
        stageName=stage_name,
    )

    settings = stage.get("methodSettings", {})

    current = settings.get("*/*", {})

    original_rate = current.get("throttlingRateLimit", 10000)
    original_burst = current.get("throttlingBurstLimit", 5000)

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "rest_api_id": rest_api_id,
                "stage_name": stage_name,
                "region": region,
                "rate": original_rate,
                "burst": original_burst,
            },
            fp,
        )

    print(f"Original Rate  : {original_rate}")
    print(f"Original Burst : {original_burst}")

    client.update_stage(
        restApiId=rest_api_id,
        stageName=stage_name,
        patchOperations=[
            {
                "op": "replace",
                "path": "/*/*/throttling/rateLimit",
                "value": str(throttle_rate),
            },
            {
                "op": "replace",
                "path": "/*/*/throttling/burstLimit",
                "value": str(throttle_burst),
            },
        ],
    )

    print(f"Updated Rate  : {throttle_rate}")
    print(f"Updated Burst : {throttle_burst}")


def rollback_throttling():

    if getattr(context, "apigateway_protocol", "REST").upper() == "HTTP":
        print("No rollback required for HTTP API.")
        return

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    print("Restoring original throttling...")

    client.update_stage(
        restApiId=state["rest_api_id"],
        stageName=state["stage_name"],
        patchOperations=[
            {
                "op": "replace",
                "path": "/*/*/throttling/rateLimit",
                "value": str(state["rate"]),
            },
            {
                "op": "replace",
                "path": "/*/*/throttling/burstLimit",
                "value": str(state["burst"]),
            },
        ],
    )

    os.remove(STATE_FILE)

    print("Rollback completed.")
