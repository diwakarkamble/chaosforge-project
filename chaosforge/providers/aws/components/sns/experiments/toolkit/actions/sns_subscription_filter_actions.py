"""
SNS Subscription Filter Policy Actions
"""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

from chaosforge.interfaces.cli.interactive.ui.status import error, info, success

STATE_FILE = "sns_subscription_filter_state.json"


def capture_current_filter_policy(subscription_arn, region):
    """
    Capture current SNS Subscription Filter Policy.
    """

    info(f"Capturing Filter Policy for {subscription_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        response = client.get_subscription_attributes(SubscriptionArn=subscription_arn)

        attributes = response["Attributes"]

        state = {
            "subscription_arn": subscription_arn,
            "filter_policy": attributes.get("FilterPolicy"),
        }

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)

        success("Current Filter Policy captured.")

        return True

    except ClientError as e:
        error(f"Failed to capture Filter Policy: {e}")

        raise


def update_filter_policy(subscription_arn, region, filter_policy):
    """
    Apply a restrictive filter policy.
    """

    info(f"Updating Filter Policy for {subscription_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        filter_policy = json.loads(filter_policy)
        if not isinstance(filter_policy, dict):
            raise ValueError("Filter policy must be a JSON object.")

        client.set_subscription_attributes(
            SubscriptionArn=subscription_arn,
            AttributeName="FilterPolicy",
            AttributeValue=json.dumps(filter_policy),
        )

        success("Filter Policy updated.")

        return True

    except ClientError as e:
        error(f"Failed to update Filter Policy: {e}")

        raise


def wait_for_duration(wait_seconds):
    """
    Wait before rollback.
    """

    wait_seconds = int(wait_seconds)

    info(f"Waiting for {wait_seconds} seconds...")

    time.sleep(wait_seconds)

    success("Wait completed.")


def restore_filter_policy(subscription_arn, region):
    """
    Restore original Filter Policy.
    """

    if not os.path.exists(STATE_FILE):
        error("Filter Policy state file not found.")

        return False

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    client = boto3.client("sns", region_name=region)

    try:
        original_policy = state.get("filter_policy")

        if original_policy is None:
            client.set_subscription_attributes(
                SubscriptionArn=subscription_arn,
                AttributeName="FilterPolicy",
                AttributeValue="",
            )

        else:
            client.set_subscription_attributes(
                SubscriptionArn=subscription_arn,
                AttributeName="FilterPolicy",
                AttributeValue=original_policy,
            )

        success("Original Filter Policy restored.")

        return True

    except ClientError as e:
        error(f"Failed to restore Filter Policy: {e}")

        raise
