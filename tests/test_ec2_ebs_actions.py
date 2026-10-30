from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions import (
    _get_asg_instances,
    attach_ebs_volume,
    attach_ebs_volume_to_asg_instance,
    detach_attached_ebs_volume,
    detach_ebs_volume,
    detach_random_asg_ebs_volume,
    restore_asg_attached_ebs_volume,
    restore_asg_ebs_volume,
    restore_ebs_volume,
    wait_for_duration,
)

# ----------------------------------------------------------
# Detach validation
# ----------------------------------------------------------


def test_detach_requires_instance_id():

    with pytest.raises(
        ValueError,
        match="EC2 instance ID is required",
    ):
        detach_ebs_volume(
            instance_id="",
            volume_id="vol-123",
            device_name="/dev/sdf",
            aws_region="eu-central-1",
        )


def test_detach_requires_volume_id():

    with pytest.raises(
        ValueError,
        match="EBS volume ID is required",
    ):
        detach_ebs_volume(
            instance_id="i-123",
            volume_id="",
            device_name="/dev/sdf",
            aws_region="eu-central-1",
        )


def test_detach_requires_device_name():

    with pytest.raises(
        ValueError,
        match="EBS device name is required",
    ):
        detach_ebs_volume(
            instance_id="i-123",
            volume_id="vol-123",
            device_name="",
            aws_region="eu-central-1",
        )


# ----------------------------------------------------------
# Detach
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.save_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_detach_ebs_volume(
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
    mock_save_state,
):

    client = mock_get_client.return_value

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "in-use",
    }

    mock_get_root_device.return_value = "/dev/sda1"

    detach_ebs_volume(
        instance_id="i-123",
        volume_id="vol-123",
        device_name="/dev/sdf",
        aws_region="eu-central-1",
    )

    mock_describe_volume.assert_called_once_with(
        "vol-123",
        "eu-central-1",
    )

    mock_get_root_device.assert_called_once_with(
        "i-123",
        "eu-central-1",
    )

    mock_save_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
        {
            "instance_id": "i-123",
            "volume_id": "vol-123",
            "device_name": "/dev/sdf",
        },
    )

    client.detach_volume.assert_called_once_with(
        VolumeId="vol-123",
        InstanceId="i-123",
        Force=True,
    )


# ----------------------------------------------------------
# Root volume protection
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.save_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_detach_rejects_root_volume(
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
    mock_save_state,
):

    client = mock_get_client.return_value

    mock_describe_volume.return_value = {
        "VolumeId": "vol-root",
        "State": "in-use",
    }

    mock_get_root_device.return_value = "/dev/sda1"

    with pytest.raises(
        ValueError,
        match="Root EBS volume cannot be detached",
    ):
        detach_ebs_volume(
            instance_id="i-123",
            volume_id="vol-root",
            device_name="/dev/sda1",
            aws_region="eu-central-1",
        )

    mock_save_state.assert_not_called()
    client.detach_volume.assert_not_called()


# ----------------------------------------------------------
# Volume not found
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_detach_volume_not_found(
    mock_get_client,
    mock_describe_volume,
):

    mock_describe_volume.side_effect = RuntimeError(
        "EBS volume 'vol-missing' not found."
    )

    with pytest.raises(
        RuntimeError,
        match="EBS volume 'vol-missing' not found",
    ):
        detach_ebs_volume(
            instance_id="i-123",
            volume_id="vol-missing",
            device_name="/dev/sdf",
            aws_region="eu-central-1",
        )


# ----------------------------------------------------------
# Restore
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.delete_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_ebs_volume(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_wait,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-123",
        "device_name": "/dev/sdf",
    }

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "available",
    }

    restore_ebs_volume(
        aws_region="eu-central-1",
        wait_seconds=30,
    )

    mock_load_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
    )

    mock_describe_volume.assert_called_once_with(
        "vol-123",
        "eu-central-1",
    )

    mock_wait.assert_not_called()

    client.attach_volume.assert_called_once_with(
        VolumeId="vol-123",
        InstanceId="i-123",
        Device="/dev/sdf",
    )

    mock_delete_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
    )


# ----------------------------------------------------------
# Restore waits for available volume
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.delete_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_waits_for_available_volume(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_wait,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-123",
        "device_name": "/dev/sdf",
    }

    mock_describe_volume.side_effect = [
        {
            "VolumeId": "vol-123",
            "State": "detaching",
        },
        {
            "VolumeId": "vol-123",
            "State": "available",
        },
    ]

    restore_ebs_volume(
        aws_region="eu-central-1",
        wait_seconds=30,
    )

    assert mock_describe_volume.call_count == 2

    mock_wait.assert_called_once_with(1)

    client.attach_volume.assert_called_once_with(
        VolumeId="vol-123",
        InstanceId="i-123",
        Device="/dev/sdf",
    )

    mock_delete_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
    )


# ----------------------------------------------------------
# Restore state missing
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_state_missing(mock_load_state):

    mock_load_state.side_effect = FileNotFoundError("State file not found")

    with pytest.raises(
        FileNotFoundError,
        match="State file not found",
    ):
        restore_ebs_volume(
            aws_region="eu-central-1",
        )


# ----------------------------------------------------------
# Restore timeout
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_volume_timeout(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_wait,
):

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-123",
        "device_name": "/dev/sdf",
    }

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "detaching",
    }

    with pytest.raises(
        RuntimeError,
        match="did not become available",
    ):
        restore_ebs_volume(
            aws_region="eu-central-1",
            wait_seconds=3,
        )

    assert mock_describe_volume.call_count == 3
    assert mock_wait.call_count == 3

    mock_get_client.return_value.attach_volume.assert_not_called()


# ----------------------------------------------------------
# Wait for duration
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
def test_wait_for_duration_positive(mock_wait):

    wait_for_duration(10)

    mock_wait.assert_called_once_with(10)


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
def test_wait_for_duration_zero(mock_wait):

    wait_for_duration(0)

    mock_wait.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
def test_wait_for_duration_negative(mock_wait):

    wait_for_duration(-1)

    mock_wait.assert_not_called()


# ----------------------------------------------------------
# Attach validation
# ----------------------------------------------------------


def test_attach_requires_instance_id():

    with pytest.raises(
        ValueError,
        match="EC2 instance ID is required",
    ):
        attach_ebs_volume(
            instance_id="",
            volume_id="vol-123",
            device_name="/dev/sdf",
            aws_region="eu-central-1",
        )


def test_attach_requires_volume_id():

    with pytest.raises(
        ValueError,
        match="EBS volume ID is required",
    ):
        attach_ebs_volume(
            instance_id="i-123",
            volume_id="",
            device_name="/dev/sdf",
            aws_region="eu-central-1",
        )


def test_attach_requires_device_name():

    with pytest.raises(
        ValueError,
        match="EBS device name is required",
    ):
        attach_ebs_volume(
            instance_id="i-123",
            volume_id="vol-123",
            device_name="",
            aws_region="eu-central-1",
        )


# ----------------------------------------------------------
# Attach
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.save_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_attach_ebs_volume(
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
    mock_save_state,
    mock_wait,
):

    client = mock_get_client.return_value

    mock_describe_volume.side_effect = [
        {
            "VolumeId": "vol-123",
            "State": "available",
        },
        {
            "VolumeId": "vol-123",
            "State": "in-use",
        },
    ]

    mock_get_root_device.return_value = "/dev/sda1"

    attach_ebs_volume(
        instance_id="i-123",
        volume_id="vol-123",
        device_name="/dev/sdf",
        aws_region="eu-central-1",
    )

    mock_save_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
        {
            "instance_id": "i-123",
            "volume_id": "vol-123",
            "device_name": "/dev/sdf",
        },
    )

    client.attach_volume.assert_called_once_with(
        VolumeId="vol-123",
        InstanceId="i-123",
        Device="/dev/sdf",
    )

    mock_wait.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_attach_rejects_unavailable_volume(
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
):

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "in-use",
    }

    with pytest.raises(
        ValueError,
        match="must be available",
    ):
        attach_ebs_volume(
            instance_id="i-123",
            volume_id="vol-123",
            device_name="/dev/sdf",
            aws_region="eu-central-1",
        )

    mock_get_root_device.assert_not_called()
    mock_get_client.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_attach_rejects_root_device_conflict(
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
):

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "available",
    }

    mock_get_root_device.return_value = "/dev/sda1"

    with pytest.raises(
        ValueError,
        match="conflicts with",
    ):
        attach_ebs_volume(
            instance_id="i-123",
            volume_id="vol-123",
            device_name="/dev/sda1",
            aws_region="eu-central-1",
        )

    mock_get_client.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.save_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_attach_waits_for_in_use(
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
    mock_save_state,
    mock_wait,
):

    client = mock_get_client.return_value

    mock_get_root_device.return_value = "/dev/sda1"

    mock_describe_volume.side_effect = [
        {
            "VolumeId": "vol-123",
            "State": "available",
        },
        {
            "VolumeId": "vol-123",
            "State": "attaching",
        },
        {
            "VolumeId": "vol-123",
            "State": "in-use",
        },
    ]

    attach_ebs_volume(
        instance_id="i-123",
        volume_id="vol-123",
        device_name="/dev/sdf",
        aws_region="eu-central-1",
        wait_seconds=30,
    )

    assert mock_describe_volume.call_count == 3
    mock_wait.assert_called_once_with(1)

    client.attach_volume.assert_called_once_with(
        VolumeId="vol-123",
        InstanceId="i-123",
        Device="/dev/sdf",
    )


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
def test_attach_timeout(
    mock_get_client,
    mock_get_root_device,
    mock_describe_volume,
    mock_wait,
):

    mock_get_root_device.return_value = "/dev/sda1"

    mock_describe_volume.side_effect = [
        {
            "VolumeId": "vol-123",
            "State": "available",
        },
        {
            "VolumeId": "vol-123",
            "State": "attaching",
        },
        {
            "VolumeId": "vol-123",
            "State": "attaching",
        },
        {
            "VolumeId": "vol-123",
            "State": "attaching",
        },
    ]

    with pytest.raises(
        RuntimeError,
        match="did not become 'in-use'",
    ):
        attach_ebs_volume(
            instance_id="i-123",
            volume_id="vol-123",
            device_name="/dev/sdf",
            aws_region="eu-central-1",
            wait_seconds=3,
        )

    assert mock_describe_volume.call_count == 4
    assert mock_wait.call_count == 3

    mock_get_client.return_value.attach_volume.assert_called_once()


# ----------------------------------------------------------
# Detach attached volume rollback
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.delete_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_detach_attached_ebs_volume(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
    mock_wait,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-123",
        "device_name": "/dev/sdf",
    }

    mock_get_root_device.return_value = "/dev/sda1"

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "available",
    }

    detach_attached_ebs_volume(
        aws_region="eu-central-1",
        wait_seconds=30,
    )

    client.detach_volume.assert_called_once_with(
        VolumeId="vol-123",
        InstanceId="i-123",
        Force=True,
    )

    mock_delete_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
    )

    mock_wait.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_detach_attached_rejects_root_volume(
    mock_load_state,
    mock_get_client,
    mock_get_root_device,
):

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-root",
        "device_name": "/dev/sda1",
    }

    mock_get_root_device.return_value = "/dev/sda1"

    with pytest.raises(
        ValueError,
        match="Root EBS volume cannot be detached",
    ):
        detach_attached_ebs_volume(
            aws_region="eu-central-1",
        )

    mock_get_client.return_value.detach_volume.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_detach_attached_timeout(
    mock_load_state,
    mock_get_client,
    mock_get_root_device,
    mock_describe_volume,
    mock_wait,
):

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-123",
        "device_name": "/dev/sdf",
    }

    mock_get_root_device.return_value = "/dev/sda1"

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "detaching",
    }

    with pytest.raises(
        RuntimeError,
        match="did not become 'available'",
    ):
        detach_attached_ebs_volume(
            aws_region="eu-central-1",
            wait_seconds=3,
        )

    assert mock_wait.call_count == 3


# ----------------------------------------------------------
# ASG instance discovery
# ----------------------------------------------------------


def test_get_asg_instances_requires_name():

    with pytest.raises(
        ValueError,
        match="Auto Scaling Group name is required",
    ):
        _get_asg_instances(
            "",
            "eu-central-1",
        )


@patch("boto3.client")
def test_get_asg_instances_not_found(mock_boto_client):

    client = mock_boto_client.return_value

    client.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": []}

    with pytest.raises(
        RuntimeError,
        match="not found",
    ):
        _get_asg_instances(
            "asg-test",
            "eu-central-1",
        )


@patch("boto3.client")
def test_get_asg_instances_no_inservice(mock_boto_client):

    client = mock_boto_client.return_value

    client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "Instances": [
                    {
                        "LifecycleState": "Pending",
                        "InstanceId": "i-123",
                    }
                ]
            }
        ]
    }

    with pytest.raises(
        RuntimeError,
        match="has no InService instances",
    ):
        _get_asg_instances(
            "asg-test",
            "eu-central-1",
        )


@patch("boto3.client")
def test_get_asg_instances_success(mock_boto_client):

    client = mock_boto_client.return_value

    client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "Instances": [
                    {
                        "LifecycleState": "InService",
                        "InstanceId": "i-123",
                    },
                    {
                        "LifecycleState": "Pending",
                        "InstanceId": "i-456",
                    },
                    {
                        "LifecycleState": "InService",
                        "InstanceId": "i-789",
                    },
                    {
                        "LifecycleState": "InService",
                    },
                ]
            }
        ]
    }

    result = _get_asg_instances(
        "asg-test",
        "eu-central-1",
    )

    assert result == [
        "i-123",
        "i-789",
    ]


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.save_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_root_device")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions._get_asg_instances")
def test_attach_asg_no_suitable_instance(
    mock_get_asg,
    mock_get_client,
    mock_describe_volume,
    mock_get_root_device,
    mock_save_state,
):

    mock_get_asg.return_value = [
        "i-123",
        "i-456",
    ]

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "available",
    }

    mock_get_root_device.side_effect = RuntimeError("Instance lookup failed")

    with pytest.raises(
        RuntimeError,
        match="No suitable InService",
    ):
        attach_ebs_volume_to_asg_instance(
            "asg-test",
            "vol-123",
            "/dev/sdf",
            "eu-central-1",
        )

    mock_save_state.assert_not_called()
    mock_get_client.return_value.attach_volume.assert_not_called()


# ----------------------------------------------------------
# ASG attached volume restore
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.delete_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_asg_attached_ebs_volume(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_wait,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-123",
        "device_name": "/dev/sdf",
    }

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "available",
    }

    restore_asg_attached_ebs_volume(
        aws_region="eu-central-1",
    )

    client.detach_volume.assert_called_once_with(
        VolumeId="vol-123",
        InstanceId="i-123",
        Force=True,
    )

    mock_delete_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
    )

    mock_wait.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_asg_attached_timeout(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_wait,
):

    mock_load_state.return_value = {
        "instance_id": "i-123",
        "volume_id": "vol-123",
        "device_name": "/dev/sdf",
    }

    mock_describe_volume.return_value = {
        "VolumeId": "vol-123",
        "State": "detaching",
    }

    with pytest.raises(
        RuntimeError,
        match="did not become 'available'",
    ):
        restore_asg_attached_ebs_volume(
            aws_region="eu-central-1",
            wait_seconds=3,
        )

    assert mock_wait.call_count == 3


# ----------------------------------------------------------
# Random ASG volume detach
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.delete_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.save_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions._get_asg_instances")
def test_detach_random_asg_ebs_volume(
    mock_get_asg,
    mock_get_client,
    mock_save_state,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_get_asg.return_value = [
        "i-123",
    ]

    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "RootDeviceName": "/dev/sda1",
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/sda1",
                                "Ebs": {
                                    "VolumeId": "vol-root",
                                },
                            },
                            {
                                "DeviceName": "/dev/sdf",
                                "Ebs": {
                                    "VolumeId": "vol-data",
                                },
                            },
                        ],
                    }
                ]
            }
        ]
    }

    detach_random_asg_ebs_volume(
        "asg-test",
        "eu-central-1",
    )

    mock_save_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
        {
            "autoscaling_group": "asg-test",
            "instance_id": "i-123",
            "volume_id": "vol-data",
            "device_name": "/dev/sdf",
        },
    )

    client.detach_volume.assert_called_once_with(
        VolumeId="vol-data",
        InstanceId="i-123",
        Force=True,
    )


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions._get_asg_instances")
def test_detach_random_asg_no_non_root_volume(
    mock_get_asg,
    mock_get_client,
):

    client = mock_get_client.return_value

    mock_get_asg.return_value = [
        "i-123",
    ]

    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "RootDeviceName": "/dev/sda1",
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/sda1",
                                "Ebs": {
                                    "VolumeId": "vol-root",
                                },
                            }
                        ],
                    }
                ]
            }
        ]
    }

    with pytest.raises(
        RuntimeError,
        match="No non-root EBS volume found",
    ):
        detach_random_asg_ebs_volume(
            "asg-test",
            "eu-central-1",
        )


# ----------------------------------------------------------
# Random ASG volume restore
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.delete_state")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_asg_ebs_volume(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_wait,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "autoscaling_group": "asg-test",
        "instance_id": "i-123",
        "volume_id": "vol-data",
        "device_name": "/dev/sdf",
    }

    mock_describe_volume.return_value = {
        "VolumeId": "vol-data",
        "State": "available",
    }

    restore_asg_ebs_volume(
        aws_region="eu-central-1",
    )

    client.attach_volume.assert_called_once_with(
        VolumeId="vol-data",
        InstanceId="i-123",
        Device="/dev/sdf",
    )

    mock_delete_state.assert_called_once_with(
        "chaosforge_ec2_ebs",
    )

    mock_wait.assert_not_called()


@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.wait_for_seconds")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.describe_volume")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.get_client")
@patch("chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_ebs_actions.load_state")
def test_restore_asg_ebs_volume_timeout(
    mock_load_state,
    mock_get_client,
    mock_describe_volume,
    mock_wait,
):

    mock_load_state.return_value = {
        "autoscaling_group": "asg-test",
        "instance_id": "i-123",
        "volume_id": "vol-data",
        "device_name": "/dev/sdf",
    }

    mock_describe_volume.return_value = {
        "VolumeId": "vol-data",
        "State": "detaching",
    }

    with pytest.raises(
        RuntimeError,
        match="did not become 'available'",
    ):
        restore_asg_ebs_volume(
            aws_region="eu-central-1",
            wait_seconds=3,
        )

    assert mock_wait.call_count == 3

    mock_get_client.return_value.attach_volume.assert_not_called()
