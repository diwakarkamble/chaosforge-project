from .elb_common import (
    delete_state,
    get_client,
    load_state,
    save_state,
)

STATE_NAME = "chaosforge_elb_deregistration_delay"


def get_deregistration_delay(
    target_group_arn,
    aws_region,
):
    client = get_client(aws_region)

    response = client.describe_target_group_attributes(
        TargetGroupArn=target_group_arn,
    )

    for attribute in response.get("Attributes", []):
        if attribute.get("Key") == "deregistration_delay.timeout_seconds":
            return attribute.get("Value")

    raise RuntimeError("deregistration_delay.timeout_seconds attribute was not found.")


def modify_deregistration_delay(
    target_group_arn,
    deregistration_delay,
    aws_region,
):
    if not target_group_arn:
        raise ValueError("ELB target group ARN is required.")

    if deregistration_delay is None:
        raise ValueError("Deregistration delay value is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    original_value = get_deregistration_delay(
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
                "Key": "deregistration_delay.timeout_seconds",
                "Value": str(deregistration_delay),
            }
        ],
    )

    print(
        f"ELB target group {target_group_arn} "
        f"deregistration delay changed to "
        f"{deregistration_delay} seconds."
    )


def restore_deregistration_delay(
    aws_region,
):
    if not aws_region:
        raise ValueError("AWS region is required.")

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    client.modify_target_group_attributes(
        TargetGroupArn=state["target_group_arn"],
        Attributes=[
            {
                "Key": "deregistration_delay.timeout_seconds",
                "Value": str(state["original_value"]),
            }
        ],
    )

    delete_state(STATE_NAME)

    print(
        f"ELB target group "
        f"{state['target_group_arn']} "
        f"deregistration delay restored to "
        f"{state['original_value']} seconds."
    )
