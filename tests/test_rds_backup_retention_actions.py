from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions import (
    capture_current_backup_retention,
    modify_backup_retention,
    restore_backup_retention,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.get_client")
def test_capture_current_backup_retention(
    mock_get_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"BackupRetentionPeriod": 7}]
    }

    mock_get_client.return_value = client

    capture_current_backup_retention("my-db", "eu-central-1")

    client.describe_db_instances.assert_called_once_with(DBInstanceIdentifier="my-db")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.get_client")
def test_modify_backup_retention(mock_get_client, mock_wait, mock_print):

    client = MagicMock()

    mock_get_client.return_value = client

    modify_backup_retention("my-db", "eu-central-1", "14")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="my-db", BackupRetentionPeriod=14, ApplyImmediately=True
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "my-db")
    assert kwargs["expected_instance"]({"BackupRetentionPeriod": 14}) is True
    assert kwargs["expected_instance"]({"BackupRetentionPeriod": 7}) is False


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):

    wait_for_duration("10")

    mock_sleep.assert_called_once_with(10.0)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.get_client")
def test_restore_backup_retention(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_retention": 7}

    restore_backup_retention("my-db", "eu-central-1")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="my-db", BackupRetentionPeriod=7, ApplyImmediately=True
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "my-db")
    assert kwargs["expected_instance"]({"BackupRetentionPeriod": 7}) is True
    assert kwargs["expected_instance"]({"BackupRetentionPeriod": 14}) is False


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_backup_retention_actions.get_client")
def test_modify_backup_retention_integer_conversion(
    mock_get_client, mock_wait, mock_print
):

    client = MagicMock()

    mock_get_client.return_value = client

    modify_backup_retention("my-db", "eu-central-1", "1")

    args = client.modify_db_instance.call_args.kwargs

    assert args["BackupRetentionPeriod"] == 1
