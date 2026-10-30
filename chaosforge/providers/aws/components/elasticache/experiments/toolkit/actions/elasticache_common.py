import time

import boto3


def get_client(region):
    return boto3.client(
        "elasticache",
        region_name=region,
    )


def wait_for_duration(wait_seconds):
    duration = float(wait_seconds)
    print(f"Waiting for {duration} seconds...")
    time.sleep(duration)
    print("Wait completed.")


def wait_for_serverless_cache_available(
    client,
    serverless_cache_name,
):

    while True:
        response = client.describe_serverless_caches(
            ServerlessCacheName=serverless_cache_name
        )

        status = response["ServerlessCaches"][0]["Status"]

        print(f"Current Status : {status}")

        if status.lower() == "available":
            return

        time.sleep(15)
