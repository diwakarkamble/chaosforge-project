from unittest.mock import patch

from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions import (
    capture_current_versioning,
    restore_original_versioning,
    update_versioning,
)

# ============================================================
# Capture Current Versioning
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_bucket_versioning")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_client")
def test_capture_current_versioning(
    mock_get_client,
    mock_get_versioning,
    mock_save_state,
):

    client = object()

    mock_get_client.return_value = client
    mock_get_versioning.return_value = "Enabled"

    result = capture_current_versioning(
        "demo-bucket",
        "eu-west-1",
    )

    assert result is True

    mock_get_versioning.assert_called_once_with(
        client,
        "demo-bucket",
    )

    mock_save_state.assert_called_once_with(
        "s3_versioning",
        {
            "bucket": "demo-bucket",
            "versioning": "Enabled",
        },
        "demo-bucket",
    )


# ============================================================
# Update Versioning
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_client")
def test_update_versioning(
    mock_get_client,
    mock_success,
):

    client = mock_get_client.return_value

    result = update_versioning(
        "demo-bucket",
        "eu-west-1",
        "Suspended",
    )

    assert result is True

    client.put_bucket_versioning.assert_called_once_with(
        Bucket="demo-bucket",
        VersioningConfiguration={
            "Status": "Suspended",
        },
    )

    mock_success.assert_called_once()


# ============================================================
# Restore Versioning
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.delete_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.restore_versioning")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_client")
def test_restore_original_versioning(
    mock_get_client,
    mock_load_state,
    mock_restore,
    mock_success,
    mock_delete,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "bucket": "demo-bucket",
        "versioning": "Enabled",
    }

    result = restore_original_versioning(
        "demo-bucket",
        "eu-west-1",
    )

    assert result is True

    mock_restore.assert_called_once_with(
        client,
        "demo-bucket",
        "Enabled",
    )

    mock_success.assert_called_once()

    mock_delete.assert_called_once_with(
        "s3_versioning",
        "demo-bucket",
    )


# ============================================================
# Capture Disabled Versioning
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_bucket_versioning")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_client")
def test_capture_current_versioning_disabled(
    mock_get_client,
    mock_get_versioning,
    mock_save_state,
    mock_info,
):

    mock_get_versioning.return_value = "Suspended"

    capture_current_versioning(
        "demo-bucket",
        "eu-west-1",
    )

    mock_info.assert_called_once_with("Original Versioning : Suspended")


# ============================================================
# Restore Deletes State
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.delete_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.restore_versioning")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_client")
def test_restore_calls_delete_state(
    mock_get_client,
    mock_load_state,
    mock_restore,
    mock_success,
    mock_delete,
):

    mock_load_state.return_value = {
        "bucket": "demo",
        "versioning": "Enabled",
    }

    restore_original_versioning(
        "demo",
        "eu-west-1",
    )

    mock_delete.assert_called_once_with(
        "s3_versioning",
        "demo",
    )


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_versioning_actions.get_client")
def test_restore_rejects_versioning_state_from_another_bucket(_mock_client, mock_load_state):
    mock_load_state.return_value = {"bucket": "other", "versioning": "Enabled"}

    import pytest

    with pytest.raises(RuntimeError, match="does not match"):
        restore_original_versioning("demo", "eu-west-1")
