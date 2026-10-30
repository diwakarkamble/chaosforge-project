import boto3

_original_snapshot_retention = None


def get_cache(client, serverless_cache_name):

    response = client.describe_serverless_caches(
        ServerlessCacheName=serverless_cache_name
    )

    return response["ServerlessCaches"][0]


def capture_snapshot_retention(serverless_cache_name, region):

    global _original_snapshot_retention

    client = boto3.client("elasticache", region_name=region)

    cache = get_cache(client, serverless_cache_name)

    _original_snapshot_retention = cache["SnapshotRetentionLimit"]

    print()
    print("-" * 60)
    print(f"Current Snapshot Retention : {_original_snapshot_retention} day(s)")
    print("-" * 60)


def modify_snapshot_retention(serverless_cache_name, region, snapshot_retention_limit):

    client = boto3.client("elasticache", region_name=region)

    print()
    print("-" * 60)
    print(f"Current Snapshot Retention : {_original_snapshot_retention} day(s)")
    print(f"Target Snapshot Retention  : {snapshot_retention_limit} day(s)")
    print("-" * 60)

    print("\nApplying configuration...\n")

    response = client.modify_serverless_cache(
        ServerlessCacheName=serverless_cache_name,
        SnapshotRetentionLimit=int(snapshot_retention_limit),
    )

    print("✓ Modification request accepted.")
    print(f"Status : {response['ServerlessCache']['Status']}")


def restore_snapshot_retention(serverless_cache_name, region):

    client = boto3.client("elasticache", region_name=region)

    print()
    print("-" * 60)
    print("Restoring Original Configuration")
    print("-" * 60)

    print(f"Original Snapshot Retention : {_original_snapshot_retention} day(s)")

    response = client.modify_serverless_cache(
        ServerlessCacheName=serverless_cache_name,
        SnapshotRetentionLimit=_original_snapshot_retention,
    )

    print("✓ Restore request accepted.")
    print(f"Status : {response['ServerlessCache']['Status']}")

    print()
    print("✔ Snapshot Retention restored successfully.")
