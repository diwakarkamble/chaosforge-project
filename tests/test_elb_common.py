import os
from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common import (
    delete_state,
    get_state_file,
    get_target_registration,
    load_state,
    save_state,
    wait_for_seconds,
)


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.boto3.client")
def test_get_client(mock_client):

    from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common import (
        get_client,
    )

    client = get_client("test-region")

    mock_client.assert_called_once_with(
        "elbv2",
        region_name="test-region",
    )

    assert client == mock_client.return_value


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.get_client")
def test_get_target_registration(mock_get_client):

    client = mock_get_client.return_value

    client.describe_target_health.return_value = {
        "TargetHealthDescriptions": [
            {
                "Target": {
                    "Id": "target-123",
                    "Port": 8080,
                },
                "TargetHealth": {
                    "State": "healthy",
                },
            }
        ]
    }

    result = get_target_registration(
        "target-group-arn-123",
        "target-123",
        "test-region",
    )

    client.describe_target_health.assert_called_once_with(
        TargetGroupArn="target-group-arn-123",
        Targets=[
            {
                "Id": "target-123",
            }
        ],
    )

    assert result == {
        "target_group_arn": "target-group-arn-123",
        "target_id": "target-123",
        "port": 8080,
    }


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.get_client")
def test_get_target_registration_not_found(mock_get_client):

    client = mock_get_client.return_value

    client.describe_target_health.return_value = {"TargetHealthDescriptions": []}

    with pytest.raises(
        RuntimeError,
        match="ELB target 'target-missing' not found",
    ):
        get_target_registration(
            "target-group-arn-123",
            "target-missing",
            "test-region",
        )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.time.sleep")
def test_wait_for_seconds(mock_sleep):

    wait_for_seconds(30)

    mock_sleep.assert_called_once_with(30.0)


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.tempfile.gettempdir")
def test_get_state_file(mock_tempdir):

    temp_dir = os.path.join(
        "tmp",
        "chaosforge",
    )

    mock_tempdir.return_value = temp_dir

    result = get_state_file("elb-test")

    assert result == os.path.join(
        temp_dir,
        "elb-test.json",
    )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.json.dump")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.open")
def test_save_state(
    mock_open,
    mock_dump,
    mock_get_state_file,
):

    mock_get_state_file.return_value = "state.json"

    data = {
        "target_group_arn": "target-group-arn-123",
        "target_id": "target-123",
        "port": 8080,
    }

    save_state(
        "elb-test",
        data,
    )

    mock_open.assert_called_once_with(
        "state.json",
        "w",
        encoding="utf-8",
    )

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.os.path.exists")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.open")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.json.load")
def test_load_state(
    mock_json_load,
    mock_open,
    mock_exists,
    mock_get_state_file,
):

    mock_get_state_file.return_value = "state.json"

    mock_exists.return_value = True

    mock_json_load.return_value = {
        "target_group_arn": "target-group-arn-123",
        "target_id": "target-123",
        "port": 8080,
    }

    result = load_state("elb-test")

    assert result == {
        "target_group_arn": "target-group-arn-123",
        "target_id": "target-123",
        "port": 8080,
    }


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.os.path.exists")
def test_load_state_missing_file(
    mock_exists,
    mock_get_state_file,
):

    mock_get_state_file.return_value = "state.json"

    mock_exists.return_value = False

    with pytest.raises(
        FileNotFoundError,
        match="State file not found",
    ):
        load_state("elb-test")


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.os.remove")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.os.path.exists")
def test_delete_state(
    mock_exists,
    mock_remove,
    mock_get_state_file,
):

    mock_get_state_file.return_value = "state.json"

    mock_exists.return_value = True

    delete_state("elb-test")

    mock_remove.assert_called_once_with("state.json")


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.os.remove")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_common.os.path.exists")
def test_delete_state_missing_file(
    mock_exists,
    mock_remove,
    mock_get_state_file,
):

    mock_exists.return_value = False

    delete_state("elb-test")

    mock_remove.assert_not_called()
