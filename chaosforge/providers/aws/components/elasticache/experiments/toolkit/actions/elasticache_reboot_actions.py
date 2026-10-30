import boto3


def reboot_cache_cluster(cache_cluster_id, region):

    client = boto3.client("elasticache", region_name=region)

    print(f"Rebooting {cache_cluster_id}...")

    client.reboot_cache_cluster(
        CacheClusterId=cache_cluster_id, CacheNodeIdsToReboot=["0001"]
    )

    print("Waiting for the cache cluster to become available...")
    client.get_waiter("cache_cluster_available").wait(
        CacheClusterId=cache_cluster_id,
        WaiterConfig={"Delay": 15, "MaxAttempts": 40},
    )

    print("Reboot completed and cache cluster is available.")
