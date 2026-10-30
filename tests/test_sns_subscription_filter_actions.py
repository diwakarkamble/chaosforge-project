from unittest.mock import MagicMock, mock_open, patch

import pytest
from botocore.exceptions import ClientError

from chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions import (
    capture_current_filter_policy,
    restore_filter_policy,
    update_filter_policy,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.json.dump")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.boto3.client")
def test_capture_current_filter_policy(
    mock_client, mock_open_file, mock_dump, mock_info, mock_success
):
    client = MagicMock()

    client.get_subscription_attributes.return_value = {
        "Attributes": {"FilterPolicy": '{"type":["test"]}'}
    }

    mock_client.return_value = client

    result = capture_current_filter_policy("arn:test", "eu-central-1")

    assert result is True

    client.get_subscription_attributes.assert_called_once_with(
        SubscriptionArn="arn:test"
    )

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.boto3.client")
def test_capture_filter_policy_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.get_subscription_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}},
        "GetSubscriptionAttributes",
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        capture_current_filter_policy("arn:test", "eu-central-1")

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.boto3.client")
def test_update_filter_policy(mock_client, mock_info, mock_success):
    client = MagicMock()

    mock_client.return_value = client

    result = update_filter_policy("arn:test", "eu-central-1", '{"event": ["allowed"]}')

    assert result is True

    client.set_subscription_attributes.assert_called_once_with(
        SubscriptionArn="arn:test",
        AttributeName="FilterPolicy",
        AttributeValue='{"event": ["allowed"]}',
    )


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.boto3.client")
def test_update_filter_policy_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.set_subscription_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}},
        "SetSubscriptionAttributes",
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        update_filter_policy("arn:test", "eu-central-1", "{}")

    mock_error.assert_called_once()


def test_update_filter_policy_rejects_non_object():
    with pytest.raises(ValueError, match="JSON object"):
        update_filter_policy("arn:test", "eu-central-1", "[]")


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.time.sleep")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.info")
def test_wait_for_duration(mock_info, mock_success, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.json.load")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.boto3.client")
def test_restore_filter_policy(
    mock_client, mock_exists, mock_open_file, mock_load, mock_success
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"filter_policy": '{"type":["prod"]}'}

    result = restore_filter_policy("arn:test", "eu-central-1")

    assert result is True

    client.set_subscription_attributes.assert_called_once_with(
        SubscriptionArn="arn:test",
        AttributeName="FilterPolicy",
        AttributeValue='{"type":["prod"]}',
    )


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.json.load")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.boto3.client")
def test_restore_filter_policy_none(
    mock_client, mock_exists, mock_open_file, mock_load, mock_success
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"filter_policy": None}

    restore_filter_policy("arn:test", "eu-central-1")

    client.set_subscription_attributes.assert_called_once_with(
        SubscriptionArn="arn:test", AttributeName="FilterPolicy", AttributeValue=""
    )


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.os.path.exists")
def test_restore_filter_policy_state_missing(mock_exists, mock_error):
    mock_exists.return_value = False

    result = restore_filter_policy("arn:test", "eu-central-1")

    assert result is False

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.json.load")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_subscription_filter_actions.boto3.client")
def test_restore_filter_policy_failure(
    mock_client, mock_exists, mock_open_file, mock_load, mock_error
):
    mock_exists.return_value = True

    client = MagicMock()

    client.set_subscription_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}},
        "SetSubscriptionAttributes",
    )

    mock_client.return_value = client

    mock_load.return_value = {"filter_policy": '{"type":["prod"]}'}

    with pytest.raises(ClientError):
        restore_filter_policy("arn:test", "eu-central-1")

    mock_error.assert_called_once()
