from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions import (
    capture_current_capacity,
    restore_capacity,
    update_capacity,
    wait_for_duration,
    wait_until_active,
)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions._client")
def test_capture_current_capacity(mock_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_table.return_value = {
        "Table": {
            "ProvisionedThroughput": {
                "ReadCapacityUnits": 100,
                "WriteCapacityUnits": 50,
            }
        }
    }

    mock_client.return_value = client

    capture_current_capacity("table1", "eu-central-1")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions._client")
def test_capture_pay_per_request(mock_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_table.return_value = {
        "Table": {"BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"}}
    }

    mock_client.return_value = client

    capture_current_capacity("table1", "eu-central-1")

    mock_dump.assert_called_once_with({"skip": True}, mock_open_file())


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("20")

    mock_sleep.assert_called_once_with(20.0)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.wait_until_active")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions._client")
def test_update_capacity(mock_client, mock_open_file, mock_load, mock_wait, mock_print):
    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"skip": False, "read": 100, "write": 50}

    update_capacity("table1", "eu-central-1", 10, 5)

    client.update_table.assert_called_once_with(
        TableName="table1",
        ProvisionedThroughput={"ReadCapacityUnits": 10, "WriteCapacityUnits": 5},
    )

    mock_wait.assert_called_once_with(client, "table1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.open", new_callable=mock_open)
def test_update_capacity_skip(mock_open_file, mock_load, mock_print):
    mock_load.return_value = {"skip": True}

    update_capacity("table1", "eu-central-1", 1, 1)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.wait_until_active")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions._client")
def test_restore_capacity(
    mock_client, mock_open_file, mock_load, mock_wait, mock_print
):
    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"skip": False, "read": 100, "write": 50}

    restore_capacity("table1", "eu-central-1")

    client.update_table.assert_called_once_with(
        TableName="table1",
        ProvisionedThroughput={"ReadCapacityUnits": 100, "WriteCapacityUnits": 50},
    )

    mock_wait.assert_called_once_with(client, "table1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.open", new_callable=mock_open)
def test_restore_capacity_skip(mock_open_file, mock_load, mock_print):
    mock_load.return_value = {"skip": True}

    restore_capacity("table1", "eu-central-1")


def test_wait_until_active():
    client = MagicMock()

    client.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE"}}

    wait_until_active(client, "table1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
def test_wait_until_active_retry(mock_print, mock_sleep):
    client = MagicMock()

    client.describe_table.side_effect = [
        {"Table": {"TableStatus": "UPDATING"}},
        {"Table": {"TableStatus": "ACTIVE"}},
    ]

    wait_until_active(client, "table1")

    mock_sleep.assert_called_once_with(5)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions._client")
def test_default_billing_mode(mock_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_table.return_value = {
        "Table": {
            "ProvisionedThroughput": {"ReadCapacityUnits": 10, "WriteCapacityUnits": 5}
        }
    }

    mock_client.return_value = client

    capture_current_capacity("table1", "eu-central-1")

    mock_dump.assert_called_once()


from unittest.mock import patch

from chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions import (
    _client,
)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_capacity_actions.boto3.client")
def test_client(mock_boto_client):
    fake_client = MagicMock()
    mock_boto_client.return_value = fake_client

    result = _client("eu-central-1")

    mock_boto_client.assert_called_once_with("dynamodb", region_name="eu-central-1")

    assert result == fake_client
