"""
SNS Delivery Policy Actions
"""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

from chaosforge.interfaces.cli.interactive.ui.status import error, info, success

STATE_FILE = "sns_delivery_policy_state.json"


def capture_current_delivery_policy(topic_arn, region):
    """
    Capture current SNS Delivery Policy.
    """

    info(f"Capturing Delivery Policy for {topic_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        response = client.get_topic_attributes(TopicArn=topic_arn)

        attributes = response["Attributes"]

        state = {
            "topic_arn": topic_arn,
            "delivery_policy": attributes.get("DeliveryPolicy"),
        }

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)

        success("Current Delivery Policy captured.")

        return True

    except ClientError as e:
        error(f"Failed to capture Delivery Policy: {e}")

        raise


def update_delivery_policy(topic_arn, region, delivery_policy):
    """
    Apply a restrictive delivery policy.

    NOTE:
    This policy is intended only for controlled
    chaos testing.
    """

    info(f"Updating Delivery Policy for {topic_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        delivery_policy = json.loads(delivery_policy)
        if not isinstance(delivery_policy, dict):
            raise ValueError("Delivery policy must be a JSON object.")

        client.set_topic_attributes(
            TopicArn=topic_arn,
            AttributeName="DeliveryPolicy",
            AttributeValue=json.dumps(delivery_policy),
        )

        success("Delivery Policy updated.")

        return True

    except ClientError as e:
        error(f"Failed to update Delivery Policy: {e}")

        raise


def wait_for_duration(wait_seconds):
    """
    Wait before rollback.
    """

    wait_seconds = int(wait_seconds)

    info(f"Waiting for {wait_seconds} seconds...")

    time.sleep(wait_seconds)

    success("Wait completed.")


def restore_delivery_policy(topic_arn, region):
    """
    Restore original Delivery Policy.
    """

    if not os.path.exists(STATE_FILE):
        error("Delivery Policy state file not found.")

        return False

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    client = boto3.client("sns", region_name=region)

    try:
        original_policy = state.get("delivery_policy")

        if original_policy is None:
            client.set_topic_attributes(
                TopicArn=topic_arn, AttributeName="DeliveryPolicy", AttributeValue=""
            )

        else:
            client.set_topic_attributes(
                TopicArn=topic_arn,
                AttributeName="DeliveryPolicy",
                AttributeValue=original_policy,
            )

        success("Original Delivery Policy restored.")

        return True

    except ClientError as e:
        error(f"Failed to restore Delivery Policy: {e}")

        raise
