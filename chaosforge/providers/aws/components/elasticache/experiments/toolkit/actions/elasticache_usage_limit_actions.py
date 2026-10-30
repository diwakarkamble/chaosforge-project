import json
import os
import tempfile

from .elasticache_common import get_client, wait_for_serverless_cache_available

STATE_FILE = os.path.join(tempfile.gettempdir(), "elasticache_usage_limit_state.json")


def capture_and_modify_usage_limit(serverless_cache_name, usage_type, maximum, region):

    client = get_client(region)

    response = client.describe_serverless_caches(
        ServerlessCacheName=serverless_cache_name
    )

    cache = response["ServerlessCaches"][0]

    usage_limits = cache.get("CacheUsageLimits", {})

    original = usage_limits.get(usage_type)

    if original is None:
        raise ValueError(f"{usage_type} usage limit not configured.")

    print(f"Current {usage_type} Usage Limit : {original}")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "serverless_cache_name": serverless_cache_name,
                "region": region,
                "usage_type": usage_type,
                "original": original,
            },
            fp,
            indent=2,
        )

    usage_limits[usage_type] = {"Maximum": int(maximum)}

    client.modify_serverless_cache(
        ServerlessCacheName=serverless_cache_name, CacheUsageLimits=usage_limits
    )

    wait_for_serverless_cache_available(client, serverless_cache_name)

    print("Usage limit updated successfully.")


def rollback_usage_limit():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    response = client.describe_serverless_caches(
        ServerlessCacheName=state["serverless_cache_name"]
    )

    cache = response["ServerlessCaches"][0]

    usage_limits = cache["CacheUsageLimits"]

    usage_limits[state["usage_type"]] = state["original"]

    client.modify_serverless_cache(
        ServerlessCacheName=state["serverless_cache_name"],
        CacheUsageLimits=usage_limits,
    )

    wait_for_serverless_cache_available(client, state["serverless_cache_name"])

    os.remove(STATE_FILE)

    print("Usage limit restored successfully.")
