from unittest.mock import MagicMock, mock_open, patch

import pytest
from botocore.exceptions import ClientError

from chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions import (
    capture_subscription,
    delete_subscription,
    restore_subscription,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.json.dump")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.boto3.client")
def test_capture_subscription(
    mock_client, mock_open_file, mock_dump, mock_info, mock_success
):
    client = MagicMock()

    client.get_subscription_attributes.return_value = {
        "Attributes": {"Protocol": "email", "Endpoint": "test@example.com"}
    }

    mock_client.return_value = client

    result = capture_subscription("arn:test", "eu-central-1")

    assert result is True

    client.get_subscription_attributes.assert_called_once_with(
        SubscriptionArn="arn:test"
    )

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.boto3.client")
def test_capture_subscription_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.get_subscription_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}},
        "GetSubscriptionAttributes",
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        capture_subscription("arn:test", "eu-central-1")

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.boto3.client")
def test_delete_subscription(mock_client, mock_info, mock_success):
    client = MagicMock()

    mock_client.return_value = client

    result = delete_subscription("arn:test", "eu-central-1")

    assert result is True

    client.unsubscribe.assert_called_once_with(SubscriptionArn="arn:test")


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.boto3.client")
def test_delete_subscription_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.unsubscribe.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "Unsubscribe"
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        delete_subscription("arn:test", "eu-central-1")

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.time.sleep")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.info")
def test_wait_for_duration(mock_info, mock_success, mock_sleep):
    wait_for_duration("20")

    mock_sleep.assert_called_once_with(20)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.json.load")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.os.path.exists")
def test_restore_subscription(
    mock_exists, mock_open_file, mock_load, mock_info, mock_success
):
    mock_exists.return_value = True

    mock_load.return_value = {"subscription_arn": "arn:test"}

    result = restore_subscription("eu-central-1")

    assert result is True

    mock_info.assert_any_call("Subscription restoration is not implemented yet.")


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_actions.os.path.exists")
def test_restore_subscription_missing_state(mock_exists, mock_error):
    mock_exists.return_value = False

    result = restore_subscription("eu-central-1")

    assert result is False

    mock_error.assert_called_once()
