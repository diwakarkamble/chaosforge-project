from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions import (
    capture_current_auto_minor_upgrade,
    restore_auto_minor_upgrade,
    update_auto_minor_upgrade,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.get_client")
def test_capture_current_auto_minor_upgrade(
    mock_get_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"AutoMinorVersionUpgrade": True}]
    }

    mock_get_client.return_value = client

    capture_current_auto_minor_upgrade("my-db", "eu-central-1")

    client.describe_db_instances.assert_called_once_with(DBInstanceIdentifier="my-db")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.get_client")
def test_update_auto_minor_upgrade_true(mock_get_client, mock_wait, mock_print):

    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"AutoMinorVersionUpgrade": False}]
    }

    mock_get_client.return_value = client

    update_auto_minor_upgrade("my-db", "eu-central-1", "true")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="my-db",
        AutoMinorVersionUpgrade=True,
        ApplyImmediately=True,
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "my-db")
    assert kwargs["expected_instance"]({"AutoMinorVersionUpgrade": True}) is True
    assert kwargs["expected_instance"]({"AutoMinorVersionUpgrade": False}) is False


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.get_client")
def test_update_auto_minor_upgrade_false(mock_get_client, mock_wait, mock_print):

    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"AutoMinorVersionUpgrade": True}]
    }

    mock_get_client.return_value = client

    update_auto_minor_upgrade("my-db", "eu-central-1", "false")

    args = client.modify_db_instance.call_args.kwargs

    assert args["AutoMinorVersionUpgrade"] is False
    wait_args, wait_kwargs = mock_wait.call_args
    assert wait_args == (client, "my-db")
    assert wait_kwargs["expected_instance"]({"AutoMinorVersionUpgrade": False}) is True


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.get_client")
def test_update_auto_minor_upgrade_rejects_no_op_target(mock_get_client):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"AutoMinorVersionUpgrade": True}]
    }
    mock_get_client.return_value = client

    import pytest

    with pytest.raises(ValueError, match=r"already matches the current value \(True\)"):
        update_auto_minor_upgrade("my-db", "eu-central-1", "true")
    client.modify_db_instance.assert_not_called()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):

    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15.0)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.get_client")
def test_restore_auto_minor_upgrade(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_value": True}
    client.describe_db_instances.return_value = {
        "DBInstances": [{"AutoMinorVersionUpgrade": False}]
    }

    restore_auto_minor_upgrade("my-db", "eu-central-1")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="my-db",
        AutoMinorVersionUpgrade=True,
        ApplyImmediately=True,
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "my-db")
    assert kwargs["expected_instance"]({"AutoMinorVersionUpgrade": True}) is True


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.get_client")
def test_restore_auto_minor_upgrade_false(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_value": False}
    client.describe_db_instances.return_value = {
        "DBInstances": [{"AutoMinorVersionUpgrade": True}]
    }

    restore_auto_minor_upgrade("my-db", "eu-central-1")

    args = client.modify_db_instance.call_args.kwargs

    assert args["AutoMinorVersionUpgrade"] is False


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_auto_minor_version_upgrade_actions.get_client")
def test_restore_auto_minor_upgrade_skips_no_op_failure(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    mock_load.return_value = {"original_value": True}
    mock_get_client.return_value.describe_db_instances.return_value = {
        "DBInstances": [{"AutoMinorVersionUpgrade": True}]
    }

    restore_auto_minor_upgrade("my-db", "eu-central-1")

    mock_get_client.assert_called_once_with("eu-central-1")
    mock_get_client.return_value.modify_db_instance.assert_not_called()
    mock_wait.assert_not_called()
    mock_print.assert_called_once_with(
        "Auto Minor Version Upgrade was not changed; rollback skipped."
    )
