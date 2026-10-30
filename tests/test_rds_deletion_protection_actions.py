from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions import (
    capture_current_deletion_protection,
    restore_deletion_protection,
    update_deletion_protection,
    wait_for_deletion_protection,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.get_client")
def test_capture_current_deletion_protection(
    mock_get_client, mock_open_file, mock_dump, mock_print
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"DeletionProtection": True}]
    }

    mock_get_client.return_value = client

    capture_current_deletion_protection("db1", "eu-central-1")

    client.describe_db_instances.assert_called_once_with(DBInstanceIdentifier="db1")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.print")
def test_wait_for_deletion_protection(mock_print):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"DeletionProtection": True, "DBInstanceStatus": "available"}]
    }

    wait_for_deletion_protection(client, "db1", True)

    client.describe_db_instances.assert_called_once()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.print")
def test_wait_for_deletion_protection_retry(mock_print, mock_sleep):
    client = MagicMock()

    client.describe_db_instances.side_effect = [
        {
            "DBInstances": [
                {"DeletionProtection": False, "DBInstanceStatus": "modifying"}
            ]
        },
        {
            "DBInstances": [
                {"DeletionProtection": True, "DBInstanceStatus": "available"}
            ]
        },
    ]

    wait_for_deletion_protection(client, "db1", True)

    assert client.describe_db_instances.call_count == 2
    mock_sleep.assert_called_once_with(5)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.wait_for_deletion_protection")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.get_client")
def test_update_deletion_protection(mock_get_client, mock_wait, mock_print):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"DeletionProtection": False}]
    }

    mock_get_client.return_value = client

    update_deletion_protection("db1", "eu-central-1", "true")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", DeletionProtection=True, ApplyImmediately=True
    )

    mock_wait.assert_called_once_with(client, "db1", True)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.wait_for_deletion_protection")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.get_client")
def test_update_deletion_protection_false(mock_get_client, mock_wait, mock_print):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"DeletionProtection": True}]
    }

    mock_get_client.return_value = client

    update_deletion_protection("db1", "eu-central-1", "false")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", DeletionProtection=False, ApplyImmediately=True
    )


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.get_client")
def test_update_deletion_protection_rejects_no_op_target(mock_get_client):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"DeletionProtection": True}]
    }
    mock_get_client.return_value = client

    import pytest

    with pytest.raises(ValueError, match="already matches"):
        update_deletion_protection("db1", "eu-central-1", "true")
    client.modify_db_instance.assert_not_called()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15.0)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.wait_for_deletion_protection")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_deletion_protection_actions.get_client")
def test_restore_deletion_protection(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_value": True}

    restore_deletion_protection("db1", "eu-central-1")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", DeletionProtection=True, ApplyImmediately=True
    )

    mock_wait.assert_called_once_with(client, "db1", True)
