from importlib import import_module
from unittest.mock import MagicMock, mock_open, patch

import pytest

actions = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions"
)
capture_current_memory = actions.capture_current_memory
restore_memory = actions.restore_memory
update_memory = actions.update_memory
wait_for_duration = actions.wait_for_duration
waiter_for_update = actions.waiter_for_update


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.boto3.client")
def test_capture_current_memory(mock_client, mock_open_file, mock_dump, mock_print):

    client = MagicMock()

    client.get_function_configuration.return_value = {"MemorySize": 512}

    mock_client.return_value = client

    capture_current_memory("my-function", "eu-central-1")

    client.get_function_configuration.assert_called_once()

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.time.sleep")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):

    wait_for_duration("2")

    mock_sleep.assert_called_once_with(2.0)


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.waiter_for_update")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.boto3.client")
def test_update_memory(mock_client, mock_waiter, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    update_memory("my-function", "1024", "eu-central-1")

    client.update_function_configuration.assert_called_once()

    mock_waiter.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.waiter_for_update")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.boto3.client")
def test_restore_memory(
    mock_client, mock_open_file, mock_load, mock_waiter, mock_print
):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"original_memory": 512}

    restore_memory("my-function", "eu-central-1")

    client.update_function_configuration.assert_called_once_with(
        FunctionName="my-function", MemorySize=512
    )

    mock_waiter.assert_called_once()


def test_waiter_success():

    client = MagicMock()

    client.get_function_configuration.return_value = {"LastUpdateStatus": "Successful"}

    waiter_for_update(client, "my-function")

    client.get_function_configuration.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_memory_actions.time.sleep")
def test_waiter_running_then_success(mock_sleep):

    client = MagicMock()

    client.get_function_configuration.side_effect = [
        {"LastUpdateStatus": "InProgress"},
        {"LastUpdateStatus": "Successful"},
    ]

    waiter_for_update(client, "my-function")

    mock_sleep.assert_called_once_with(5)


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
