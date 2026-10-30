from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common import (
    get_client,
    wait_for_db_available,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.boto3.client")
def test_get_client(mock_boto_client):
    get_client("eu-central-1")

    mock_boto_client.assert_called_once_with("rds", region_name="eu-central-1")


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.time.sleep")
def test_wait_for_db_available_success(mock_sleep, mock_print):
    client = MagicMock()

    client.describe_db_instances.side_effect = [
        {"DBInstances": [{"DBInstanceStatus": "modifying"}]},
        {"DBInstances": [{"DBInstanceStatus": "available"}]},
    ]

    wait_for_db_available(client, "db-test")

    assert client.describe_db_instances.call_count == 2

    mock_sleep.assert_called_once_with(5)

    mock_print.assert_any_call("Modification completed.")


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.time.sleep")
def test_wait_for_db_available_timeout(mock_sleep, mock_print):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceStatus": "available"}]
    }

    with pytest.raises(
        TimeoutError, match="Timed out waiting for RDS instance db-test"
    ):
        wait_for_db_available(client, "db-test", timeout=10)

    assert client.describe_db_instances.call_count == 2

    assert mock_sleep.call_count == 2


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.time.sleep")
def test_wait_for_db_available_multiple_modifying(mock_sleep, mock_print):
    client = MagicMock()

    client.describe_db_instances.side_effect = [
        {"DBInstances": [{"DBInstanceStatus": "modifying"}]},
        {"DBInstances": [{"DBInstanceStatus": "modifying"}]},
        {"DBInstances": [{"DBInstanceStatus": "available"}]},
    ]

    wait_for_db_available(client, "db-test")

    assert client.describe_db_instances.call_count == 3

    assert mock_sleep.call_count == 2


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_common.time.sleep")
def test_wait_for_db_available_accepts_available_setting_update(mock_sleep, mock_print):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "DBInstanceStatus": "available",
                "BackupRetentionPeriod": 4,
            }
        ]
    }

    wait_for_db_available(
        client,
        "db-test",
        expected_instance=lambda instance: instance["BackupRetentionPeriod"] == 4,
    )

    client.describe_db_instances.assert_called_once_with(DBInstanceIdentifier="db-test")
    mock_sleep.assert_not_called()
    mock_print.assert_any_call("Modification completed.")
