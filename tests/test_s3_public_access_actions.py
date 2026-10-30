from unittest.mock import patch

from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions import (
    capture_current_public_access,
    restore_original_public_access,
    update_public_access,
)


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.save_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_public_access_block")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_client")
def test_capture_current_public_access(
    mock_get_client,
    mock_get_block,
    mock_save_state,
):

    client = mock_get_client.return_value

    config = {"BlockPublicAcls": True}

    mock_get_block.return_value = config

    assert (
        capture_current_public_access(
            "bucket",
            "eu-west-1",
        )
        is True
    )

    mock_get_block.assert_called_once_with(
        client,
        "bucket",
    )

    mock_save_state.assert_called_once_with(
        "s3_public_access",
        {"bucket": "bucket", "configuration": config},
        "bucket",
    )


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_public_access_block")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_client")
def test_capture_current_public_access_none(
    mock_get_client,
    mock_get_block,
    mock_info,
):

    mock_get_block.return_value = None

    capture_current_public_access(
        "bucket",
        "eu-west-1",
    )

    mock_info.assert_called_once_with("Original Public Access Block : Not Configured")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_client")
def test_update_public_access(
    mock_get_client,
    mock_success,
):

    client = mock_get_client.return_value

    assert (
        update_public_access(
            "bucket",
            "eu-west-1",
        )
        is True
    )

    client.put_public_access_block.assert_called_once_with(
        Bucket="bucket",
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": False,
            "IgnorePublicAcls": False,
            "BlockPublicPolicy": False,
            "RestrictPublicBuckets": False,
        },
    )

    mock_success.assert_called_once()


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.delete_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.success")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.restore_public_access")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_client")
def test_restore_original_public_access(
    mock_get_client,
    mock_load_state,
    mock_restore,
    mock_success,
    mock_delete,
):

    client = mock_get_client.return_value

    state = {
        "bucket": "bucket",
        "configuration": {},
    }

    mock_load_state.return_value = state

    assert (
        restore_original_public_access(
            "bucket",
            "eu-west-1",
        )
        is True
    )

    mock_restore.assert_called_once_with(
        client,
        "bucket",
        state["configuration"],
    )

    mock_delete.assert_called_once_with(
        "s3_public_access",
        "bucket",
    )


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.info")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_public_access_block")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_client")
def test_capture_current_public_access_present(
    mock_get_client,
    mock_get_block,
    mock_info,
):

    mock_get_block.return_value = {
        "BlockPublicAcls": True,
    }

    capture_current_public_access(
        "bucket",
        "eu-west-1",
    )

    mock_info.assert_called_once_with("Original Public Access Block captured.")


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.load_state")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_public_access_actions.get_client")
def test_restore_rejects_state_from_a_different_bucket(mock_get_client, mock_load_state):
    mock_load_state.return_value = {"bucket": "other-bucket", "configuration": {}}

    import pytest

    with pytest.raises(RuntimeError, match="does not match"):
        restore_original_public_access("bucket", "eu-west-1")


def test_public_access_experiment_can_run_twice_with_bucket_scoped_state(monkeypatch, tmp_path):
    from chaosforge.providers.aws.components.s3.experiments.toolkit.actions import (
        s3_common,
        s3_public_access_actions,
    )

    client = type("Client", (), {})()
    client.get_public_access_block = lambda **_kwargs: {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
    }
    client.put_public_access_block = lambda **_kwargs: None
    monkeypatch.setattr(s3_public_access_actions, "get_client", lambda _region: client)
    monkeypatch.setattr(s3_common.tempfile, "gettempdir", lambda: str(tmp_path))

    for _ in range(2):
        assert capture_current_public_access("bucket", "eu-west-1") is True
        assert update_public_access("bucket", "eu-west-1") is True
        assert restore_original_public_access("bucket", "eu-west-1") is True

    assert not (tmp_path / "s3_public_access-bucket.json").exists()
