import json
import os
import tempfile

from .elasticache_common import get_client, wait_for_serverless_cache_available

STATE_FILE = os.path.join(
    tempfile.gettempdir(), "elasticache_daily_snapshot_state.json"
)


def capture_and_modify_daily_snapshot(
    serverless_cache_name, daily_snapshot_time, region
):

    client = get_client(region)

    response = client.describe_serverless_caches(
        ServerlessCacheName=serverless_cache_name
    )

    cache = response["ServerlessCaches"][0]

    original = cache.get("DailySnapshotTime")

    print(f"Current Snapshot Time : {original}")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "serverless_cache_name": serverless_cache_name,
                "region": region,
                "original": original,
            },
            fp,
            indent=2,
        )

    client.modify_serverless_cache(
        ServerlessCacheName=serverless_cache_name, DailySnapshotTime=daily_snapshot_time
    )

    wait_for_serverless_cache_available(client, serverless_cache_name)

    print("Daily Snapshot updated successfully.")


def rollback_daily_snapshot():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    client.modify_serverless_cache(
        ServerlessCacheName=state["serverless_cache_name"],
        DailySnapshotTime=state["original"],
    )

    wait_for_serverless_cache_available(client, state["serverless_cache_name"])

    os.remove(STATE_FILE)

    print("Daily Snapshot restored successfully.")
