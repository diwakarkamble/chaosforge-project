from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_listener_actions import (
    modify_listener_attribute,
    restore_listener_attribute,
)


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_listener_actions.get_client")
def test_modify_listener_attribute(
    mock_get_client,
):

    client = MagicMock()

    client.describe_listener_attributes.return_value = {
        "Attributes": [
            {
                "Key": "routing.http2.enabled",
                "Value": "true",
            }
        ]
    }

    mock_get_client.return_value = client

    modify_listener_attribute(
        listener_arn="listener-arn",
        attribute_key="routing.http2.enabled",
        attribute_value="false",
        aws_region="eu-central-1",
    )

    client.modify_listener_attributes.assert_called_once_with(
        ListenerArn="listener-arn",
        Attributes=[
            {
                "Key": "routing.http2.enabled",
                "Value": "false",
            }
        ],
    )


def test_modify_listener_attribute_missing_listener():

    with pytest.raises(
        ValueError,
        match="Listener ARN is required",
    ):
        modify_listener_attribute(
            listener_arn=None,
            attribute_key="test",
            attribute_value="test",
            aws_region="eu-central-1",
        )


def test_modify_listener_attribute_missing_key():

    with pytest.raises(
        ValueError,
        match="attribute key is required",
    ):
        modify_listener_attribute(
            listener_arn="listener-arn",
            attribute_key=None,
            attribute_value="test",
            aws_region="eu-central-1",
        )


def test_modify_listener_attribute_missing_value():

    with pytest.raises(
        ValueError,
        match="attribute value is required",
    ):
        modify_listener_attribute(
            listener_arn="listener-arn",
            attribute_key="test",
            attribute_value=None,
            aws_region="eu-central-1",
        )


def test_modify_listener_attribute_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        modify_listener_attribute(
            listener_arn="listener-arn",
            attribute_key="test",
            attribute_value="test",
            aws_region=None,
        )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_listener_actions.delete_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_listener_actions.load_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_listener_actions.get_client")
def test_restore_listener_attribute(
    mock_get_client,
    mock_load_state,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "listener_arn": "listener-arn",
        "attribute_key": "routing.http2.enabled",
        "original_value": "true",
    }

    client = MagicMock()
    mock_get_client.return_value = client

    restore_listener_attribute(
        aws_region="eu-central-1",
    )

    client.modify_listener_attributes.assert_called_once()

    mock_delete_state.assert_called_once()


def test_restore_listener_attribute_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        restore_listener_attribute(
            aws_region=None,
        )
