from .elb_common import (
    delete_state,
    get_client,
    load_state,
    save_state,
)

STATE_NAME = "chaosforge_elb_listener"


def get_listener_attribute(
    listener_arn,
    attribute_key,
    aws_region,
):
    client = get_client(aws_region)

    response = client.describe_listener_attributes(
        ListenerArn=listener_arn,
    )

    for attribute in response.get("Attributes", []):
        if attribute.get("Key") == attribute_key:
            return attribute.get("Value")

    raise RuntimeError(
        f"Listener attribute '{attribute_key}' not found on listener '{listener_arn}'."
    )


def modify_listener_attribute(
    listener_arn,
    attribute_key,
    attribute_value,
    aws_region,
):
    if not listener_arn:
        raise ValueError("Listener ARN is required.")

    if not attribute_key:
        raise ValueError("Listener attribute key is required.")

    if attribute_value is None:
        raise ValueError("Listener attribute value is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    original_value = get_listener_attribute(
        listener_arn,
        attribute_key,
        aws_region,
    )

    state = {
        "listener_arn": listener_arn,
        "attribute_key": attribute_key,
        "original_value": original_value,
    }

    save_state(
        STATE_NAME,
        state,
    )

    client = get_client(aws_region)

    client.modify_listener_attributes(
        ListenerArn=listener_arn,
        Attributes=[
            {
                "Key": attribute_key,
                "Value": str(attribute_value),
            }
        ],
    )

    print(
        f"ELB listener attribute '{attribute_key}' "
        f"modified on listener '{listener_arn}'."
    )


def restore_listener_attribute(
    aws_region,
):
    if not aws_region:
        raise ValueError("AWS region is required.")

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    client.modify_listener_attributes(
        ListenerArn=state["listener_arn"],
        Attributes=[
            {
                "Key": state["attribute_key"],
                "Value": state["original_value"],
            }
        ],
    )

    delete_state(STATE_NAME)

    print(f"ELB listener attribute '{state['attribute_key']}' restored.")
