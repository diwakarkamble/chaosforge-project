from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_load_balancer_actions import (
    modify_load_balancer_attribute,
    restore_load_balancer_attribute,
)


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_load_balancer_actions.get_client")
def test_modify_load_balancer_attribute(
    mock_get_client,
):

    client = MagicMock()

    client.describe_load_balancer_attributes.return_value = {
        "Attributes": [
            {
                "Key": "idle_timeout.timeout_seconds",
                "Value": "60",
            }
        ]
    }

    mock_get_client.return_value = client

    modify_load_balancer_attribute(
        load_balancer_arn="load-balancer-arn",
        attribute_key="idle_timeout.timeout_seconds",
        attribute_value="30",
        aws_region="eu-central-1",
    )

    client.modify_load_balancer_attributes.assert_called_once_with(
        LoadBalancerArn="load-balancer-arn",
        Attributes=[
            {
                "Key": "idle_timeout.timeout_seconds",
                "Value": "30",
            }
        ],
    )


def test_modify_load_balancer_attribute_missing_load_balancer():

    with pytest.raises(
        ValueError,
        match="Load balancer ARN is required",
    ):
        modify_load_balancer_attribute(
            load_balancer_arn=None,
            attribute_key="test",
            attribute_value="test",
            aws_region="eu-central-1",
        )


def test_modify_load_balancer_attribute_missing_key():

    with pytest.raises(
        ValueError,
        match="attribute key is required",
    ):
        modify_load_balancer_attribute(
            load_balancer_arn="load-balancer-arn",
            attribute_key=None,
            attribute_value="test",
            aws_region="eu-central-1",
        )


def test_modify_load_balancer_attribute_missing_value():

    with pytest.raises(
        ValueError,
        match="attribute value is required",
    ):
        modify_load_balancer_attribute(
            load_balancer_arn="load-balancer-arn",
            attribute_key="test",
            attribute_value=None,
            aws_region="eu-central-1",
        )


def test_modify_load_balancer_attribute_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        modify_load_balancer_attribute(
            load_balancer_arn="load-balancer-arn",
            attribute_key="test",
            attribute_value="test",
            aws_region=None,
        )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_load_balancer_actions.delete_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_load_balancer_actions.load_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_load_balancer_actions.get_client")
def test_restore_load_balancer_attribute(
    mock_get_client,
    mock_load_state,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "load_balancer_arn": "load-balancer-arn",
        "attribute_key": "idle_timeout.timeout_seconds",
        "original_value": "60",
    }

    client = MagicMock()
    mock_get_client.return_value = client

    restore_load_balancer_attribute(
        aws_region="eu-central-1",
    )

    client.modify_load_balancer_attributes.assert_called_once()

    mock_delete_state.assert_called_once()


def test_restore_load_balancer_attribute_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        restore_load_balancer_attribute(
            aws_region=None,
        )
