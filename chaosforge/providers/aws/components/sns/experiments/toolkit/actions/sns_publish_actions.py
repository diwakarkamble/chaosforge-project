"""
SNS Publish Message Actions
"""

import boto3
from botocore.exceptions import ClientError

from chaosforge.interfaces.cli.interactive.ui.status import error, info, success


def publish_message(topic_arn, message, region):
    """
    Publish a message to an SNS Topic.
    """

    info(f"Publishing message to SNS Topic: {topic_arn}")

    client = boto3.client("sns", region_name=region)

    try:
        response = client.publish(TopicArn=topic_arn, Message=message)

        success("Message published successfully.")

        info(f"Message ID : {response['MessageId']}")

        return True

    except ClientError as e:
        error(f"Failed to publish message: {e}")

        raise


def wait_for_duration(wait_seconds):
    """
    Optional wait helper.
    """

    import time

    wait_seconds = int(wait_seconds)

    info(f"Waiting for {wait_seconds} seconds...")

    time.sleep(wait_seconds)

    success("Wait completed.")
