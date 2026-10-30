from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions import (
    publish_message,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.boto3.client")
def test_publish_message_success(mock_client, mock_info, mock_success):
    client = MagicMock()

    client.publish.return_value = {"MessageId": "abc123"}

    mock_client.return_value = client

    result = publish_message("arn:aws:sns:test", "Hello", "eu-central-1")

    client.publish.assert_called_once_with(TopicArn="arn:aws:sns:test", Message="Hello")

    assert result is True


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.boto3.client")
def test_publish_message_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.publish.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "Publish"
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        publish_message("arn:aws:sns:test", "Hello", "eu-central-1")

    mock_error.assert_called_once()


@patch("time.sleep")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.info")
def test_wait_for_duration(mock_info, mock_success, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.boto3.client")
def test_publish_uses_correct_region(mock_client, mock_info, mock_success):
    client = MagicMock()

    client.publish.return_value = {"MessageId": "1"}

    mock_client.return_value = client

    publish_message("topic", "msg", "us-east-1")

    mock_client.assert_called_once_with("sns", region_name="us-east-1")


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_publish_actions.boto3.client")
def test_publish_logs_message_id(mock_client, mock_info, mock_success):
    client = MagicMock()

    client.publish.return_value = {"MessageId": "xyz789"}

    mock_client.return_value = client

    publish_message("topic", "msg", "eu-west-1")

    mock_info.assert_any_call("Message ID : xyz789")
