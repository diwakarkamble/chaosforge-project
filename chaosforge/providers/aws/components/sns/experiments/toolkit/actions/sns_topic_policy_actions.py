"""Actions for temporarily replacing an SNS topic policy."""

import json
import time

import boto3
from botocore.exceptions import ClientError

from chaosforge.common.paths import repository_paths
from chaosforge.interfaces.cli.interactive.ui.status import error, info, success


def _state_file(topic_arn):
    topic_name = topic_arn.rsplit(":", 1)[-1]
    safe_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in topic_name
    )
    return repository_paths().rollback / f"sns-topic-policy-{safe_name}.json"


def capture_current_policy(topic_arn, region):
    """Capture the current SNS topic policy for rollback."""

    info(f"Capturing Topic Policy for {topic_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        response = client.get_topic_attributes(TopicArn=topic_arn)

        attributes = response["Attributes"]

        state = {"topic_arn": topic_arn, "policy": attributes.get("Policy")}
        state_file = _state_file(topic_arn)
        state_file.parent.mkdir(parents=True, exist_ok=True)

        with state_file.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=4)

        success("Current Topic Policy captured.")

        return True

    except ClientError as e:
        error(f"Failed to capture Topic Policy: {e}")

        raise


def update_topic_policy(topic_arn, region):
    """Restrict the topic policy to the owning AWS account."""

    info(f"Updating Topic Policy for {topic_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        arn_parts = topic_arn.split(":", 5)
        if len(arn_parts) != 6:
            raise ValueError(f"Invalid SNS topic ARN: {topic_arn}")
        arn, partition, service, _region, account_id, _topic_name = arn_parts
        if arn != "arn" or service != "sns" or not account_id:
            raise ValueError(f"Invalid SNS topic ARN: {topic_arn}")

        owner_only_policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowOwnerOnly",
                        "Effect": "Allow",
                        "Principal": {"AWS": f"arn:{partition}:iam::{account_id}:root"},
                        "Action": [
                            "SNS:Publish",
                            "SNS:RemovePermission",
                            "SNS:SetTopicAttributes",
                            "SNS:DeleteTopic",
                            "SNS:ListSubscriptionsByTopic",
                            "SNS:GetTopicAttributes",
                            "SNS:AddPermission",
                            "SNS:Subscribe",
                        ],
                        "Resource": topic_arn,
                    }
                ],
            }
        )

        client.set_topic_attributes(
            TopicArn=topic_arn, AttributeName="Policy", AttributeValue=owner_only_policy
        )

        success("Topic Policy updated.")

        return True

    except ClientError as e:
        error(f"Failed to update Topic Policy: {e}")

        raise


def wait_for_duration(wait_seconds):
    """Wait before rollback."""

    wait_seconds = int(wait_seconds)

    info(f"Waiting for {wait_seconds} seconds...")

    time.sleep(wait_seconds)

    success("Wait completed.")


def restore_topic_policy(topic_arn, region):
    """Restore the policy captured before fault injection."""

    state_file = _state_file(topic_arn)

    if not state_file.exists():
        error("Topic Policy state file not found.")

        return False

    with state_file.open(encoding="utf-8") as handle:
        state = json.load(handle)

    if state.get("topic_arn") != topic_arn:
        raise ValueError("SNS policy rollback state does not match the target topic.")

    client = boto3.client("sns", region_name=region)

    try:
        client.set_topic_attributes(
            TopicArn=topic_arn,
            AttributeName="Policy",
            AttributeValue=state.get("policy") or "",
        )
        state_file.unlink()

        success("Original Topic Policy restored.")

        return True

    except ClientError as e:
        error(f"Failed to restore Topic Policy: {e}")

        raise
