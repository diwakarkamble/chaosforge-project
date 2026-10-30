from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions import (
    ec2_incremental_actions,
)
from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions import (
    restore_incrementally_stopped_instances,
    stop_instances_incrementally,
)


def _running_instances(client, instance_ids):
    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {"InstanceId": instance_id, "State": {"Name": "running"}}
                    for instance_id in instance_ids
                ]
            }
        ]
    }


def test_stop_instances_requires_instance_ids():
    with pytest.raises(
        ValueError,
        match="At least one EC2 instance ID is required",
    ):
        stop_instances_incrementally(
            instance_ids=[],
            step_quantity=1,
            step_duration=0,
            aws_region="eu-central-1",
        )


def test_stop_instances_requires_positive_step_quantity():
    with pytest.raises(
        ValueError,
        match="Step quantity must be at least 1",
    ):
        stop_instances_incrementally(
            instance_ids=["i-001"],
            step_quantity=0,
            step_duration=0,
            aws_region="eu-central-1",
        )


def test_stop_instances_rejects_negative_step_duration():
    with pytest.raises(
        ValueError,
        match="Step duration cannot be negative",
    ):
        stop_instances_incrementally(
            instance_ids=["i-001"],
            step_quantity=1,
            step_duration=-1,
            aws_region="eu-central-1",
        )


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_stop_instances_single_batch(mock_get_client):
    client = mock_get_client.return_value
    _running_instances(client, ["i-001", "i-002"])

    stop_instances_incrementally(
        instance_ids=["i-001", "i-002"],
        step_quantity=2,
        step_duration=0,
        aws_region="eu-central-1",
    )

    mock_get_client.assert_called_once_with("eu-central-1")

    client.stop_instances.assert_called_once_with(
        InstanceIds=["i-001", "i-002"],
    )


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.time.sleep")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_stop_instances_incrementally_in_batches(
    mock_get_client,
    mock_sleep,
):
    client = mock_get_client.return_value

    instance_ids = [
        "i-001",
        "i-002",
        "i-003",
        "i-004",
        "i-005",
    ]
    _running_instances(client, instance_ids)

    stop_instances_incrementally(
        instance_ids=instance_ids,
        step_quantity=2,
        step_duration=30,
        aws_region="eu-central-1",
    )

    assert client.stop_instances.call_count == 3

    client.stop_instances.assert_any_call(
        InstanceIds=["i-001", "i-002"],
    )

    client.stop_instances.assert_any_call(
        InstanceIds=["i-003", "i-004"],
    )

    client.stop_instances.assert_any_call(
        InstanceIds=["i-005"],
    )

    assert mock_sleep.call_count == 2

    mock_sleep.assert_any_call(30)


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.time.sleep")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_stop_instances_waits_between_batches_only(
    mock_get_client,
    mock_sleep,
):
    client = mock_get_client.return_value
    _running_instances(client, ["i-001", "i-002", "i-003"])

    stop_instances_incrementally(
        instance_ids=[
            "i-001",
            "i-002",
            "i-003",
        ],
        step_quantity=1,
        step_duration=15,
        aws_region="eu-central-1",
    )

    assert client.stop_instances.call_count == 3

    assert mock_sleep.call_count == 2

    mock_sleep.assert_any_call(15)


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.time.sleep")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_stop_instances_with_step_quantity_larger_than_list(
    mock_get_client,
    mock_sleep,
):
    client = mock_get_client.return_value
    _running_instances(client, ["i-001", "i-002"])

    stop_instances_incrementally(
        instance_ids=["i-001", "i-002"],
        step_quantity=10,
        step_duration=30,
        aws_region="eu-central-1",
    )

    client.stop_instances.assert_called_once_with(
        InstanceIds=["i-001", "i-002"],
    )

    mock_sleep.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.time.sleep")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_stop_instances_converts_numeric_inputs(
    mock_get_client,
    mock_sleep,
):
    client = mock_get_client.return_value
    _running_instances(client, ["i-001", "i-002", "i-003"])

    stop_instances_incrementally(
        instance_ids=[
            "i-001",
            "i-002",
            "i-003",
        ],
        step_quantity="2",
        step_duration="10",
        aws_region="eu-central-1",
    )

    assert client.stop_instances.call_count == 2

    mock_sleep.assert_called_once_with(10)


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.repository_paths")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_restore_starts_only_instances_that_were_running(mock_get_client, mock_paths, tmp_path):
    mock_paths.return_value = type("Paths", (), {"rollback": tmp_path})()
    client = mock_get_client.return_value
    _running_instances(client, ["i-running", "i-stopped"])
    client.describe_instances.return_value["Reservations"][0]["Instances"][1]["State"]["Name"] = "stopped"

    stop_instances_incrementally(["i-running", "i-stopped"], 2, 0, "eu-central-1")
    restore_incrementally_stopped_instances(["i-running", "i-stopped"], "eu-central-1")

    client.stop_instances.assert_called_once_with(InstanceIds=["i-running"])
    client.start_instances.assert_called_once_with(InstanceIds=["i-running"])


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.repository_paths")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_restore_handles_missing_and_mismatched_rollback_state(mock_get_client, mock_paths, tmp_path):
    mock_paths.return_value = type("Paths", (), {"rollback": tmp_path})()

    assert restore_incrementally_stopped_instances(["i-1"], "eu-central-1") == "No EC2 rollback state was recorded."

    path = ec2_incremental_actions._path("eu-central-1", ["i-1"])
    path.parent.mkdir(parents=True)
    path.write_text('{"instance_ids":["i-2"],"running":["i-2"]}', encoding="utf-8")
    with pytest.raises(ValueError, match="another instance selection"):
        restore_incrementally_stopped_instances(["i-1"], "eu-central-1")


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_incremental_actions.get_client")
def test_stop_instances_rejects_unknown_baseline_targets(mock_get_client):
    mock_get_client.return_value.describe_instances.return_value = {"Reservations": []}

    with pytest.raises(ValueError, match="resolve every"):
        stop_instances_incrementally(["i-1"], 1, 0, "eu-central-1")


def test_normalize_rejects_non_list_json_and_non_sequence_inputs():
    with pytest.raises(TypeError, match="instance_ids must be"):
        ec2_incremental_actions._normalize('{"instance":"i-1"}')
    with pytest.raises(TypeError, match="instance_ids must be"):
        ec2_incremental_actions._normalize(1)
