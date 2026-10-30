import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions import (
    capture_current_policy,
    restore_topic_policy,
    update_topic_policy,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.boto3.client")
def test_capture_current_policy(
    mock_client, mock_info, mock_success, tmp_path, monkeypatch
):
    client = MagicMock()

    client.get_topic_attributes.return_value = {
        "Attributes": {"Policy": '{"Version":"2012-10-17"}'}
    }

    mock_client.return_value = client
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(
        "chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions._state_file",
        lambda topic_arn: state_file,
    )

    result = capture_current_policy("arn:test", "eu-central-1")

    assert result is True

    client.get_topic_attributes.assert_called_once_with(TopicArn="arn:test")

    assert state_file.exists()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.boto3.client")
def test_capture_current_policy_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.get_topic_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "GetTopicAttributes"
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        capture_current_policy("arn:test", "eu-central-1")

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.boto3.client")
def test_update_topic_policy(mock_client, mock_info, mock_success):
    client = MagicMock()

    mock_client.return_value = client

    topic_arn = "arn:aws:sns:eu-central-1:123456789012:topic"

    result = update_topic_policy(topic_arn, "eu-central-1")

    assert result is True

    client.set_topic_attributes.assert_called_once_with(
        TopicArn=topic_arn,
        AttributeName="Policy",
        AttributeValue=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowOwnerOnly",
                        "Effect": "Allow",
                        "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
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
        ),
    )

    policy = json.loads(client.set_topic_attributes.call_args.kwargs["AttributeValue"])
    assert "SNS:*" not in policy["Statement"][0]["Action"]


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.boto3.client")
def test_update_topic_policy_failure(mock_client, mock_info, mock_error):
    client = MagicMock()

    client.set_topic_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "SetTopicAttributes"
    )

    mock_client.return_value = client

    with pytest.raises(ClientError):
        update_topic_policy("arn:aws:sns:eu-central-1:123456789012:topic", "eu-central-1")

    mock_error.assert_called_once()


def test_update_topic_policy_rejects_invalid_arn():
    with pytest.raises(ValueError, match="Invalid SNS topic ARN"):
        update_topic_policy("invalid", "eu-central-1")

    with pytest.raises(ValueError, match="Invalid SNS topic ARN"):
        update_topic_policy("invalid:aws:sns:eu-central-1:123456789012:topic", "eu-central-1")


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.time.sleep")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.info")
def test_wait_for_duration(mock_info, mock_success, mock_sleep):
    wait_for_duration("10")

    mock_sleep.assert_called_once_with(10)


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.boto3.client")
def test_restore_topic_policy(
    mock_client, mock_success, tmp_path, monkeypatch
):
    client = MagicMock()

    mock_client.return_value = client
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"topic_arn":"arn:test","policy":"{\\"Version\\":\\"2012-10-17\\"}"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions._state_file",
        lambda topic_arn: state_file,
    )

    result = restore_topic_policy("arn:test", "eu-central-1")

    assert result is True

    client.set_topic_attributes.assert_called_once_with(
        TopicArn="arn:test",
        AttributeName="Policy",
        AttributeValue='{"Version":"2012-10-17"}',
    )
    assert not state_file.exists()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.error")
def test_restore_topic_policy_missing_state(mock_error, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions._state_file",
        lambda topic_arn: tmp_path / "missing.json",
    )

    result = restore_topic_policy("arn:test", "eu-central-1")

    assert result is False

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.error")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.boto3.client")
def test_restore_topic_policy_failure(
    mock_client, mock_error, tmp_path, monkeypatch
):
    client = MagicMock()

    client.set_topic_attributes.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "Failure"}}, "SetTopicAttributes"
    )

    mock_client.return_value = client
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"topic_arn":"arn:test","policy":"{\\"Version\\":\\"2012-10-17\\"}"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions._state_file",
        lambda topic_arn: state_file,
    )

    with pytest.raises(ClientError):
        restore_topic_policy("arn:test", "eu-central-1")

    mock_error.assert_called_once()


@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.success")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.info")
@patch("chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions.boto3.client")
def test_capture_uses_region(mock_client, mock_info, mock_success, tmp_path, monkeypatch):
    client = MagicMock()

    client.get_topic_attributes.return_value = {"Attributes": {}}

    mock_client.return_value = client
    monkeypatch.setattr(
        "chaosforge.providers.aws.components.sns.experiments.toolkit.actions.sns_topic_policy_actions._state_file",
        lambda topic_arn: tmp_path / "state.json",
    )

    capture_current_policy("arn:test", "us-east-1")

    mock_client.assert_called_once_with("sns", region_name="us-east-1")
