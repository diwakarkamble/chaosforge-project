from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions import (
    capture_and_update_throttling,
    rollback_throttling,
)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.get_client")
def test_capture_and_update_throttling(
    mock_get_client, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    client.get_stage.return_value = {
        "methodSettings": {
            "*/*": {"throttlingRateLimit": 1000, "throttlingBurstLimit": 500}
        }
    }

    capture_and_update_throttling("api-id", "dev", "eu-central-1", 100, 50)

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[
            {"op": "replace", "path": "/*/*/throttling/rateLimit", "value": "100"},
            {"op": "replace", "path": "/*/*/throttling/burstLimit", "value": "50"},
        ],
    )


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.get_client")
def test_default_throttling_values(
    mock_get_client, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    client.get_stage.return_value = {}

    capture_and_update_throttling("api-id", "dev", "eu-central-1", 200, 100)

    client.update_stage.assert_called_once()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.os.path.exists")
def test_rollback_state_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found."):
        rollback_throttling()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.get_client")
def test_rollback_throttling(
    mock_get_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "rate": 1000,
        "burst": 500,
    }

    rollback_throttling()

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[
            {"op": "replace", "path": "/*/*/throttling/rateLimit", "value": "1000"},
            {"op": "replace", "path": "/*/*/throttling/burstLimit", "value": "500"},
        ],
    )

    mock_remove.assert_called_once()


from unittest.mock import patch

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions import (
    get_client,
)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_throttling_actions.boto3.client")
def test_get_client(mock_boto_client):
    client = MagicMock()

    mock_boto_client.return_value = client

    result = get_client("eu-central-1")

    mock_boto_client.assert_called_once_with("apigateway", region_name="eu-central-1")

    assert result == client
