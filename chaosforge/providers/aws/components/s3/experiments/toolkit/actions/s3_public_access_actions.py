from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common import (
    delete_state,
    get_client,
    get_public_access_block,
    info,
    load_state,
    restore_public_access,
    save_state,
    success,
)

EXPERIMENT_NAME = "s3_public_access"


def capture_current_public_access(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    configuration = get_public_access_block(client, bucket_name)

    save_state(
        EXPERIMENT_NAME,
        {"bucket": bucket_name, "configuration": configuration},
        bucket_name,
    )

    if configuration is None:
        info("Original Public Access Block : Not Configured")

    else:
        info("Original Public Access Block captured.")

    return True


def update_public_access(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    client.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": False,
            "IgnorePublicAcls": False,
            "BlockPublicPolicy": False,
            "RestrictPublicBuckets": False,
        },
    )

    success("Public Access Block disabled for all four bucket-level controls.")

    return True


def restore_original_public_access(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    state = load_state(EXPERIMENT_NAME, bucket_name)
    if state.get("bucket") != bucket_name:
        raise RuntimeError("Public Access Block rollback state does not match the selected bucket.")

    restore_public_access(client, bucket_name, state["configuration"])

    success("Public Access Block Restored.")

    delete_state(EXPERIMENT_NAME, bucket_name)

    return True
