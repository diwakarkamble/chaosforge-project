from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common import (
    apply_patch_operations,
    delete_state,
    get_client,
    get_stage,
    get_state_file,
    load_state,
    print_header,
    print_stage_summary,
    save_state,
    update_stage,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.boto3.client")
def test_get_client(mock_boto_client):
    client = MagicMock()

    mock_boto_client.return_value = client

    result = get_client("eu-central-1")

    mock_boto_client.assert_called_once_with("apigateway", region_name="eu-central-1")

    assert result == client


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.get_client")
def test_get_stage(mock_get_client):
    client = MagicMock()

    mock_get_client.return_value = client

    client.get_stage.return_value = {"stageName": "dev"}

    result = get_stage("api-id", "dev", "eu-central-1")

    client.get_stage.assert_called_once_with(restApiId="api-id", stageName="dev")

    assert result["stageName"] == "dev"


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.get_client")
def test_update_stage(mock_get_client, mock_print):
    client = MagicMock()

    mock_get_client.return_value = client

    patch_ops = [{"op": "replace", "path": "/tracingEnabled", "value": "true"}]

    update_stage("api-id", "dev", patch_ops, "eu-central-1")

    client.update_stage.assert_called_once_with(
        restApiId="api-id", stageName="dev", patchOperations=patch_ops
    )


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.update_stage")
def test_apply_patch_operations(mock_update):
    patch_ops = [{"op": "replace"}]

    apply_patch_operations("api-id", "dev", patch_ops, "eu-central-1")

    mock_update.assert_called_once_with(
        rest_api_id="api-id",
        stage_name="dev",
        patch_operations=patch_ops,
        region="eu-central-1",
    )


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.print")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.time.sleep")
def test_wait_for_duration(mock_sleep, mock_print):
    wait_for_duration(5)

    mock_sleep.assert_called_once_with(5.0)


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.tempfile.gettempdir")
def test_get_state_file(mock_tempdir):
    mock_tempdir.return_value = "/tmp"

    result = get_state_file("demo")

    assert result.endswith("demo.json")


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.json.dump")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.get_state_file")
def test_save_state(mock_state_file, mock_open_file, mock_dump):
    mock_state_file.return_value = "state.json"

    save_state("demo", {"a": 1})

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.json.load")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.get_state_file")
def test_load_state(mock_state_file, mock_exists, mock_open_file, mock_load):
    mock_state_file.return_value = "state.json"

    mock_exists.return_value = True

    mock_load.return_value = {"a": 1}

    result = load_state("demo")

    assert result["a"] == 1


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.get_state_file")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.os.path.exists")
def test_load_state_missing(mock_exists, mock_state_file):
    mock_state_file.return_value = "state.json"

    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found"):
        load_state("demo")


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.get_state_file")
def test_delete_state(mock_state_file, mock_exists, mock_remove):
    mock_state_file.return_value = "state.json"

    mock_exists.return_value = True

    delete_state("demo")

    mock_remove.assert_called_once_with("state.json")


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.os.remove")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.os.path.exists")
@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.get_state_file")
def test_delete_state_not_exists(mock_state_file, mock_exists, mock_remove):
    mock_state_file.return_value = "state.json"

    mock_exists.return_value = False

    delete_state("demo")

    mock_remove.assert_not_called()


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.print")
def test_print_header(mock_print):
    print_header("Chaos Test")

    assert mock_print.call_count == 4


@patch("chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions.apigateway_common.print")
def test_print_stage_summary(mock_print):
    print_stage_summary(
        {
            "stageName": "dev",
            "deploymentId": "123",
            "tracingEnabled": True,
            "cacheClusterSize": "0.5",
            "cacheClusterEnabled": True,
        }
    )

    assert mock_print.call_count >= 6
