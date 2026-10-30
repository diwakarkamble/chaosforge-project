"""
ChaosForge EC2 / EBS Chaos Actions
"""

from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common import (
    delete_state,
    describe_volume,
    get_client,
    get_root_device,
    load_state,
    save_state,
    wait_for_seconds,
)

STATE_NAME = "chaosforge_ec2_ebs"


def wait_for_duration(wait_seconds):
    """
    Keep the chaos state active for the configured duration.
    """

    seconds = int(wait_seconds)

    if seconds <= 0:
        return

    print(f"Waiting {seconds} seconds before rollback...")

    wait_for_seconds(seconds)


def detach_ebs_volume(
    instance_id,
    volume_id,
    device_name,
    aws_region,
    force=True,
):
    """
    Detach a non-root EBS volume from an EC2 instance.

    The original attachment information is persisted so that the
    volume can be restored during rollback.
    """

    if not instance_id:
        raise ValueError("EC2 instance ID is required.")

    if not volume_id:
        raise ValueError("EBS volume ID is required.")

    if not device_name:
        raise ValueError("EBS device name is required.")

    client = get_client(aws_region)

    describe_volume(
        volume_id,
        aws_region,
    )

    root_device = get_root_device(
        instance_id,
        aws_region,
    )

    if root_device and device_name == root_device:
        raise ValueError("Root EBS volume cannot be detached by this experiment.")

    state = {
        "instance_id": instance_id,
        "volume_id": volume_id,
        "device_name": device_name,
    }

    save_state(
        STATE_NAME,
        state,
    )

    client.detach_volume(
        VolumeId=volume_id,
        InstanceId=instance_id,
        Force=str(force).lower() == "true",
    )

    print(f"EBS volume {volume_id} detached from {instance_id}.")


def restore_ebs_volume(
    aws_region,
    wait_seconds=30,
):
    """
    Restore the EBS volume captured by detach_ebs_volume.
    """

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    volume_id = state["volume_id"]
    instance_id = state["instance_id"]
    device_name = state["device_name"]

    for _ in range(max(1, int(wait_seconds))):
        volume = describe_volume(
            volume_id,
            aws_region,
        )

        if volume["State"] == "available":
            break

        wait_for_seconds(1)

    else:
        raise RuntimeError(
            f"EBS volume '{volume_id}' did not become "
            f"available within {wait_seconds} seconds."
        )

    client.attach_volume(
        VolumeId=volume_id,
        InstanceId=instance_id,
        Device=device_name,
    )

    delete_state(STATE_NAME)

    print(f"EBS volume {volume_id} reattached to {instance_id} as {device_name}.")


def attach_ebs_volume(
    instance_id,
    volume_id,
    device_name,
    aws_region,
    wait_seconds=30,
):
    """
    Attach an available EBS volume to an EC2 instance.

    The original volume state is persisted so that the attachment
    can be removed during rollback.
    """

    if not instance_id:
        raise ValueError("EC2 instance ID is required.")

    if not volume_id:
        raise ValueError("EBS volume ID is required.")

    if not device_name:
        raise ValueError("EBS device name is required.")

    volume = describe_volume(
        volume_id,
        aws_region,
    )

    if volume["State"] != "available":
        raise ValueError(
            f"EBS volume '{volume_id}' must be available "
            f"before it can be attached. "
            f"Current state: {volume['State']}."
        )

    root_device = get_root_device(
        instance_id,
        aws_region,
    )

    if root_device and device_name == root_device:
        raise ValueError(
            "The selected device name conflicts with the EC2 instance root device."
        )

    client = get_client(aws_region)

    state = {
        "instance_id": instance_id,
        "volume_id": volume_id,
        "device_name": device_name,
    }

    save_state(
        STATE_NAME,
        state,
    )

    client.attach_volume(
        VolumeId=volume_id,
        InstanceId=instance_id,
        Device=device_name,
    )

    for _ in range(max(1, int(wait_seconds))):
        volume = describe_volume(
            volume_id,
            aws_region,
        )

        if volume["State"] == "in-use":
            break

        wait_for_seconds(1)

    else:
        raise RuntimeError(
            f"EBS volume '{volume_id}' did not become "
            f"'in-use' within {wait_seconds} seconds."
        )

    print(f"EBS volume {volume_id} attached to {instance_id} as {device_name}.")


def detach_attached_ebs_volume(
    aws_region,
    wait_seconds=30,
    force=True,
):
    """
    Roll back an attachment created by attach_ebs_volume().
    """

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    volume_id = state["volume_id"]
    instance_id = state["instance_id"]

    root_device = get_root_device(
        instance_id,
        aws_region,
    )

    device_name = state["device_name"]

    if root_device and device_name == root_device:
        raise ValueError("Root EBS volume cannot be detached during rollback.")

    client.detach_volume(
        VolumeId=volume_id,
        InstanceId=instance_id,
        Force=force,
    )

    for _ in range(max(1, int(wait_seconds))):
        volume = describe_volume(
            volume_id,
            aws_region,
        )

        if volume["State"] == "available":
            break

        wait_for_seconds(1)

    else:
        raise RuntimeError(
            f"EBS volume '{volume_id}' did not become "
            f"'available' within {wait_seconds} seconds."
        )

    delete_state(STATE_NAME)

    print(f"EBS volume {volume_id} detached from {instance_id} during rollback.")


# ----------------------------------------------------------
# ASG EBS Helpers
# ----------------------------------------------------------


def _get_asg_instances(
    autoscaling_group,
    aws_region,
):
    """
    Return running EC2 instance IDs belonging to an Auto Scaling Group.
    """

    if not autoscaling_group:
        raise ValueError("Auto Scaling Group name is required.")

    import boto3

    asg_client = boto3.client(
        "autoscaling",
        region_name=aws_region,
    )

    response = asg_client.describe_auto_scaling_groups(
        AutoScalingGroupNames=[autoscaling_group],
    )

    groups = response.get("AutoScalingGroups", [])

    if not groups:
        raise RuntimeError(f"Auto Scaling Group '{autoscaling_group}' not found.")

    instances = []

    for instance in groups[0].get("Instances", []):
        if instance.get("LifecycleState") == "InService":
            instance_id = instance.get("InstanceId")

            if instance_id:
                instances.append(instance_id)

    if not instances:
        raise RuntimeError(
            f"Auto Scaling Group '{autoscaling_group}' has no InService instances."
        )

    return instances


def attach_ebs_volume_to_asg_instance(
    autoscaling_group,
    volume_id,
    device_name,
    aws_region,
):
    """
    Select an InService EC2 instance from the Auto Scaling Group
    and attach the supplied available EBS volume to it.

    The selected instance and attachment information are persisted
    so that rollback can remove the attachment.
    """

    if not autoscaling_group:
        raise ValueError("Auto Scaling Group name is required.")

    if not volume_id:
        raise ValueError("EBS volume ID is required.")

    if not device_name:
        raise ValueError("EBS device name is required.")

    instance_ids = _get_asg_instances(
        autoscaling_group,
        aws_region,
    )

    client = get_client(aws_region)

    volume = describe_volume(
        volume_id,
        aws_region,
    )

    if volume["State"] != "available":
        raise ValueError(
            f"EBS volume '{volume_id}' must be available "
            f"before it can be attached. "
            f"Current state: {volume['State']}."
        )

    selected_instance = None

    for instance_id in instance_ids:
        try:
            root_device = get_root_device(
                instance_id,
                aws_region,
            )

            if root_device and device_name == root_device:
                continue

            selected_instance = instance_id
            break

        except RuntimeError:
            continue

    if not selected_instance:
        raise RuntimeError(
            "No suitable InService EC2 instance was found in the Auto Scaling Group."
        )

    state = {
        "autoscaling_group": autoscaling_group,
        "instance_id": selected_instance,
        "volume_id": volume_id,
        "device_name": device_name,
    }

    save_state(
        STATE_NAME,
        state,
    )

    client.attach_volume(
        VolumeId=volume_id,
        InstanceId=selected_instance,
        Device=device_name,
    )

    print(
        f"EBS volume {volume_id} attached to "
        f"ASG instance {selected_instance} "
        f"as {device_name}."
    )


def restore_asg_attached_ebs_volume(
    aws_region,
    wait_seconds=30,
):
    """
    Roll back an EBS attachment created by
    attach_ebs_volume_to_asg_instance().
    """

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    volume_id = state["volume_id"]
    instance_id = state["instance_id"]

    client.detach_volume(
        VolumeId=volume_id,
        InstanceId=instance_id,
        Force=True,
    )

    for _ in range(max(1, int(wait_seconds))):
        volume = describe_volume(
            volume_id,
            aws_region,
        )

        if volume["State"] == "available":
            break

        wait_for_seconds(1)

    else:
        raise RuntimeError(
            f"EBS volume '{volume_id}' did not become "
            f"'available' within {wait_seconds} seconds."
        )

    delete_state(STATE_NAME)

    print(
        f"EBS volume {volume_id} detached from "
        f"ASG instance {instance_id} during rollback."
    )


def detach_random_asg_ebs_volume(
    autoscaling_group,
    aws_region,
    force=True,
):
    """
    Select an InService EC2 instance from the Auto Scaling Group
    and detach one non-root EBS volume from it.

    The original attachment information is persisted so that
    rollback can restore the volume to the same instance and
    device.
    """
    if isinstance(force, str):
        force = force.strip().lower() in (
            "true",
            "1",
            "yes",
            "y",
        )

    instance_ids = _get_asg_instances(
        autoscaling_group,
        aws_region,
    )

    client = get_client(aws_region)

    selected_attachment = None

    for instance_id in instance_ids:
        response = client.describe_instances(
            InstanceIds=[instance_id],
        )

        reservations = response.get(
            "Reservations",
            [],
        )

        for reservation in reservations:
            for instance in reservation.get(
                "Instances",
                [],
            ):
                root_device = instance.get("RootDeviceName")

                for attachment in instance.get(
                    "BlockDeviceMappings",
                    [],
                ):
                    ebs = attachment.get("Ebs")

                    if not ebs:
                        continue

                    volume_id = ebs.get("VolumeId")
                    device_name = attachment.get("DeviceName")

                    if not volume_id:
                        continue

                    if device_name == root_device:
                        continue

                    selected_attachment = {
                        "instance_id": instance_id,
                        "volume_id": volume_id,
                        "device_name": device_name,
                    }

                    break

                if selected_attachment:
                    break

            if selected_attachment:
                break

        if selected_attachment:
            break

    if not selected_attachment:
        raise RuntimeError(
            f"No non-root EBS volume found on any "
            f"InService instance in ASG "
            f"'{autoscaling_group}'."
        )

    state = {
        "autoscaling_group": autoscaling_group,
        "instance_id": selected_attachment["instance_id"],
        "volume_id": selected_attachment["volume_id"],
        "device_name": selected_attachment["device_name"],
    }

    client.detach_volume(
        VolumeId=selected_attachment["volume_id"],
        InstanceId=selected_attachment["instance_id"],
        Force=force,
    )

    save_state(
        STATE_NAME,
        state,
    )

    print(
        f"EBS volume {selected_attachment['volume_id']} "
        f"detached from ASG instance "
        f"{selected_attachment['instance_id']} "
        f"from device {selected_attachment['device_name']}."
    )


def restore_asg_ebs_volume(
    aws_region,
    wait_seconds=30,
):
    """
    Restore the EBS attachment captured by
    detach_random_asg_ebs_volume().
    """

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    volume_id = state["volume_id"]
    instance_id = state["instance_id"]
    device_name = state["device_name"]

    for _ in range(max(1, int(wait_seconds))):
        volume = describe_volume(
            volume_id,
            aws_region,
        )

        if volume["State"] == "available":
            break

        wait_for_seconds(1)

    else:
        raise RuntimeError(
            f"EBS volume '{volume_id}' did not become "
            f"'available' within {wait_seconds} seconds."
        )

    client.attach_volume(
        VolumeId=volume_id,
        InstanceId=instance_id,
        Device=device_name,
    )

    delete_state(STATE_NAME)

    print(
        f"EBS volume {volume_id} reattached to "
        f"ASG instance {instance_id} as {device_name}."
    )
