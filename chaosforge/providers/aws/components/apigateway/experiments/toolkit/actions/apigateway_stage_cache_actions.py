from .apigateway_common import (
    delete_state,
    get_stage,
    load_state,
    save_state,
    update_stage,
)

STATE_NAME = "apigateway_stage_cache"


# ----------------------------------------------------------
# Capture Current Cache Configuration
# ----------------------------------------------------------


def capture_current_stage_cache(rest_api_id, stage_name, region):

    stage = get_stage(rest_api_id, stage_name, region)

    cache_enabled = stage.get("cacheClusterEnabled", False)

    save_state(
        STATE_NAME,
        {
            "rest_api_id": rest_api_id,
            "stage_name": stage_name,
            "region": region,
            "cache_enabled": cache_enabled,
        },
    )

    print(f"Original Cache Status : {cache_enabled}")


# ----------------------------------------------------------
# Update Cache
# ----------------------------------------------------------


def update_stage_cache(rest_api_id, stage_name, region, cache_enabled):

    value = str(cache_enabled).lower()

    print(f"Updating Cache Status to {value}")

    patch_operations = [
        {"op": "replace", "path": "/cacheClusterEnabled", "value": value}
    ]

    update_stage(rest_api_id, stage_name, patch_operations, region)

    print("Stage Cache updated successfully.")


# ----------------------------------------------------------
# Restore Cache
# ----------------------------------------------------------


def restore_stage_cache():

    state = load_state(STATE_NAME)

    value = str(state["cache_enabled"]).lower()

    print(f"Restoring Cache Status to {value}")

    patch_operations = [
        {"op": "replace", "path": "/cacheClusterEnabled", "value": value}
    ]

    update_stage(
        state["rest_api_id"], state["stage_name"], patch_operations, state["region"]
    )

    delete_state(STATE_NAME)

    print("Cache restored successfully.")
