from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions import (
    capture_and_modify_cache_ttl,
    rollback_cache_ttl,
)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.get_client")
def test_capture_and_modify_cache_ttl(
    mock_get_client, mock_get_stage, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_get_stage.return_value = {"cacheClusterSettings": {"cacheTtlInSeconds": 300}}

    capture_and_modify_cache_ttl("api-id", "dev", "eu-central-1", 60)

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[
            {"op": "replace", "path": "/*/*/caching/ttlInSeconds", "value": "60"}
        ],
    )


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.os.path.exists")
def test_rollback_state_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found."):
        rollback_cache_ttl()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.get_client")
def test_rollback_cache_ttl(
    mock_get_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "original_ttl": 300,
    }

    rollback_cache_ttl()

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[
            {"op": "replace", "path": "/*/*/caching/ttlInSeconds", "value": "300"}
        ],
    )

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_ttl_actions.get_client")
def test_default_cache_ttl(
    mock_get_client, mock_get_stage, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_get_stage.return_value = {}

    capture_and_modify_cache_ttl("api-id", "dev", "eu-central-1", 120)

    client.update_stage.assert_called_once()
