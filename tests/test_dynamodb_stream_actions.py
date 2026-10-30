from unittest.mock import MagicMock, mock_open, patch

from chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions import (
    capture_current_stream,
    disable_stream,
    get_client,
    restore_stream,
    wait_for_duration,
    wait_until_active,
)


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.boto3.client")
def test_get_client(mock_boto):
    client = MagicMock()

    mock_boto.return_value = client

    result = get_client("eu-central-1")

    mock_boto.assert_called_once_with("dynamodb", region_name="eu-central-1")

    assert result == client


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.get_client")
def test_capture_current_stream(mock_get_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_table.return_value = {
        "Table": {
            "StreamSpecification": {
                "StreamEnabled": True,
                "StreamViewType": "NEW_AND_OLD_IMAGES",
            }
        }
    }

    mock_get_client.return_value = client

    capture_current_stream("table1", "eu-central-1")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.json.dump")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.get_client")
def test_capture_stream_disabled(
    mock_get_client, mock_open_file, mock_dump, mock_print
):
    client = MagicMock()

    client.describe_table.return_value = {"Table": {}}

    mock_get_client.return_value = client

    capture_current_stream("table1", "eu-central-1")

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.wait_until_active")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.get_client")
def test_disable_stream(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"stream_enabled": True, "stream_view_type": "NEW_IMAGE"}

    disable_stream("table1", "eu-central-1")

    client.update_table.assert_called_once_with(
        TableName="table1", StreamSpecification={"StreamEnabled": False}
    )

    mock_wait.assert_called_once_with(client, "table1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.open", new_callable=mock_open)
def test_disable_already_disabled(mock_open_file, mock_load, mock_print):
    mock_load.return_value = {"stream_enabled": False}

    disable_stream("table1", "eu-central-1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.wait_until_active")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.get_client")
def test_restore_stream(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"stream_enabled": True, "stream_view_type": "NEW_IMAGE"}

    restore_stream("table1", "eu-central-1")

    client.update_table.assert_called_once_with(
        TableName="table1",
        StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"},
    )

    mock_wait.assert_called_once_with(client, "table1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.json.load")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.open", new_callable=mock_open)
def test_restore_nothing(mock_open_file, mock_load, mock_print):
    mock_load.return_value = {"stream_enabled": False}

    restore_stream("table1", "eu-central-1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("10")

    mock_sleep.assert_called_once_with(10.0)


def test_wait_until_active():
    client = MagicMock()

    client.describe_table.return_value = {"Table": {"TableStatus": "ACTIVE"}}

    wait_until_active(client, "table1")


@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.time.sleep")
@patch("chaosforge.providers.aws.components.dynamodb.experiments.toolkit.actions.dynamodb_stream_actions.print")
def test_wait_until_active_retry(mock_print, mock_sleep):
    client = MagicMock()

    client.describe_table.side_effect = [
        {"Table": {"TableStatus": "UPDATING"}},
        {"Table": {"TableStatus": "ACTIVE"}},
    ]

    wait_until_active(client, "table1")

    mock_sleep.assert_called_once_with(5)
