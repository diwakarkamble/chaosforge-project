import os
from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common import (
    delete_state,
    describe_instance,
    get_instance_state,
    get_state_file,
    load_state,
    print_header,
    print_instance_summary,
    save_state,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.boto3.client")
def test_get_client(mock_client):

    from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common import (
        get_client,
    )

    client = get_client("eu-central-1")

    mock_client.assert_called_once_with(
        "ec2",
        region_name="eu-central-1",
    )

    assert client == mock_client.return_value


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.get_client")
def test_describe_instance(mock_get_client):

    client = mock_get_client.return_value

    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-1234567890",
                        "InstanceType": "t3.micro",
                        "State": {
                            "Name": "running",
                        },
                    }
                ]
            }
        ]
    }

    result = describe_instance(
        "i-1234567890",
        "eu-central-1",
    )

    client.describe_instances.assert_called_once_with(
        InstanceIds=["i-1234567890"],
    )

    assert result["InstanceId"] == "i-1234567890"


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.get_client")
def test_describe_instance_not_found(mock_get_client):

    client = mock_get_client.return_value

    client.describe_instances.return_value = {"Reservations": []}

    with pytest.raises(
        RuntimeError,
        match="EC2 Instance 'i-missing' not found",
    ):
        describe_instance(
            "i-missing",
            "eu-central-1",
        )


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.describe_instance")
def test_get_instance_state(mock_describe):

    mock_describe.return_value = {
        "InstanceId": "i-1234567890",
        "State": {
            "Name": "running",
        },
    }

    result = get_instance_state(
        "i-1234567890",
        "eu-central-1",
    )

    mock_describe.assert_called_once_with(
        "i-1234567890",
        "eu-central-1",
    )

    assert result == "running"


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.time.sleep")
def test_wait_for_duration(mock_sleep):

    wait_for_duration(30)

    mock_sleep.assert_called_once_with(30.0)


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.tempfile.gettempdir")
def test_get_state_file(mock_tempdir):

    temp_dir = os.path.join(
        "tmp",
        "chaosforge",
    )

    mock_tempdir.return_value = temp_dir

    result = get_state_file("ec2-test")

    assert result == os.path.join(
        temp_dir,
        "ec2-test.json",
    )


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.get_state_file")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.json.dump")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.open")
def test_save_state(mock_open, mock_dump, mock_get_state_file):

    mock_get_state_file.return_value = "state.json"

    data = {
        "instance_id": "i-1234567890",
    }

    save_state(
        "ec2-test",
        data,
    )

    mock_open.assert_called_once_with(
        "state.json",
        "w",
        encoding="utf-8",
    )

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.get_state_file")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.os.path.exists")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.open")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.json.load")
def test_load_state(
    mock_json_load,
    mock_open,
    mock_exists,
    mock_get_state_file,
):

    mock_get_state_file.return_value = "state.json"

    mock_exists.return_value = True

    mock_json_load.return_value = {
        "instance_id": "i-1234567890",
    }

    result = load_state("ec2-test")

    assert result == {
        "instance_id": "i-1234567890",
    }


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.get_state_file")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.os.path.exists")
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
        load_state("ec2-test")


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.get_state_file")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.os.remove")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.os.path.exists")
def test_delete_state(
    mock_exists,
    mock_remove,
    mock_get_state_file,
):

    mock_get_state_file.return_value = "state.json"

    mock_exists.return_value = True

    delete_state("ec2-test")

    mock_remove.assert_called_once_with("state.json")


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.get_state_file")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.os.remove")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common.os.path.exists")
def test_delete_state_missing_file(
    mock_exists,
    mock_remove,
    mock_get_state_file,
):

    mock_get_state_file.return_value = "state.json"

    mock_exists.return_value = False

    delete_state("ec2-test")

    mock_remove.assert_not_called()


@patch("builtins.print")
def test_print_header(mock_print):

    print_header("EC2 Chaos")

    assert mock_print.call_count == 4


@patch("builtins.print")
def test_print_instance_summary(mock_print):

    instance = {
        "InstanceId": "i-1234567890",
        "InstanceType": "t3.micro",
        "State": {
            "Name": "running",
        },
        "Placement": {
            "AvailabilityZone": "eu-central-1a",
        },
    }

    print_instance_summary(instance)

    output = "\n".join(
        str(call.args[0]) for call in mock_print.call_args_list if call.args
    )

    assert "i-1234567890" in output
    assert "t3.micro" in output
    assert "running" in output
    assert "eu-central-1a" in output
