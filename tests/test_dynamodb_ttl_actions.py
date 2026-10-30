from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions import (
    capture_current_ttl,
    disable_ttl,
    get_client,
    restore_ttl,
    wait_for_duration,
    wait_for_ttl_status,
)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.boto3.client")
def test_get_client(mock_boto_client):
    fake = MagicMock()

    mock_boto_client.return_value = fake

    result = get_client("eu-central-1")

    mock_boto_client.assert_called_once_with("dynamodb", region_name="eu-central-1")

    assert result == fake


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.get_client")
def test_capture_current_ttl(mock_get_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_time_to_live.return_value = {
        "TimeToLiveDescription": {"TimeToLiveStatus": "ENABLED", "AttributeName": "ttl"}
    }

    mock_get_client.return_value = client

    capture_current_ttl("table1", "eu-central-1")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.get_client")
def test_capture_default_values(mock_get_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_time_to_live.return_value = {"TimeToLiveDescription": {}}

    mock_get_client.return_value = client

    capture_current_ttl("table1", "eu-central-1")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15.0)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.wait_for_ttl_status")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.get_client")
def test_disable_ttl(mock_get_client, mock_open_file, mock_load, mock_wait, mock_print):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_status": "ENABLED", "attribute_name": "ttl"}

    disable_ttl("table1", "eu-central-1")

    client.update_time_to_live.assert_called_once_with(
        TableName="table1",
        TimeToLiveSpecification={"Enabled": False, "AttributeName": "ttl"},
    )

    mock_wait.assert_called_once_with(client, "table1", "DISABLED")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.get_client")
def test_disable_already_disabled(
    mock_get_client, mock_open_file, mock_load, mock_print
):
    mock_load.return_value = {"original_status": "DISABLED"}

    disable_ttl("table1", "eu-central-1")

    mock_get_client.assert_not_called()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.wait_for_ttl_status")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.get_client")
def test_restore_ttl(mock_get_client, mock_open_file, mock_load, mock_wait, mock_print):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_status": "ENABLED", "attribute_name": "ttl"}

    restore_ttl("table1", "eu-central-1")

    client.update_time_to_live.assert_called_once_with(
        TableName="table1",
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )

    mock_wait.assert_called_once_with(client, "table1", "ENABLED")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.get_client")
def test_restore_disabled(mock_get_client, mock_open_file, mock_load, mock_print):
    mock_load.return_value = {"original_status": "DISABLED"}

    restore_ttl("table1", "eu-central-1")

    mock_get_client.assert_not_called()


def test_wait_for_ttl_status():
    client = MagicMock()

    client.describe_time_to_live.return_value = {
        "TimeToLiveDescription": {"TimeToLiveStatus": "ENABLED"}
    }

    wait_for_ttl_status(client, "table1", "ENABLED")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_ttl_actions.print")
def test_wait_for_ttl_status_retry(mock_print, mock_sleep):
    client = MagicMock()

    client.describe_time_to_live.side_effect = [
        {"TimeToLiveDescription": {"TimeToLiveStatus": "DISABLING"}},
        {"TimeToLiveDescription": {"TimeToLiveStatus": "DISABLED"}},
    ]

    wait_for_ttl_status(client, "table1", "DISABLED")

    mock_sleep.assert_called_once_with(5)
