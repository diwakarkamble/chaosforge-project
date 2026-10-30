from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common import (
    delete_state,
    get_bucket_versioning,
    get_client,
    info,
    load_state,
    restore_versioning,
    save_state,
    success,
)

EXPERIMENT_NAME = "s3_versioning"


def capture_current_versioning(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    status = get_bucket_versioning(client, bucket_name)

    save_state(
        EXPERIMENT_NAME,
        {"bucket": bucket_name, "versioning": status},
        bucket_name,
    )

    info(f"Original Versioning : {status}")

    return True


def update_versioning(
    bucket_name,
    aws_region,
    target_status,
):
    client = get_client(aws_region)

    client.put_bucket_versioning(
        Bucket=bucket_name, VersioningConfiguration={"Status": target_status}
    )

    success(f"Bucket Versioning Updated : {target_status}")

    return True


def restore_original_versioning(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    state = load_state(EXPERIMENT_NAME, bucket_name)
    if state.get("bucket") != bucket_name:
        raise RuntimeError("Versioning rollback state does not match the selected bucket.")

    restore_versioning(client, bucket_name, state["versioning"])

    success(f"Bucket Versioning Restored : {state['versioning']}")

    delete_state(EXPERIMENT_NAME, bucket_name)

    return True
