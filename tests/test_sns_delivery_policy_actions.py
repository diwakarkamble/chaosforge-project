import json
from unittest.mock import MagicMock, mock_open, patch

import pytest
from botocore.exceptions import ClientError

from chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions import (
    capture_current_delivery_policy,
    restore_delivery_policy,
    update_delivery_policy,
    wait_for_duration,
)


def test_delivery_policy_definition_passes_delivery_policy_only_to_update_action():
    from chaosforge.catalog import ExperimentCatalog

    definition = json.loads(
        ExperimentCatalog().definition_path("sns", "sns-delivery-policy-chaos.json").read_text(
            encoding="utf-8"
        )
    )
    capture, update = definition["method"][:2]

    assert "delivery_policy" not in capture["provider"]["arguments"]
    assert update["provider"]["arguments"]["delivery_policy"] == "${delivery_policy}"


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.json.dump")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.boto3.client")
def test_capture_current_delivery_policy(
    mock_client, mock_open_file, mock_dump, mock_info, mock_success
):
    client = MagicMock()

    client.get_topic_attributes.return_value = {
        "Attributes": {"DeliveryPolicy": '{"healthyRetryPolicy":{"numRetries":3}}'}
    }

    mock_client.return_value = client

    result = capture_current_delivery_policy("arn:test", "eu-central-1")

    assert result is True

    client.get_topic_attributes.assert_called_once_with(TopicArn="arn:test")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.boto3.client")
def test_capture_delivery_policy_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.get_topic_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "GetTopicAttributes"
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        capture_current_delivery_policy("arn:test", "eu-central-1")

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.boto3.client")
def test_update_delivery_policy(mock_client, mock_info, mock_success):
    client = MagicMock()

    mock_client.return_value = client

    result = update_delivery_policy(
        "arn:test", "eu-central-1", '{"healthyRetryPolicy": {"numRetries": 0}}'
    )

    assert result is True

    client.set_topic_attributes.assert_called_once_with(
        TopicArn="arn:test",
        AttributeName="DeliveryPolicy",
        AttributeValue='{"healthyRetryPolicy": {"numRetries": 0}}',
    )


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.boto3.client")
def test_update_delivery_policy_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.set_topic_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "SetTopicAttributes"
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        update_delivery_policy("arn:test", "eu-central-1", "{}")

    mock_error.assert_called_once()


def test_update_delivery_policy_rejects_non_object():
    with pytest.raises(ValueError, match="JSON object"):
        update_delivery_policy("arn:test", "eu-central-1", "[]")


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.time.sleep")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.info")
def test_wait_for_duration(mock_info, mock_success, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.json.load")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.boto3.client")
def test_restore_delivery_policy(
    mock_client, mock_exists, mock_open_file, mock_load, mock_success
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "delivery_policy": '{"healthyRetryPolicy":{"numRetries":3}}'
    }

    result = restore_delivery_policy("arn:test", "eu-central-1")

    assert result is True

    client.set_topic_attributes.assert_called_once_with(
        TopicArn="arn:test",
        AttributeName="DeliveryPolicy",
        AttributeValue='{"healthyRetryPolicy":{"numRetries":3}}',
    )


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.json.load")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.boto3.client")
def test_restore_delivery_policy_none(
    mock_client, mock_exists, mock_open_file, mock_load, mock_success
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"delivery_policy": None}

    restore_delivery_policy("arn:test", "eu-central-1")

    client.set_topic_attributes.assert_called_once_with(
        TopicArn="arn:test", AttributeName="DeliveryPolicy", AttributeValue=""
    )


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.os.path.exists")
def test_restore_delivery_policy_state_missing(mock_exists, mock_error):
    mock_exists.return_value = False

    result = restore_delivery_policy("arn:test", "eu-central-1")

    assert result is False

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.json.load")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_delivery_policy_actions.boto3.client")
def test_restore_delivery_policy_failure(
    mock_client, mock_exists, mock_open_file, mock_load, mock_error
):
    mock_exists.return_value = True

    client = MagicMock()

    client.set_topic_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "SetTopicAttributes"
    )

    mock_client.return_value = client

    mock_load.return_value = {
        "delivery_policy": '{"healthyRetryPolicy":{"numRetries":3}}'
    }

    with pytest.raises(ClientError):
        restore_delivery_policy("arn:test", "eu-central-1")

    mock_error.assert_called_once()
