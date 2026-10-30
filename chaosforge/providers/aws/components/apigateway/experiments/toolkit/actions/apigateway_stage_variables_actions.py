import json
import os
import tempfile

from .apigateway_common import get_client, get_stage

STATE_FILE = os.path.join(
    tempfile.gettempdir(), "apigateway_stage_variables_state.json"
)


def capture_and_update_stage_variable(
    rest_api_id, stage_name, region, variable_name, variable_value
):

    client = get_client(region)

    stage = get_stage(rest_api_id, stage_name, region)

    variables = stage.get("variables", {})

    print(f"Current Stage Variables : {len(variables)} configured")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "rest_api_id": rest_api_id,
                "stage_name": stage_name,
                "region": region,
                "variables": variables,
            },
            fp,
            indent=2,
        )

    print(f"Updating Stage Variable : {variable_name}")

    client.update_stage(
        restApiId=rest_api_id,
        stageName=stage_name,
        patchOperations=[
            {
                # API Gateway accepts replace as an upsert for stage variables;
                # add fails when the stage has no variables object yet.
                "op": "replace",
                "path": f"/variables/{variable_name}",
                "value": variable_value,
            }
        ],
    )

    print("Stage Variable updated successfully.")


def rollback_stage_variables():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    current = get_stage(state["rest_api_id"], state["stage_name"], state["region"]).get(
        "variables", {}
    )

    original = state["variables"]

    patch = []

    #
    # Restore existing variables
    #

    for key, value in original.items():
        if key in current:
            patch.append({"op": "replace", "path": f"/variables/{key}", "value": value})

        else:
            patch.append({"op": "replace", "path": f"/variables/{key}", "value": value})

    #
    # Remove newly added variables
    #

    for key in current:
        if key not in original:
            patch.append({"op": "remove", "path": f"/variables/{key}"})

    if patch:
        client.update_stage(
            restApiId=state["rest_api_id"],
            stageName=state["stage_name"],
            patchOperations=patch,
        )

    os.remove(STATE_FILE)

    print("Stage Variables restored successfully.")
