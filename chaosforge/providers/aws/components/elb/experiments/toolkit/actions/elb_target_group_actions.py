import json
import os
import tempfile

from .elb_common import (
    get_client,
)

STATE_NAME = "chaosforge_elb_target_group"


def _get_state_file():
    return os.path.join(
        tempfile.gettempdir(),
        f"{STATE_NAME}.json",
    )


def _save_state(data):
    state_file = _get_state_file()

    with open(
        state_file,
        "w",
        encoding="utf-8",
    ) as fp:
        json.dump(
            data,
            fp,
            indent=2,
        )

    print(f"Target group attribute state saved: {state_file}")


def _load_state():
    state_file = _get_state_file()

    if not os.path.exists(state_file):
        raise FileNotFoundError(f"Target group attribute state not found: {state_file}")

    with open(
        state_file,
        encoding="utf-8",
    ) as fp:
        return json.load(fp)


def _delete_state():
    state_file = _get_state_file()

    if os.path.exists(state_file):
        os.remove(state_file)

        print("Target group attribute state deleted.")


def modify_target_group_attribute(
    target_group_arn,
    attribute_key,
    attribute_value,
    aws_region,
):
    """
    Modify a target group attribute and persist the
    original value for rollback.
    """

    if not target_group_arn:
        raise ValueError("Target group ARN is required.")

    if not attribute_key:
        raise ValueError("Target group attribute key is required.")

    if attribute_value is None:
        raise ValueError("Target group attribute value is required.")

    if not aws_region:
        raise ValueError("AWS region is required.")

    client = get_client(aws_region)

    response = client.describe_target_group_attributes(
        TargetGroupArn=target_group_arn,
    )

    attributes = response.get(
        "Attributes",
        [],
    )

    original_value = None

    for attribute in attributes:
        if attribute.get("Key") == attribute_key:
            original_value = attribute.get("Value")

            break

    if original_value is None:
        raise ValueError(f"Target group attribute '{attribute_key}' was not found.")

    state = {
        "target_group_arn": target_group_arn,
        "attribute_key": attribute_key,
        "original_value": original_value,
    }

    _save_state(state)

    client.modify_target_group_attributes(
        TargetGroupArn=target_group_arn,
        Attributes=[
            {
                "Key": attribute_key,
                "Value": str(attribute_value),
            }
        ],
    )

    print(
        f"Target group attribute '{attribute_key}' "
        f"changed from '{original_value}' "
        f"to '{attribute_value}'."
    )


def restore_target_group_attribute(
    aws_region,
):
    """
    Restore the target group attribute captured by
    modify_target_group_attribute().
    """

    if not aws_region:
        raise ValueError("AWS region is required.")

    state = _load_state()

    client = get_client(aws_region)

    client.modify_target_group_attributes(
        TargetGroupArn=state["target_group_arn"],
        Attributes=[
            {
                "Key": state["attribute_key"],
                "Value": state["original_value"],
            }
        ],
    )

    print(
        f"Target group attribute "
        f"'{state['attribute_key']}' restored "
        f"to '{state['original_value']}'."
    )

    _delete_state()
