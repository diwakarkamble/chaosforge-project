from unittest.mock import patch

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions import (
    capture_current_stage_cache,
    restore_stage_cache,
    update_stage_cache,
)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.save_state")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.get_stage")
def test_capture_current_stage_cache(mock_get_stage, mock_save_state, mock_print):
    mock_get_stage.return_value = {"cacheClusterEnabled": True}

    capture_current_stage_cache("api-id", "dev", "eu-central-1")

    mock_get_stage.assert_called_once_with("api-id", "dev", "eu-central-1")

    mock_save_state.assert_called_once_with(
        "apigateway_stage_cache",
        {
            "rest_api_id": "api-id",
            "stage_name": "dev",
            "region": "eu-central-1",
            "cache_enabled": True,
        },
    )


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.update_stage")
def test_update_stage_cache(mock_update_stage, mock_print):
    update_stage_cache("api-id", "dev", "eu-central-1", True)

    mock_update_stage.assert_called_once_with(
        "api-id",
        "dev",
        [{"op": "replace", "path": "/cacheClusterEnabled", "value": "true"}],
        "eu-central-1",
    )


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.delete_state")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.update_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_cache_actions.load_state")
def test_restore_stage_cache(
    mock_load_state, mock_update_stage, mock_delete_state, mock_print
):
    mock_load_state.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "cache_enabled": False,
    }

    restore_stage_cache()

    mock_update_stage.assert_called_once_with(
        "api-id",
        "dev",
        [{"op": "replace", "path": "/cacheClusterEnabled", "value": "false"}],
        "eu-central-1",
    )

    mock_delete_state.assert_called_once_with("apigateway_stage_cache")
