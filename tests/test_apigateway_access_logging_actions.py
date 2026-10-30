from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions import (
    capture_and_disable_access_logging,
    restore_access_logging,
)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.get_client")
def test_capture_and_disable_access_logging(
    mock_get_client, mock_get_stage, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_get_stage.return_value = {
        "accessLogSettings": {
            "destinationArn": "arn:aws:logs:::log-group",
            "format": "$context.requestId",
        }
    }

    capture_and_disable_access_logging("api-id", "dev", "eu-central-1")

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[
            {"op": "remove", "path": "/accessLogSettings/destinationArn"},
            {"op": "remove", "path": "/accessLogSettings/format"},
        ],
    )


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.get_client")
def test_access_logging_already_disabled(
    mock_get_client, mock_get_stage, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_get_stage.return_value = {}

    capture_and_disable_access_logging("api-id", "dev", "eu-central-1")

    client.update_stage.assert_not_called()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.os.path.exists")
def test_restore_state_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found."):
        restore_access_logging()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.get_client")
def test_restore_access_logging(
    mock_get_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "destinationArn": "arn:aws:logs:::log-group",
        "format": "$context.requestId",
    }

    restore_access_logging()

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[
            {
                "op": "replace",
                "path": "/accessLogSettings/destinationArn",
                "value": "arn:aws:logs:::log-group",
            },
            {
                "op": "replace",
                "path": "/accessLogSettings/format",
                "value": "$context.requestId",
            },
        ],
    )

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_access_logging_actions.get_client")
def test_restore_access_logging_no_patch(
    mock_get_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "destinationArn": None,
        "format": None,
    }

    restore_access_logging()

    client.update_stage.assert_not_called()

    mock_remove.assert_called_once()
