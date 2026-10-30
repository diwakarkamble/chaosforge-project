from unittest.mock import patch

from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions import (
    capture_current_encryption,
    restore_original_encryption,
    update_encryption,
)

# ============================================================
# Capture Current Encryption
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_bucket_encryption")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_client")
def test_capture_current_encryption_enabled(
    mock_get_client,
    mock_get_encryption,
    mock_save_state,
):

    client = mock_get_client.return_value

    encryption = {"ServerSideEncryptionConfiguration": {"Rules": []}}

    mock_get_encryption.return_value = encryption

    result = capture_current_encryption(
        "demo-bucket",
        "eu-west-1",
    )

    assert result is True

    mock_get_encryption.assert_called_once_with(
        client,
        "demo-bucket",
    )

    mock_save_state.assert_called_once_with(
        "s3_encryption",
        {
            "bucket": "demo-bucket",
            "encryption": encryption,
        },
        "demo-bucket",
    )


# ============================================================
# Capture Disabled Encryption
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_bucket_encryption")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_client")
def test_capture_current_encryption_disabled(
    mock_get_client,
    mock_get_encryption,
    mock_save_state,
    mock_info,
):

    mock_get_encryption.return_value = None

    capture_current_encryption(
        "demo-bucket",
        "eu-west-1",
    )

    mock_info.assert_called_once_with("Original Encryption : Disabled")


# ============================================================
# Update Encryption
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_client")
def test_update_encryption(
    mock_get_client,
    mock_success,
):

    client = mock_get_client.return_value

    result = update_encryption(
        "demo-bucket",
        "eu-west-1",
    )

    assert result is True

    client.put_bucket_encryption.assert_called_once()

    kwargs = client.put_bucket_encryption.call_args.kwargs

    assert kwargs["Bucket"] == "demo-bucket"

    assert (
        kwargs["ServerSideEncryptionConfiguration"]["Rules"][0][
            "ApplyServerSideEncryptionByDefault"
        ]["SSEAlgorithm"]
        == "AES256"
    )

    mock_success.assert_called_once()


# ============================================================
# Restore Encryption
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.delete_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.restore_encryption")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_client")
def test_restore_original_encryption(
    mock_get_client,
    mock_load_state,
    mock_restore,
    mock_success,
    mock_delete,
):

    client = mock_get_client.return_value

    state = {
        "bucket": "demo-bucket",
        "encryption": {"ServerSideEncryptionConfiguration": {}},
    }

    mock_load_state.return_value = state

    result = restore_original_encryption(
        "demo-bucket",
        "eu-west-1",
    )

    assert result is True

    mock_restore.assert_called_once_with(
        client,
        "demo-bucket",
        state["encryption"],
    )

    mock_success.assert_called_once()

    mock_delete.assert_called_once_with(
        "s3_encryption",
        "demo-bucket",
    )


# ============================================================
# Restore Deletes State
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.delete_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.restore_encryption")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_client")
def test_restore_calls_delete_state(
    mock_get_client,
    mock_load_state,
    mock_restore,
    mock_success,
    mock_delete,
):

    mock_load_state.return_value = {
        "bucket": "demo",
        "encryption": None,
    }

    restore_original_encryption(
        "demo",
        "eu-west-1",
    )

    mock_delete.assert_called_once_with(
        "s3_encryption",
        "demo",
    )


# ============================================================
# Encryption Enabled Message
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_bucket_encryption")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_client")
def test_capture_current_encryption_enabled_message(
    mock_get_client,
    mock_get_encryption,
    mock_save_state,
    mock_info,
):

    mock_get_encryption.return_value = {"ServerSideEncryptionConfiguration": {}}

    capture_current_encryption(
        "demo-bucket",
        "eu-west-1",
    )

    mock_info.assert_called_once_with("Original Encryption : Enabled")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_encryption_actions.get_client")
def test_restore_rejects_encryption_state_from_another_bucket(_mock_client, mock_load_state):
    mock_load_state.return_value = {"bucket": "other", "encryption": None}

    import pytest

    with pytest.raises(RuntimeError, match="does not match"):
        restore_original_encryption("demo", "eu-west-1")
