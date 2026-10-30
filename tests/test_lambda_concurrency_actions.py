from importlib import import_module
from unittest.mock import MagicMock, mock_open, patch

import pytest
from botocore.exceptions import ClientError

actions = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions"
)
capture_current_concurrency = actions.capture_current_concurrency
restore_concurrency = actions.restore_concurrency
update_concurrency = actions.update_concurrency
wait_for_duration = actions.wait_for_duration


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_capture_current_concurrency(
    mock_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    client.get_function_concurrency.return_value = {"ReservedConcurrentExecutions": 25}

    client.list_provisioned_concurrency_configs.return_value = {
        "ProvisionedConcurrencyConfigs": [
            {"Qualifier": "LIVE", "AllocatedProvisionedConcurrentExecutions": 10}
        ]
    }

    mock_client.return_value = client

    result = capture_current_concurrency("my-function", "eu-central-1")

    assert result["had_reserved_concurrency"] is True
    assert result["original_concurrency"] == 25
    assert len(result["original_provisioned"]) == 1


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_capture_unlimited_concurrency(
    mock_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    class ResourceNotFound(Exception):
        pass

    client.exceptions.ResourceNotFoundException = ResourceNotFound

    client.get_function_concurrency.side_effect = ResourceNotFound

    client.list_provisioned_concurrency_configs.return_value = {
        "ProvisionedConcurrencyConfigs": []
    }

    mock_client.return_value = client

    result = capture_current_concurrency("my-function", "eu-central-1")

    assert result["had_reserved_concurrency"] is False
    assert result["original_concurrency"] is None


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_capture_provisioned_exception(
    mock_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    client.get_function_concurrency.return_value = {"ReservedConcurrentExecutions": 5}

    client.list_provisioned_concurrency_configs.side_effect = ClientError(
        {
            "Error": {
                "Code": "ValidationException",
                "Message": "boom",
            }
        },
        "ListProvisionedConcurrencyConfigs",
    )

    mock_client.return_value = client

    result = capture_current_concurrency("my-function", "eu-central-1")

    assert result["original_concurrency"] == 5
    assert result["original_provisioned"] == []


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_update_concurrency(mock_client, mock_open_file, mock_load, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"original_provisioned": []}

    client.list_provisioned_concurrency_configs.return_value = {
        "ProvisionedConcurrencyConfigs": []
    }

    result = update_concurrency("my-function", "10", "eu-central-1")

    client.delete_function_concurrency.assert_called_once()

    client.put_function_concurrency.assert_called_once_with(
        FunctionName="my-function", ReservedConcurrentExecutions=10
    )

    assert result["new_concurrency"] == 10


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_update_concurrency_unlimited(
    mock_client, mock_open_file, mock_load, mock_print
):

    client = MagicMock()

    class ResourceNotFound(Exception):
        pass

    client.exceptions.ResourceNotFoundException = ResourceNotFound

    client.delete_function_concurrency.side_effect = ResourceNotFound

    client.list_provisioned_concurrency_configs.return_value = {
        "ProvisionedConcurrencyConfigs": []
    }

    mock_client.return_value = client

    mock_load.return_value = {"original_provisioned": []}

    update_concurrency("my-function", "5", "eu-central-1")

    client.put_function_concurrency.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_update_concurrency_runtime_error(mock_client, mock_open_file, mock_load):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"original_provisioned": []}

    client.list_provisioned_concurrency_configs.return_value = {
        "ProvisionedConcurrencyConfigs": [
            {"AllocatedProvisionedConcurrentExecutions": 25}
        ]
    }

    with pytest.raises(RuntimeError):
        update_concurrency("my-function", "10", "eu-central-1")


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.time.sleep")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):

    result = wait_for_duration("5")

    mock_sleep.assert_called_once_with(5.0)

    assert result["waited_seconds"] == 5.0


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_restore_concurrency(mock_client, mock_open_file, mock_load, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "had_reserved_concurrency": True,
        "original_concurrency": 20,
        "original_provisioned": [],
    }

    result = restore_concurrency("my-function", "eu-central-1")

    client.put_function_concurrency.assert_called_once_with(
        FunctionName="my-function", ReservedConcurrentExecutions=20
    )

    assert result is True


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_restore_unlimited(mock_client, mock_open_file, mock_load, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "had_reserved_concurrency": False,
        "original_concurrency": None,
        "original_provisioned": [],
    }

    restore_concurrency("my-function", "eu-central-1")

    client.delete_function_concurrency.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_restore_provisioned(mock_client, mock_open_file, mock_load, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "had_reserved_concurrency": True,
        "original_concurrency": 15,
        "original_provisioned": [{"Qualifier": "LIVE", "Allocated": 8}],
    }

    restore_concurrency("my-function", "eu-central-1")

    client.put_provisioned_concurrency_config.assert_called_once_with(
        FunctionName="my-function", Qualifier="LIVE", ProvisionedConcurrentExecutions=8
    )


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_restore_provisioned_exception(
    mock_client, mock_open_file, mock_load, mock_print
):

    client = MagicMock()

    client.put_provisioned_concurrency_config.side_effect = ClientError(
        {
            "Error": {
                "Code": "ValidationException",
                "Message": "boom",
            }
        },
        "PutProvisionedConcurrencyConfig",
    )

    mock_client.return_value = client

    mock_load.return_value = {
        "had_reserved_concurrency": True,
        "original_concurrency": 15,
        "original_provisioned": [{"Qualifier": "LIVE", "Allocated": 8}],
    }

    assert restore_concurrency("my-function", "eu-central-1") is True


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.time.sleep")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_update_concurrency_wait_for_provisioned_delete(
    mock_client, mock_open_file, mock_load, mock_print, mock_sleep
):

    client = MagicMock()

    class NotFound(Exception):
        pass

    client.exceptions.ResourceNotFoundException = Exception
    client.exceptions.ProvisionedConcurrencyConfigNotFoundException = NotFound

    mock_client.return_value = client

    mock_load.return_value = {"original_provisioned": [{"Qualifier": "LIVE"}]}

    client.get_provisioned_concurrency_config.side_effect = [
        {"Status": "IN_PROGRESS"},
        NotFound(),
    ]

    client.list_provisioned_concurrency_configs.return_value = {
        "ProvisionedConcurrencyConfigs": []
    }

    update_concurrency("my-function", "5", "eu-central-1")

    assert mock_sleep.called


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_concurrency_actions.boto3.client")
def test_update_concurrency_multiple_provisioned(
    mock_client, mock_open_file, mock_load, mock_print
):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"original_provisioned": []}

    client.list_provisioned_concurrency_configs.return_value = {
        "ProvisionedConcurrencyConfigs": [
            {"AllocatedProvisionedConcurrentExecutions": 2},
            {"AllocatedProvisionedConcurrentExecutions": 3},
        ]
    }

    result = update_concurrency("my-function", "10", "eu-central-1")

    assert result["new_concurrency"] == 10
