import json

from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common import (
    delete_state,
    get_bucket_policy,
    get_client,
    info,
    load_state,
    restore_bucket_policy,
    save_state,
    success,
)

EXPERIMENT_NAME = "s3_bucket_policy"


def _build_policy(bucket_name, policy_template):

    if policy_template == "readonly":
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "ReadOnly",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                }
            ],
        }

    elif policy_template == "deny-public-read":
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyPublicRead",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                }
            ],
        }

    elif policy_template == "deny-delete":
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyDelete",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": ["s3:DeleteObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                }
            ],
        }

    raise ValueError(f"Unsupported policy template: {policy_template}")


def capture_current_policy(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    policy = get_bucket_policy(client, bucket_name)

    save_state(
        EXPERIMENT_NAME,
        {"bucket": bucket_name, "policy": policy},
        bucket_name,
    )

    if policy is None:
        info("Original Bucket Policy : None")

    else:
        info("Original Bucket Policy captured.")

    return True


def update_policy(
    bucket_name,
    aws_region,
    policy_template,
):
    client = get_client(aws_region)

    policy = _build_policy(bucket_name, policy_template)

    client.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(policy))

    success(f"Bucket Policy Updated ({policy_template})")

    return True


def restore_original_policy(
    bucket_name,
    aws_region,
):
    client = get_client(aws_region)

    state = load_state(EXPERIMENT_NAME, bucket_name)
    if state.get("bucket") != bucket_name:
        raise RuntimeError("Bucket policy rollback state does not match the selected bucket.")

    restore_bucket_policy(client, bucket_name, state["policy"])

    success("Bucket Policy Restored.")

    delete_state(EXPERIMENT_NAME, bucket_name)

    return True
