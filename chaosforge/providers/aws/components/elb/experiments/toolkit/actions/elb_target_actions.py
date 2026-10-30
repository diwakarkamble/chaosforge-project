from .elb_common import (
    delete_state,
    get_client,
    get_target_registration,
    load_state,
    save_state,
)

STATE_NAME = "chaosforge_elb_target"


def deregister_target(
    target_group_arn,
    target_id,
    aws_region,
):
    """
    Deregister an ELB target and persist its original
    registration information for rollback.
    """

    if not target_group_arn:
        raise ValueError("ELB target group ARN is required.")

    if not target_id:
        raise ValueError("ELB target ID is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    registration = get_target_registration(
        target_group_arn,
        target_id,
        aws_region,
    )

    client = get_client(aws_region)

    state = {
        "target_group_arn": registration["target_group_arn"],
        "target_id": registration["target_id"],
        "port": registration["port"],
    }

    save_state(
        STATE_NAME,
        state,
    )

    target = {
        "Id": registration["target_id"],
    }

    if registration["port"] is not None:
        target["Port"] = registration["port"]

    client.deregister_targets(
        TargetGroupArn=target_group_arn,
        Targets=[target],
    )

    print(f"ELB target {target_id} deregistered from target group {target_group_arn}.")


def restore_target(
    aws_region,
):
    """
    Restore the ELB target captured by deregister_target().
    """

    if not aws_region:
        raise ValueError("AWS region is required.")

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    target = {
        "Id": state["target_id"],
    }

    if state.get("port") is not None:
        target["Port"] = state["port"]

    client.register_targets(
        TargetGroupArn=state["target_group_arn"],
        Targets=[target],
    )

    delete_state(STATE_NAME)

    print(
        f"ELB target {state['target_id']} "
        f"restored to target group "
        f"{state['target_group_arn']}."
    )
