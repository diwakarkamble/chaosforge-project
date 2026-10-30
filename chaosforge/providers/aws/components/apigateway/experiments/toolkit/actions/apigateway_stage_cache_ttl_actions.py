import json
import os
import tempfile

from .apigateway_common import get_client, get_stage

STATE_FILE = os.path.join(
    tempfile.gettempdir(), "apigateway_stage_cache_ttl_state.json"
)


def capture_and_modify_cache_ttl(rest_api_id, stage_name, region, cache_ttl):

    client = get_client(region)

    stage = get_stage(rest_api_id, stage_name, region)

    original_ttl = stage.get("cacheClusterSettings", {}).get("cacheTtlInSeconds", 300)

    print(f"Original Cache TTL : {original_ttl}")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "rest_api_id": rest_api_id,
                "stage_name": stage_name,
                "region": region,
                "original_ttl": original_ttl,
            },
            fp,
        )

    print(f"Updating Cache TTL to {cache_ttl}")

    client.update_stage(
        restApiId=rest_api_id,
        stageName=stage_name,
        patchOperations=[
            {
                "op": "replace",
                "path": "/*/*/caching/ttlInSeconds",
                "value": str(cache_ttl),
            }
        ],
    )

    print("Cache TTL updated successfully.")


def rollback_cache_ttl():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    print(f"Restoring Cache TTL to {state['original_ttl']}")

    client.update_stage(
        restApiId=state["rest_api_id"],
        stageName=state["stage_name"],
        patchOperations=[
            {
                "op": "replace",
                "path": "/*/*/caching/ttlInSeconds",
                "value": str(state["original_ttl"]),
            }
        ],
    )

    os.remove(STATE_FILE)

    print("Rollback completed.")
