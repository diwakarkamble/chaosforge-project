from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions import (
    capture_and_update_stage_variable,
    rollback_stage_variables,
)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_client")
def test_capture_add_variable(
    mock_get_client, mock_get_stage, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_get_stage.return_value = {"variables": {}}

    capture_and_update_stage_variable("api-id", "dev", "eu-central-1", "ENV", "prod")

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[{"op": "replace", "path": "/variables/ENV", "value": "prod"}],
    )
    output = "\n".join(" ".join(map(str, call.args)) for call in mock_print.call_args_list)
    assert "0 configured" in output
    assert "ENV" in output
    assert "prod" not in output


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_client")
def test_capture_replace_variable(
    mock_get_client, mock_get_stage, mock_dump, mock_open_file, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_get_stage.return_value = {"variables": {"ENV": "dev"}}

    capture_and_update_stage_variable("api-id", "dev", "eu-central-1", "ENV", "prod")

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[{"op": "replace", "path": "/variables/ENV", "value": "prod"}],
    )
    output = "\n".join(" ".join(map(str, call.args)) for call in mock_print.call_args_list)
    assert "1 configured" in output
    assert "ENV" in output
    assert "dev" not in output
    assert "prod" not in output


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.os.path.exists")
def test_rollback_state_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found."):
        rollback_stage_variables()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_client")
def test_rollback_stage_variables(
    mock_get_client,
    mock_exists,
    mock_get_stage,
    mock_load,
    mock_open_file,
    mock_remove,
    mock_print,
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_get_client.return_value = client

    mock_load.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "variables": {"ENV": "dev"},
    }

    mock_get_stage.return_value = {"variables": {"ENV": "prod", "NEW": "value"}}

    rollback_stage_variables()

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[
            {"op": "replace", "path": "/variables/ENV", "value": "dev"},
            {"op": "remove", "path": "/variables/NEW"},
        ],
    )

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_client")
def test_rollback_no_patch_required(
    mock_get_client,
    mock_exists,
    mock_get_stage,
    mock_load,
    mock_open_file,
    mock_remove,
    mock_print,
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_get_client.return_value = client

    mock_load.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "variables": {},
    }

    mock_get_stage.return_value = {"variables": {}}

    rollback_stage_variables()

    client.update_stage.assert_not_called()

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_stage")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_stage_variables_actions.get_client")
def test_rollback_add_missing_variable(
    mock_get_client,
    mock_exists,
    mock_get_stage,
    mock_load,
    mock_open_file,
    mock_remove,
    mock_print,
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_get_client.return_value = client

    mock_load.return_value = {
        "rest_api_id": "api-id",
        "stage_name": "dev",
        "region": "eu-central-1",
        "variables": {"ENV": "dev"},
    }

    # API Gateway requires replace to restore a variable into an empty stage.
    mock_get_stage.return_value = {"variables": {}}

    rollback_stage_variables()

    client.update_stage.assert_called_once_with(
        restApiId="api-id",
        stageName="dev",
        patchOperations=[{"op": "replace", "path": "/variables/ENV", "value": "dev"}],
    )

    mock_remove.assert_called_once()
