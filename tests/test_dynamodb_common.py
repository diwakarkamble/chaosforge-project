import json
from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common import (
    get_client,
    get_table_details,
    restore_capacity,
    save_capacity,
    verify_table,
    wait_until_active,
)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.boto3.client")
def test_get_client(mock_client):
    get_client("eu-central-1")

    mock_client.assert_called_once_with(
        "dynamodb",
        region_name="eu-central-1",
    )


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.get_client")
def test_verify_table(mock_get_client):
    client = MagicMock()

    mock_get_client.return_value = client

    assert verify_table("table1", "eu-central-1") is True

    client.describe_table.assert_called_once_with(TableName="table1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.get_client")
def test_get_table_details_provisioned(mock_get_client):
    client = MagicMock()

    client.describe_table.return_value = {
        "Table": {
            "ProvisionedThroughput": {
                "ReadCapacityUnits": 5,
                "WriteCapacityUnits": 10,
            }
        }
    }

    mock_get_client.return_value = client

    result = get_table_details(
        "table1",
        "eu-central-1",
    )

    assert result["BillingMode"] == "PROVISIONED"

    assert result["ProvisionedThroughput"]["ReadCapacityUnits"] == 5


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.get_client")
def test_get_table_details_ondemand(mock_get_client):
    client = MagicMock()

    client.describe_table.return_value = {
        "Table": {
            "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
            "ProvisionedThroughput": {},
        }
    }

    mock_get_client.return_value = client

    result = get_table_details(
        "table1",
        "eu-central-1",
    )

    assert result["BillingMode"] == "PAY_PER_REQUEST"


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.get_client")
def test_wait_until_active(
    mock_get_client,
    mock_sleep,
):
    client = MagicMock()

    client.describe_table.side_effect = [
        {"Table": {"TableStatus": "UPDATING"}},
        {"Table": {"TableStatus": "ACTIVE"}},
    ]

    mock_get_client.return_value = client

    wait_until_active(
        "table1",
        "eu-central-1",
    )

    assert client.describe_table.call_count == 2

    mock_sleep.assert_called_once_with(5)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.os.makedirs")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.json.dump")
@patch("builtins.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.get_table_details")
def test_save_capacity(
    mock_details,
    mock_file,
    mock_dump,
    mock_makedirs,
):
    mock_details.return_value = {
        "BillingMode": "PROVISIONED",
        "ProvisionedThroughput": {
            "ReadCapacityUnits": 10,
            "WriteCapacityUnits": 20,
        },
    }

    save_capacity(
        "table1",
        "eu-central-1",
    )

    mock_makedirs.assert_called_once()

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.os.makedirs")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.get_table_details")
def test_save_capacity_pay_per_request(
    mock_details,
    mock_makedirs,
):
    mock_details.return_value = {
        "BillingMode": "PAY_PER_REQUEST",
        "ProvisionedThroughput": {},
    }

    save_capacity(
        "table1",
        "eu-central-1",
    )

    mock_makedirs.assert_not_called()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.wait_until_active")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_common.get_client")
@patch(
    "builtins.open",
    new_callable=mock_open,
    read_data=json.dumps(
        {
            "ReadCapacityUnits": 11,
            "WriteCapacityUnits": 22,
        }
    ),
)
def test_restore_capacity(
    mock_file,
    mock_get_client,
    mock_wait,
):
    client = MagicMock()

    mock_get_client.return_value = client

    restore_capacity(
        "table1",
        "eu-central-1",
    )

    client.update_table.assert_called_once_with(
        TableName="table1",
        ProvisionedThroughput={
            "ReadCapacityUnits": 11,
            "WriteCapacityUnits": 22,
        },
    )

    mock_wait.assert_called_once_with(
        "table1",
        "eu-central-1",
    )
