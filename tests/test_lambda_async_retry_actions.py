from importlib import import_module
from unittest.mock import MagicMock, mock_open, patch

import pytest

actions = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions"
)
capture_current_retry_attempts = actions.capture_current_retry_attempts
restore_retry_attempts = actions.restore_retry_attempts
update_retry_attempts = actions.update_retry_attempts
wait_for_duration = actions.wait_for_duration


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.boto3.client")
def test_capture_current_retry_attempts(
    mock_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    client.get_function_event_invoke_config.return_value = {"MaximumRetryAttempts": 1}

    mock_client.return_value = client

    result = capture_current_retry_attempts("my-function", "eu-central-1")

    assert result["original_retry_attempts"] == 1

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.boto3.client")
def test_capture_retry_default_when_not_found(
    mock_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    class ResourceNotFound(Exception):
        pass

    client.exceptions.ResourceNotFoundException = ResourceNotFound

    client.get_function_event_invoke_config.side_effect = ResourceNotFound

    mock_client.return_value = client

    result = capture_current_retry_attempts("my-function", "eu-central-1")

    assert result["original_retry_attempts"] == 2


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.boto3.client")
def test_update_retry_attempts(mock_client, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    result = update_retry_attempts("my-function", "1", "eu-central-1")

    client.put_function_event_invoke_config.assert_called_once_with(
        FunctionName="my-function", MaximumRetryAttempts=1
    )

    assert result["retry_attempts"] == 1


def test_update_retry_attempts_invalid():

    with pytest.raises(ValueError):
        update_retry_attempts("my-function", "5", "eu-central-1")


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.time.sleep")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):

    result = wait_for_duration("5")

    mock_sleep.assert_called_once_with(5)

    assert result["waited_seconds"] == 5


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.boto3.client")
def test_restore_retry_attempts(mock_client, mock_open_file, mock_load, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"original_retry_attempts": 2}

    result = restore_retry_attempts("my-function", "eu-central-1")

    client.put_function_event_invoke_config.assert_called_once_with(
        FunctionName="my-function", MaximumRetryAttempts=2
    )

    assert result["restored_retry_attempts"] == 2


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.boto3.client")
def test_update_retry_attempts_zero(mock_client, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    result = update_retry_attempts("my-function", "0", "eu-central-1")

    assert result["retry_attempts"] == 0


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_async_retry_actions.boto3.client")
def test_update_retry_attempts_two(mock_client, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    result = update_retry_attempts("my-function", "2", "eu-central-1")

    assert result["retry_attempts"] == 2
