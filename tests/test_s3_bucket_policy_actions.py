from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions import (
    _build_policy,
    capture_current_policy,
    restore_original_policy,
    update_policy,
)


def test_build_policy_readonly():

    policy = _build_policy("bucket", "readonly")

    assert policy["Statement"][0]["Sid"] == "ReadOnly"


def test_build_policy_deny_public():

    policy = _build_policy(
        "bucket",
        "deny-public-read",
    )

    assert policy["Statement"][0]["Sid"] == "DenyPublicRead"


def test_build_policy_deny_delete():

    policy = _build_policy(
        "bucket",
        "deny-delete",
    )

    assert policy["Statement"][0]["Sid"] == "DenyDelete"


def test_build_policy_invalid():

    with pytest.raises(ValueError):
        _build_policy("bucket", "invalid")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_bucket_policy")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_client")
def test_capture_current_policy(
    mock_get_client,
    mock_get_policy,
    mock_save_state,
):

    client = mock_get_client.return_value

    mock_get_policy.return_value = "{}"

    assert (
        capture_current_policy(
            "bucket",
            "eu-west-1",
        )
        is True
    )

    mock_get_policy.assert_called_once_with(
        client,
        "bucket",
    )


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_client")
def test_update_policy(
    mock_get_client,
    mock_success,
):

    client = mock_get_client.return_value

    assert (
        update_policy(
            "bucket",
            "eu-west-1",
            "readonly",
        )
        is True
    )

    client.put_bucket_policy.assert_called_once()

    mock_success.assert_called_once()


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.delete_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.restore_bucket_policy")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_client")
def test_restore_original_policy(
    mock_get_client,
    mock_load_state,
    mock_restore,
    mock_success,
    mock_delete,
):

    client = mock_get_client.return_value

    state = {
        "bucket": "bucket",
        "policy": "{}",
    }

    mock_load_state.return_value = state

    assert (
        restore_original_policy(
            "bucket",
            "eu-west-1",
        )
        is True
    )

    mock_restore.assert_called_once_with(
        client,
        "bucket",
        "{}",
    )

    mock_delete.assert_called_once_with(
        "s3_bucket_policy",
        "bucket",
    )


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_bucket_policy")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_client")
def test_capture_current_policy_none(
    mock_get_client,
    mock_get_policy,
    mock_info,
):

    mock_get_policy.return_value = None

    capture_current_policy(
        "bucket",
        "eu-west-1",
    )

    mock_info.assert_called_once_with("Original Bucket Policy : None")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_bucket_policy")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_client")
def test_capture_current_policy_present(
    mock_get_client,
    mock_get_policy,
    mock_info,
):

    mock_get_policy.return_value = "{}"

    capture_current_policy(
        "bucket",
        "eu-west-1",
    )

    mock_info.assert_called_once_with("Original Bucket Policy captured.")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_bucket_policy_actions.get_client")
def test_restore_rejects_policy_state_from_another_bucket(_mock_client, mock_load_state):
    mock_load_state.return_value = {"bucket": "other", "policy": None}

    with pytest.raises(RuntimeError, match="does not match"):
        restore_original_policy("demo", "eu-west-1")
