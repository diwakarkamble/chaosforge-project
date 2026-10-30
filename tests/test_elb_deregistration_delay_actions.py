from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions import (
    get_deregistration_delay,
    modify_deregistration_delay,
    restore_deregistration_delay,
)

# ----------------------------------------------------------
# get_deregistration_delay
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.get_client")
def test_get_deregistration_delay(mock_get_client):

    client = MagicMock()

    client.describe_target_group_attributes.return_value = {
        "Attributes": [
            {
                "Key": "deregistration_delay.timeout_seconds",
                "Value": "300",
            }
        ]
    }

    mock_get_client.return_value = client

    result = get_deregistration_delay(
        "target-group-arn",
        "eu-central-1",
    )

    assert result == "300"

    client.describe_target_group_attributes.assert_called_once_with(
        TargetGroupArn="target-group-arn",
    )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.get_client")
def test_get_deregistration_delay_missing_attribute(
    mock_get_client,
):

    client = MagicMock()

    client.describe_target_group_attributes.return_value = {"Attributes": []}

    mock_get_client.return_value = client

    with pytest.raises(
        RuntimeError,
        match="deregistration_delay.timeout_seconds",
    ):
        get_deregistration_delay(
            "target-group-arn",
            "eu-central-1",
        )


# ----------------------------------------------------------
# modify_deregistration_delay
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.save_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.get_client")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.get_deregistration_delay")
def test_modify_deregistration_delay(
    mock_get_delay,
    mock_get_client,
    mock_save_state,
):

    mock_get_delay.return_value = "300"

    client = MagicMock()
    mock_get_client.return_value = client

    modify_deregistration_delay(
        target_group_arn="target-group-arn",
        deregistration_delay="10",
        aws_region="eu-central-1",
    )

    mock_save_state.assert_called_once_with(
        "chaosforge_elb_deregistration_delay",
        {
            "target_group_arn": "target-group-arn",
            "original_value": "300",
        },
    )

    client.modify_target_group_attributes.assert_called_once_with(
        TargetGroupArn="target-group-arn",
        Attributes=[
            {
                "Key": "deregistration_delay.timeout_seconds",
                "Value": "10",
            }
        ],
    )


# ----------------------------------------------------------
# modify validation
# ----------------------------------------------------------


def test_modify_deregistration_delay_missing_target_group():

    with pytest.raises(
        ValueError,
        match="target group ARN is required",
    ):
        modify_deregistration_delay(
            target_group_arn=None,
            deregistration_delay="10",
            aws_region="eu-central-1",
        )


def test_modify_deregistration_delay_missing_value():

    with pytest.raises(
        ValueError,
        match="Deregistration delay value is required",
    ):
        modify_deregistration_delay(
            target_group_arn="target-group-arn",
            deregistration_delay=None,
            aws_region="eu-central-1",
        )


def test_modify_deregistration_delay_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        modify_deregistration_delay(
            target_group_arn="target-group-arn",
            deregistration_delay="10",
            aws_region=None,
        )


# ----------------------------------------------------------
# restore_deregistration_delay
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.delete_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.load_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_deregistration_delay_actions.get_client")
def test_restore_deregistration_delay(
    mock_get_client,
    mock_load_state,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "target_group_arn": "target-group-arn",
        "original_value": "300",
    }

    client = MagicMock()
    mock_get_client.return_value = client

    restore_deregistration_delay(
        aws_region="eu-central-1",
    )

    client.modify_target_group_attributes.assert_called_once_with(
        TargetGroupArn="target-group-arn",
        Attributes=[
            {
                "Key": "deregistration_delay.timeout_seconds",
                "Value": "300",
            }
        ],
    )

    mock_delete_state.assert_called_once_with("chaosforge_elb_deregistration_delay")


def test_restore_deregistration_delay_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        restore_deregistration_delay(
            aws_region=None,
        )
