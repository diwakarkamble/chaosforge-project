from importlib import import_module
from unittest.mock import MagicMock, mock_open, patch

import pytest

actions = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions"
)
capture_current_timeout = actions.capture_current_timeout
restore_timeout = actions.restore_timeout
update_timeout = actions.update_timeout
wait_for_duration = actions.wait_for_duration
waiter_for_update = actions.waiter_for_update


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.boto3.client")
def test_capture_current_timeout(mock_client, mock_open_file, mock_dump, mock_print):

    client = MagicMock()

    client.get_function_configuration.return_value = {"Timeout": 30}

    mock_client.return_value = client

    capture_current_timeout("my-function", "eu-central-1")

    client.get_function_configuration.assert_called_once()

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.time.sleep")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):

    wait_for_duration("5")

    mock_sleep.assert_called_once_with(5.0)


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.waiter_for_update")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.boto3.client")
def test_update_timeout(mock_client, mock_waiter, mock_print):

    client = MagicMock()

    client.get_function_configuration.return_value = {"Timeout": 15}

    mock_client.return_value = client

    update_timeout("my-function", "60", "eu-central-1")

    client.update_function_configuration.assert_called_once_with(
        FunctionName="my-function", Timeout=60
    )

    mock_waiter.assert_called_once_with(client, "my-function")


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.waiter_for_update")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.boto3.client")
def test_restore_timeout(
    mock_client, mock_open_file, mock_load, mock_waiter, mock_print
):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"original_timeout": 25}

    restore_timeout("my-function", "eu-central-1")

    client.update_function_configuration.assert_called_once_with(
        FunctionName="my-function", Timeout=25
    )

    mock_waiter.assert_called_once_with(client, "my-function")


def test_waiter_success():

    client = MagicMock()

    client.get_function_configuration.return_value = {"LastUpdateStatus": "Successful"}

    waiter_for_update(client, "my-function")

    client.get_function_configuration.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.time.sleep")
def test_waiter_in_progress_then_success(mock_sleep):

    client = MagicMock()

    client.get_function_configuration.side_effect = [
        {"LastUpdateStatus": "InProgress"},
        {"LastUpdateStatus": "Successful"},
    ]

    waiter_for_update(client, "my-function")

    mock_sleep.assert_called_once_with(2)


def test_waiter_failed():

    client = MagicMock()

    client.get_function_configuration.return_value = {
        "LastUpdateStatus": "Failed",
        "LastUpdateStatusReason": "Access Denied",
    }

    with pytest.raises(RuntimeError):
        waiter_for_update(client, "my-function")


def test_waiter_default_success():

    client = MagicMock()

    client.get_function_configuration.return_value = {}

    waiter_for_update(client, "my-function")

    client.get_function_configuration.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.time.sleep")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_timeout_actions.print")
def test_waiter_timeout(mock_print, mock_sleep):

    client = MagicMock()

    client.get_function_configuration.return_value = {"LastUpdateStatus": "InProgress"}

    waiter_for_update(client, "my-function")

    assert client.get_function_configuration.call_count == 15

    assert mock_sleep.call_count == 15

    mock_print.assert_any_call("WARNING: Lambda update still in progress.")

    mock_print.assert_any_call("Continuing without waiting further.")
