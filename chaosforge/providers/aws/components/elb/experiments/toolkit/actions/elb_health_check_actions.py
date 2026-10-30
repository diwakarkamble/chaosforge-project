from .elb_common import (
    delete_state,
    get_client,
    load_state,
    save_state,
)

STATE_NAME = "chaosforge_elb_health_check"


def modify_health_check(
    target_group_arn,
    health_check_enabled,
    aws_region,
):
    """
    Temporarily modify the health check configuration of an
    ELB target group and persist the original configuration
    for rollback.
    """

    if not target_group_arn:
        raise ValueError("ELB target group ARN is required.")

    if health_check_enabled is None:
        raise ValueError("Health check enabled value is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    client = get_client(aws_region)

    response = client.describe_target_groups(
        TargetGroupArns=[
            target_group_arn,
        ],
    )

    target_groups = response.get(
        "TargetGroups",
        [],
    )

    if not target_groups:
        raise RuntimeError(f"Target group '{target_group_arn}' not found.")

    original_value = target_groups[0].get("HealthCheckEnabled")

    state = {
        "target_group_arn": target_group_arn,
        "health_check_enabled": original_value,
    }

    save_state(
        STATE_NAME,
        state,
    )

    client.modify_target_group(
        TargetGroupArn=target_group_arn,
        HealthCheckEnabled=(str(health_check_enabled).lower() == "true"),
    )

    print(f"ELB health check changed for target group {target_group_arn}.")


def restore_health_check(
    aws_region,
):
    """
    Restore the original health check configuration.
    """

    if not aws_region:
        raise ValueError("AWS region is required.")

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    client.modify_target_group(
        TargetGroupArn=state["target_group_arn"],
        HealthCheckEnabled=state["health_check_enabled"],
    )

    delete_state(STATE_NAME)

    print(f"ELB health check restored for target group {state['target_group_arn']}.")
