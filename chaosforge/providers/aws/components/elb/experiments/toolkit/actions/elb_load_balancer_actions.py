from .elb_common import (
    delete_state,
    get_client,
    load_state,
    save_state,
)

STATE_NAME = "chaosforge_elb_load_balancer"


def get_load_balancer_attributes(
    load_balancer_arn,
    aws_region,
):
    if not load_balancer_arn:
        raise ValueError("Load balancer ARN is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    client = get_client(aws_region)

    response = client.describe_load_balancer_attributes(
        LoadBalancerArn=load_balancer_arn,
    )

    return response.get(
        "Attributes",
        [],
    )


def get_attribute_value(
    attributes,
    attribute_key,
):
    for attribute in attributes:
        if attribute.get("Key") == attribute_key:
            return attribute.get("Value")

    return None


def modify_load_balancer_attribute(
    load_balancer_arn,
    attribute_key,
    attribute_value,
    aws_region,
):
    if not load_balancer_arn:
        raise ValueError("Load balancer ARN is required.")

    if not attribute_key:
        raise ValueError("Load balancer attribute key is required.")

    if attribute_value is None:
        raise ValueError("Load balancer attribute value is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    attributes = get_load_balancer_attributes(
        load_balancer_arn,
        aws_region,
    )

    original_value = get_attribute_value(
        attributes,
        attribute_key,
    )

    if original_value is None:
        raise RuntimeError(f"Load balancer attribute '{attribute_key}' was not found.")

    save_state(
        STATE_NAME,
        {
            "load_balancer_arn": load_balancer_arn,
            "attribute_key": attribute_key,
            "original_value": original_value,
        },
    )

    client = get_client(aws_region)

    client.modify_load_balancer_attributes(
        LoadBalancerArn=load_balancer_arn,
        Attributes=[
            {
                "Key": attribute_key,
                "Value": str(attribute_value),
            }
        ],
    )

    print(
        f"ELB load balancer attribute "
        f"'{attribute_key}' changed from "
        f"'{original_value}' to "
        f"'{attribute_value}'."
    )


def restore_load_balancer_attribute(
    aws_region,
):
    if not aws_region:
        raise ValueError("AWS region is required.")

    state = load_state(STATE_NAME)

    client = get_client(aws_region)

    client.modify_load_balancer_attributes(
        LoadBalancerArn=state["load_balancer_arn"],
        Attributes=[
            {
                "Key": state["attribute_key"],
                "Value": state["original_value"],
            }
        ],
    )

    delete_state(STATE_NAME)

    print(
        f"ELB load balancer attribute "
        f"'{state['attribute_key']}' restored "
        f"to '{state['original_value']}'."
    )
