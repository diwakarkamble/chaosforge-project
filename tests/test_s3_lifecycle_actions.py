from unittest.mock import patch

from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions import (
    capture_current_lifecycle,
    restore_original_lifecycle,
    update_lifecycle,
)


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_bucket_lifecycle")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_client")
def test_capture_current_lifecycle(
    mock_get_client,
    mock_get_lifecycle,
    mock_save_state,
):

    client = mock_get_client.return_value

    lifecycle = {"Rules": []}

    mock_get_lifecycle.return_value = lifecycle

    assert capture_current_lifecycle("bucket", "eu-west-1") is True

    mock_get_lifecycle.assert_called_once_with(client, "bucket")

    mock_save_state.assert_called_once_with(
        "s3_lifecycle",
        {
            "bucket": "bucket",
            "lifecycle": lifecycle,
        },
        "bucket",
    )


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_bucket_lifecycle")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_client")
def test_capture_current_lifecycle_none(
    mock_get_client,
    mock_get_lifecycle,
    mock_info,
):

    mock_get_lifecycle.return_value = None

    capture_current_lifecycle("bucket", "eu-west-1")

    mock_info.assert_called_once_with("Original Lifecycle : Not Configured")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_client")
def test_update_lifecycle(
    mock_get_client,
    mock_success,
):

    client = mock_get_client.return_value

    assert (
        update_lifecycle(
            "bucket",
            "eu-west-1",
            30,
        )
        is True
    )

    client.put_bucket_lifecycle_configuration.assert_called_once()

    mock_success.assert_called_once()


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.delete_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.restore_lifecycle")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_client")
def test_restore_original_lifecycle(
    mock_get_client,
    mock_load_state,
    mock_restore,
    mock_success,
    mock_delete,
):

    client = mock_get_client.return_value

    state = {
        "bucket": "bucket",
        "lifecycle": {"Rules": []},
    }

    mock_load_state.return_value = state

    assert (
        restore_original_lifecycle(
            "bucket",
            "eu-west-1",
        )
        is True
    )

    mock_restore.assert_called_once_with(
        client,
        "bucket",
        state["lifecycle"],
    )

    mock_delete.assert_called_once_with("s3_lifecycle", "bucket")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_bucket_lifecycle")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_client")
def test_capture_current_lifecycle_enabled(
    mock_get_client,
    mock_get_lifecycle,
    mock_info,
):

    mock_get_lifecycle.return_value = {"Rules": []}

    capture_current_lifecycle("bucket", "eu-west-1")

    mock_info.assert_called_once_with("Original Lifecycle captured.")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_lifecycle_actions.get_client")
def test_restore_rejects_lifecycle_state_from_another_bucket(_mock_client, mock_load_state):
    mock_load_state.return_value = {"bucket": "other", "lifecycle": None}

    import pytest

    with pytest.raises(RuntimeError, match="does not match"):
        restore_original_lifecycle("demo", "eu-west-1")
