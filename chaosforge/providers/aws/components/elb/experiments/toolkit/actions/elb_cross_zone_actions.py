from .elb_common import (
    delete_state,
    get_client,
    load_state,
    save_state,
)

STATE_NAME = "chaosforge_elb_cross_zone"


def get_cross_zone_status(
    target_group_arn,
    aws_region,
):
    """
    Get the current cross-zone load balancing
    configuration for the target group.
    """

    if not target_group_arn:
        raise ValueError("ELB target group ARN is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    client = get_client(aws_region)

    response = client.describe_target_group_attributes(
        TargetGroupArn=target_group_arn,
    )

    for attribute in response.get(
        "Attributes",
        [],
    ):
        if attribute.get("Key") == "load_balancing.cross_zone.enabled":
            return attribute.get("Value")

    raise RuntimeError("Cross-zone load balancing attribute was not found.")


def disable_cross_zone(
    target_group_arn,
    aws_region,
):
    """
    Disable cross-zone load balancing for the
    selected ELB target group.

    The original configuration is saved so that
    rollback can restore it.
    """

    if not target_group_arn:
        raise ValueError("ELB target group ARN is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    attribute_key = "load_balancing.cross_zone.enabled"

    original_value = get_cross_zone_status(
        target_group_arn,
        aws_region,
    )

    save_state(
        STATE_NAME,
        {
            "target_group_arn": target_group_arn,
            "original_value": original_value,
        },
    )

    client = get_client(aws_region)

    client.modify_target_group_attributes(
        TargetGroupArn=target_group_arn,
        Attributes=[
            {
                "Key": attribute_key,
                "Value": "false",
            }
        ],
    )

    print(f"Cross-zone load balancing disabled for target group {target_group_arn}.")


def restore_cross_zone(
    aws_region,
):
    """
    Restore the original cross-zone load balancing
    configuration.
    """

    if not aws_region:
        raise ValueError("AWS region is required.")

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    client.modify_target_group_attributes(
        TargetGroupArn=state["target_group_arn"],
        Attributes=[
            {
                "Key": ("load_balancing.cross_zone.enabled"),
                "Value": state["original_value"],
            }
        ],
    )

    delete_state(STATE_NAME)

    print(
        f"Cross-zone load balancing restored "
        f"for target group "
        f"{state['target_group_arn']}."
    )
