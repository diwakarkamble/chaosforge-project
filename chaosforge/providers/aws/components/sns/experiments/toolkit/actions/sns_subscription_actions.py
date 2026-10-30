"""
SNS Subscription Actions
"""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

from chaosforge.interfaces.cli.interactive.ui.status import error, info, success

STATE_FILE = "sns_subscription_state.json"


def capture_subscription(subscription_arn, region):
    """
    Capture current subscription attributes.
    """

    info(f"Capturing subscription: {subscription_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        response = client.get_subscription_attributes(SubscriptionArn=subscription_arn)

        state = {
            "subscription_arn": subscription_arn,
            "attributes": response["Attributes"],
        }

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)

        success("Subscription details captured.")

        return True

    except ClientError as e:
        error(f"Failed to capture subscription: {e}")

        raise


def delete_subscription(subscription_arn, region):
    """
    Delete SNS Subscription.
    """

    info(f"Deleting subscription: {subscription_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        client.unsubscribe(SubscriptionArn=subscription_arn)

        success("Subscription deleted successfully.")

        return True

    except ClientError as e:
        error(f"Failed to delete subscription: {e}")

        raise


def wait_for_duration(wait_seconds):
    """
    Wait for configured duration.
    """

    wait_seconds = int(wait_seconds)

    info(f"Waiting for {wait_seconds} seconds...")

    time.sleep(wait_seconds)

    success("Wait completed.")


def restore_subscription(region):
    """
    Restore SNS Subscription.

    NOTE:
    Automatic restoration is not yet implemented.
    This function currently loads the saved state
    for future enhancement.
    """

    if not os.path.exists(STATE_FILE):
        error("No subscription state found.")

        return False

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    info("Subscription restoration is not implemented yet.")

    info(f"Original Subscription ARN: {state['subscription_arn']}")

    success("Rollback placeholder completed.")

    return True
