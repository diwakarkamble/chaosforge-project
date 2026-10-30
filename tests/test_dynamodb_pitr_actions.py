from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions import (
    capture_current_pitr,
    disable_pitr,
    get_client,
    restore_pitr,
    wait_for_duration,
    wait_for_pitr_status,
)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.boto3.client")
def test_get_client(mock_boto):
    client = MagicMock()

    mock_boto.return_value = client

    result = get_client("eu-central-1")

    mock_boto.assert_called_once_with("dynamodb", region_name="eu-central-1")

    assert result == client


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.get_client")
def test_capture_current_pitr(mock_get_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_continuous_backups.return_value = {
        "ContinuousBackupsDescription": {
            "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "ENABLED"}
        }
    }

    mock_get_client.return_value = client

    capture_current_pitr("table1", "eu-central-1")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15.0)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.wait_for_pitr_status")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.get_client")
def test_disable_pitr(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_status": "ENABLED"}

    disable_pitr("table1", "eu-central-1")

    client.update_continuous_backups.assert_called_once_with(
        TableName="table1",
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": False},
    )

    mock_wait.assert_called_once_with(client, "table1", "DISABLED")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.get_client")
def test_disable_already_disabled(
    mock_get_client, mock_open_file, mock_load, mock_print
):
    mock_load.return_value = {"original_status": "DISABLED"}

    disable_pitr("table1", "eu-central-1")

    mock_get_client.assert_not_called()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.wait_for_pitr_status")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.get_client")
def test_restore_pitr(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_status": "ENABLED"}

    restore_pitr("table1", "eu-central-1")

    client.update_continuous_backups.assert_called_once_with(
        TableName="table1",
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
    )

    mock_wait.assert_called_once_with(client, "table1", "ENABLED")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.get_client")
def test_restore_nothing(mock_get_client, mock_open_file, mock_load, mock_print):
    mock_load.return_value = {"original_status": "DISABLED"}

    restore_pitr("table1", "eu-central-1")

    mock_get_client.assert_not_called()


def test_wait_for_pitr_status():
    client = MagicMock()

    client.describe_continuous_backups.return_value = {
        "ContinuousBackupsDescription": {
            "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "ENABLED"}
        }
    }

    wait_for_pitr_status(client, "table1", "ENABLED")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_pitr_actions.print")
def test_wait_for_pitr_status_retry(mock_print, mock_sleep):
    client = MagicMock()

    client.describe_continuous_backups.side_effect = [
        {
            "ContinuousBackupsDescription": {
                "PointInTimeRecoveryDescription": {
                    "PointInTimeRecoveryStatus": "DISABLING"
                }
            }
        },
        {
            "ContinuousBackupsDescription": {
                "PointInTimeRecoveryDescription": {
                    "PointInTimeRecoveryStatus": "DISABLED"
                }
            }
        },
    ]

    wait_for_pitr_status(client, "table1", "DISABLED")

    mock_sleep.assert_called_once_with(5)
