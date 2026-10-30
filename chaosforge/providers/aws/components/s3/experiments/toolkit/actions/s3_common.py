import json
import os
import tempfile
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# ============================================================
# S3 Client
# ============================================================


def get_client(region):
    return boto3.client("s3", region_name=region)


# ============================================================
# State File Helpers
# ============================================================


def _state_file(experiment_name, bucket_name=""):

    suffix = ""
    if bucket_name:
        safe_bucket = "".join(
            character if character.isalnum() or character in ".-" else "-"
            for character in str(bucket_name)
        )
        suffix = f"-{safe_bucket}"

    return os.path.join(tempfile.gettempdir(), f"{experiment_name}{suffix}.json")


def save_state(experiment_name, state, bucket_name=""):

    state["timestamp"] = datetime.now(timezone.utc).isoformat()

    filename = _state_file(experiment_name, bucket_name)

    with open(filename, "w", encoding="utf-8") as fp:
        json.dump(state, fp, indent=4)

    print(f"STATE FILE : {filename}")
    print("State saved.")


def load_state(experiment_name, bucket_name=""):

    filename = _state_file(experiment_name, bucket_name)

    if not os.path.exists(filename):
        raise RuntimeError(f"State file not found : {filename}")

    with open(filename, "r", encoding="utf-8") as fp:
        state = json.load(fp)

    print(f"STATE FILE : {filename}")

    return state


def delete_state(experiment_name, bucket_name=""):

    filename = _state_file(experiment_name, bucket_name)

    if os.path.exists(filename):
        os.remove(filename)

        print(f"STATE FILE : {filename}")
        print("State deleted.")


# ============================================================
# Logging Helpers
# ============================================================


def info(message):

    print(message)


def success(message):

    print(message)


def warning(message):

    print(message)


# ============================================================
# Wait
# ============================================================


def wait(seconds):

    seconds = int(seconds)

    print(f"\nWaiting for {seconds} seconds...")

    time.sleep(seconds)


# ============================================================
# Safe Read Operations
# ============================================================


def get_bucket_versioning(client, bucket):

    response = client.get_bucket_versioning(Bucket=bucket)

    return response.get("Status", "Suspended")


def get_bucket_encryption(client, bucket):

    try:
        response = client.get_bucket_encryption(Bucket=bucket)

        return response

    except ClientError as ex:
        code = ex.response["Error"]["Code"]

        if code == "ServerSideEncryptionConfigurationNotFoundError":
            return None

        raise


def get_bucket_policy(client, bucket):

    try:
        response = client.get_bucket_policy(Bucket=bucket)

        return response["Policy"]

    except ClientError as ex:
        code = ex.response["Error"]["Code"]

        if code == "NoSuchBucketPolicy":
            return None

        raise


def get_bucket_lifecycle(client, bucket):

    try:
        response = client.get_bucket_lifecycle_configuration(Bucket=bucket)

        return response

    except ClientError as ex:
        code = ex.response["Error"]["Code"]

        if code == "NoSuchLifecycleConfiguration":
            return None

        raise


def get_public_access_block(client, bucket):

    try:
        response = client.get_public_access_block(Bucket=bucket)

        return response["PublicAccessBlockConfiguration"]

    except ClientError as ex:
        code = ex.response["Error"]["Code"]

        if code == "NoSuchPublicAccessBlockConfiguration":
            return None

        raise


# ============================================================
# Restore Helpers
# ============================================================


def restore_versioning(client, bucket, state):

    client.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": state}
    )


def restore_encryption(client, bucket, state):

    if state is None:
        try:
            client.delete_bucket_encryption(Bucket=bucket)

        except ClientError:
            pass

        return

    client.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration=state["ServerSideEncryptionConfiguration"],
    )


def restore_bucket_policy(client, bucket, state):

    if state is None:
        try:
            client.delete_bucket_policy(Bucket=bucket)

        except ClientError:
            pass

        return

    client.put_bucket_policy(Bucket=bucket, Policy=state)


def restore_lifecycle(client, bucket, state):

    if state is None:
        try:
            client.delete_bucket_lifecycle(Bucket=bucket)

        except ClientError:
            pass

        return

    client.put_bucket_lifecycle_configuration(
        Bucket=bucket, LifecycleConfiguration={"Rules": state["Rules"]}
    )


def restore_public_access(client, bucket, state):

    if state is None:
        try:
            client.delete_public_access_block(Bucket=bucket)

        except ClientError:
            pass

        return

    client.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration=state)
