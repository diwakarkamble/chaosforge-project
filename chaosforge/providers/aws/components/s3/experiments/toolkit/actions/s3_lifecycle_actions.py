from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common import (
    delete_state,
    get_bucket_lifecycle,
    get_client,
    info,
    load_state,
    restore_lifecycle,
    save_state,
    success,
)

EXPERIMENT_NAME = "s3_lifecycle"


def capture_current_lifecycle(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    lifecycle = get_bucket_lifecycle(client, bucket_name)

    save_state(
        EXPERIMENT_NAME,
        {"bucket": bucket_name, "lifecycle": lifecycle},
        bucket_name,
    )

    if lifecycle is None:
        info("Original Lifecycle : Not Configured")
    else:
        info("Original Lifecycle captured.")

    return True


def update_lifecycle(
    bucket_name,
    aws_region,
    expiration_days,
):
    client = get_client(aws_region)

    client.put_bucket_lifecycle_configuration(
        Bucket=bucket_name,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "ChaosForgeLifecycleRule",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "Expiration": {"Days": int(expiration_days)},
                }
            ]
        },
    )

    success(f"Lifecycle Updated ({expiration_days} days)")

    return True


def restore_original_lifecycle(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    state = load_state(EXPERIMENT_NAME, bucket_name)
    if state.get("bucket") != bucket_name:
        raise RuntimeError("Lifecycle rollback state does not match the selected bucket.")

    restore_lifecycle(client, bucket_name, state["lifecycle"])

    success("Lifecycle Restored.")

    delete_state(EXPERIMENT_NAME, bucket_name)

    return True
