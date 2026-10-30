from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions import (
    capture_and_change_parameter_group,
    rollback_parameter_group,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.get_client")
def test_capture_and_change_parameter_group(
    mock_get_client, mock_open_file, mock_dump, mock_wait, mock_print
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"DBParameterGroups": [{"DBParameterGroupName": "default-pg"}]}]
    }

    mock_get_client.return_value = client

    capture_and_change_parameter_group("db1", "eu-central-1", "chaos-pg")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1",
        DBParameterGroupName="chaos-pg",
        ApplyImmediately=True,
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "db1")
    assert kwargs["expected_instance"](
        {"DBParameterGroups": [{"DBParameterGroupName": "chaos-pg"}]}
    ) is True

    mock_dump.assert_called_once()


@patch("time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15.0)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.os.remove")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.get_client")
def test_rollback_parameter_group(
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
        "original_parameter_group": "default-pg",
    }

    rollback_parameter_group()

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1",
        DBParameterGroupName="default-pg",
        ApplyImmediately=True,
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "db1")
    assert kwargs["expected_instance"](
        {"DBParameterGroups": [{"DBParameterGroupName": "default-pg"}]}
    ) is True

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.os.path.exists")
def test_rollback_parameter_group_state_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found"):
        rollback_parameter_group()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.os.remove")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_parameter_group_actions.get_client")
def test_rollback_parameter_group_region(
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
        "original_parameter_group": "default",
    }

    rollback_parameter_group()

    mock_get_client.assert_called_once_with("ap-south-1")
