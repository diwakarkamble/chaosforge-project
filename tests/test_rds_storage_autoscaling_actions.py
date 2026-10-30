from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions import (
    capture_and_reduce_max_allocated_storage,
    rollback_max_allocated_storage,
    wait_for_duration,
    wait_for_max_allocated_storage,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.wait_for_max_allocated_storage")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.get_client")
def test_capture_and_reduce_storage(
    mock_get_client, mock_open_file, mock_dump, mock_wait, mock_print
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"AllocatedStorage": 100, "MaxAllocatedStorage": 200}]
    }

    mock_get_client.return_value = client

    capture_and_reduce_max_allocated_storage("db1", "eu-central-1", "50")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", MaxAllocatedStorage=100, ApplyImmediately=True
    )

    mock_wait.assert_called_once_with(client, "db1", 100)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.get_client")
def test_storage_autoscaling_not_enabled(mock_get_client):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"AllocatedStorage": 100}]
    }

    mock_get_client.return_value = client

    with pytest.raises(Exception, match="Storage Autoscaling is not enabled"):
        capture_and_reduce_max_allocated_storage("db1", "eu-central-1", "50")


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.wait_for_max_allocated_storage")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.get_client")
def test_target_storage_adjusted(
    mock_get_client, mock_open_file, mock_dump, mock_wait, mock_print
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"AllocatedStorage": 100, "MaxAllocatedStorage": 120}]
    }

    mock_get_client.return_value = client

    capture_and_reduce_max_allocated_storage("db1", "eu-central-1", "50")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", MaxAllocatedStorage=100, ApplyImmediately=True
    )


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.print")
def test_wait_for_max_allocated_storage(mock_print):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"MaxAllocatedStorage": 100, "DBInstanceStatus": "available"}]
    }

    wait_for_max_allocated_storage(client, "db1", 100)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.print")
def test_wait_retry(mock_print, mock_sleep):
    client = MagicMock()

    client.describe_db_instances.side_effect = [
        {
            "DBInstances": [
                {"MaxAllocatedStorage": 150, "DBInstanceStatus": "modifying"}
            ]
        },
        {
            "DBInstances": [
                {"MaxAllocatedStorage": 100, "DBInstanceStatus": "available"}
            ]
        },
    ]

    wait_for_max_allocated_storage(client, "db1", 100)

    mock_sleep.assert_called_once_with(5)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15.0)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.os.remove")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.wait_for_max_allocated_storage")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.get_client")
def test_rollback_storage(
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
        "original_max_storage": 200,
    }

    rollback_max_allocated_storage()

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", MaxAllocatedStorage=200, ApplyImmediately=True
    )

    mock_wait.assert_called_once_with(client, "db1", 200)

    mock_remove.assert_called_once()


from unittest.mock import patch


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_storage_autoscaling_actions.os.path.exists")
def test_rollback_storage_state_file_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found."):
        rollback_max_allocated_storage()
