import json
import os
import tempfile

from .apigateway_common import get_client, get_stage

STATE_FILE = os.path.join(tempfile.gettempdir(), "apigateway_xray_state.json")


def capture_and_update_xray(rest_api_id, stage_name, region, tracing_enabled):

    client = get_client(region)

    stage = get_stage(rest_api_id, stage_name, region)

    original = stage.get("tracingEnabled", False)

    print(f"Original X-Ray Tracing : {original}")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "rest_api_id": rest_api_id,
                "stage_name": stage_name,
                "region": region,
                "original": original,
            },
            fp,
            indent=2,
        )

    value = str(tracing_enabled).lower()

    print(f"Updating X-Ray Tracing to {value}")

    client.update_stage(
        restApiId=rest_api_id,
        stageName=stage_name,
        patchOperations=[{"op": "replace", "path": "/tracingEnabled", "value": value}],
    )

    print("X-Ray Tracing updated successfully.")


def rollback_xray():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    value = str(state["original"]).lower()

    print(f"Restoring X-Ray Tracing to {value}")

    client.update_stage(
        restApiId=state["rest_api_id"],
        stageName=state["stage_name"],
        patchOperations=[{"op": "replace", "path": "/tracingEnabled", "value": value}],
    )

    os.remove(STATE_FILE)

    print("Rollback completed.")
