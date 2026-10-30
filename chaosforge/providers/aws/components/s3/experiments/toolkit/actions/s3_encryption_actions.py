from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common import (
    delete_state,
    get_bucket_encryption,
    get_client,
    info,
    load_state,
    restore_encryption,
    save_state,
    success,
)

EXPERIMENT_NAME = "s3_encryption"


def capture_current_encryption(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    encryption = get_bucket_encryption(client, bucket_name)

    save_state(
        EXPERIMENT_NAME,
        {"bucket": bucket_name, "encryption": encryption},
        bucket_name,
    )

    if encryption is None:
        info("Original Encryption : Disabled")

    else:
        info("Original Encryption : Enabled")

    return True


def update_encryption(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    client.put_bucket_encryption(
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]
        },
    )

    success("Bucket Encryption Enabled (AES256)")

    return True


def restore_original_encryption(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    state = load_state(EXPERIMENT_NAME, bucket_name)
    if state.get("bucket") != bucket_name:
        raise RuntimeError("Encryption rollback state does not match the selected bucket.")

    restore_encryption(client, bucket_name, state["encryption"])

    success("Bucket Encryption Restored")

    delete_state(EXPERIMENT_NAME, bucket_name)

    return True
