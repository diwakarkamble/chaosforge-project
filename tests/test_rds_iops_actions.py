from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions import (
    capture_and_reduce_iops,
    rollback_iops,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.remove")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.path.exists", return_value=True)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_capture_and_reduce_iops(
    mock_get_client, mock_exists, mock_remove, mock_open_file, mock_dump, mock_wait, mock_print
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"StorageType": "io1", "AllocatedStorage": 100, "Iops": 4000}]
    }

    mock_get_client.return_value = client

    capture_and_reduce_iops("db1", "eu-central-1", "50")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", AllocatedStorage=100, Iops=2000, ApplyImmediately=True
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "db1")
    assert kwargs["expected_instance"]({"Iops": 2000}) is True
    assert kwargs["expected_instance"]({"Iops": 4000}) is False

    mock_dump.assert_called_once()
    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_invalid_storage_type(mock_get_client):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"StorageType": "gp2", "Iops": 3000}]
    }

    mock_get_client.return_value = client

    with pytest.raises(Exception, match="does not support Provisioned IOPS"):
        capture_and_reduce_iops("db1", "eu-central-1", "50")


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_iops_already_minimum(mock_get_client):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"StorageType": "io1", "Iops": 1000}]
    }

    mock_get_client.return_value = client

    with pytest.raises(Exception, match="cannot be reduced below 1000"):
        capture_and_reduce_iops("db1", "eu-central-1", "50")


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_target_not_lower_than_current(mock_get_client):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"StorageType": "io1", "Iops": 2000}]
    }

    mock_get_client.return_value = client

    with pytest.raises(Exception, match="must be lower than current"):
        capture_and_reduce_iops("db1", "eu-central-1", "100")


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_target_iops_clamped(
    mock_get_client, mock_open_file, mock_dump, mock_wait, mock_print
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"StorageType": "io1", "AllocatedStorage": 100, "Iops": 1500}]
    }

    mock_get_client.return_value = client

    capture_and_reduce_iops("db1", "eu-central-1", "10")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", AllocatedStorage=100, Iops=1000, ApplyImmediately=True
    )


@patch("time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("20")

    mock_sleep.assert_called_once_with(20.0)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.remove")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_rollback_iops(
    mock_get_client,
    mock_exists,
    mock_open_file,
    mock_load,
    mock_wait,
    mock_remove,
    mock_print,
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {
        "db_instance_identifier": "db1",
        "region": "eu-central-1",
        "original_iops": 4000,
        "allocated_storage": 100,
    }

    rollback_iops()

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", AllocatedStorage=100, Iops=4000, ApplyImmediately=True
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "db1")
    assert kwargs["expected_instance"]({"Iops": 4000}) is True

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.remove")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.path.exists", return_value=True)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_rollback_iops_recovers_legacy_journal_without_allocated_storage(
    mock_get_client,
    mock_exists,
    mock_open_file,
    mock_load,
    mock_wait,
    mock_remove,
    mock_print,
):
    client = MagicMock()
    client.describe_db_instances.return_value = {"DBInstances": [{"AllocatedStorage": 100}]}
    mock_get_client.return_value = client
    mock_load.return_value = {
        "db_instance_identifier": "db1",
        "region": "eu-central-1",
        "original_iops": 2000,
    }

    rollback_iops()

    client.describe_db_instances.assert_called_once_with(DBInstanceIdentifier="db1")
    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", AllocatedStorage=100, Iops=2000, ApplyImmediately=True
    )


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.print")
def test_rollback_skips_when_iops_was_not_changed(mock_print, mock_exists):
    mock_exists.return_value = False

    rollback_iops()

    mock_print.assert_called_once_with("IOPS was not changed; rollback skipped.")


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.remove")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_iops_actions.get_client")
def test_rollback_region(
    mock_get_client,
    mock_exists,
    mock_open_file,
    mock_load,
    mock_wait,
    mock_remove,
    mock_print,
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {
        "db_instance_identifier": "db1",
        "region": "ap-south-1",
        "original_iops": 5000,
        "allocated_storage": 100,
    }

    rollback_iops()

    mock_get_client.assert_called_once_with("ap-south-1")
