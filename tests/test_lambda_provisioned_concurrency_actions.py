from importlib import import_module
from unittest.mock import MagicMock, mock_open, patch

actions = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions"
)
ALIAS = actions.ALIAS
capture_current_provisioned_concurrency = actions.capture_current_provisioned_concurrency
restore_provisioned_concurrency = actions.restore_provisioned_concurrency
update_provisioned_concurrency = actions.update_provisioned_concurrency
wait_for_duration = actions.wait_for_duration


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.json.dump")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.boto3.client")
def test_capture_current_provisioned_concurrency(
    mock_client, mock_open_file, mock_dump, mock_print
):

    client = MagicMock()

    client.get_provisioned_concurrency_config.return_value = {
        "RequestedProvisionedConcurrentExecutions": 15
    }

    mock_client.return_value = client

    capture_current_provisioned_concurrency("my-function", "eu-central-1")

    client.get_provisioned_concurrency_config.assert_called_once_with(
        FunctionName="my-function", Qualifier=ALIAS
    )

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.boto3.client")
def test_update_provisioned_concurrency(mock_client, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    update_provisioned_concurrency("my-function", "25", "eu-central-1")

    client.put_provisioned_concurrency_config.assert_called_once_with(
        FunctionName="my-function", Qualifier=ALIAS, ProvisionedConcurrentExecutions=25
    )


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.time.sleep")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):

    wait_for_duration("5")

    mock_sleep.assert_called_once_with(5)


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.json.load")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.boto3.client")
def test_restore_provisioned_concurrency(
    mock_client, mock_open_file, mock_load, mock_print
):

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {"value": 12}

    restore_provisioned_concurrency("my-function", "eu-central-1")

    client.put_provisioned_concurrency_config.assert_called_once_with(
        FunctionName="my-function", Qualifier=ALIAS, ProvisionedConcurrentExecutions=12
    )


@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.print")
@patch("chaosforge.providers.aws.components.lambda.experiments.toolkit.actions.lambda_provisioned_concurrency_actions.boto3.client")
def test_update_provisioned_concurrency_integer_conversion(mock_client, mock_print):

    client = MagicMock()

    mock_client.return_value = client

    update_provisioned_concurrency("my-function", "1", "eu-central-1")

    args = client.put_provisioned_concurrency_config.call_args.kwargs

    assert args["ProvisionedConcurrentExecutions"] == 1
