from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_health_check_actions import (
    modify_health_check,
    restore_health_check,
)


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_health_check_actions.get_client")
def test_modify_health_check(mock_get_client):

    client = MagicMock()

    client.describe_target_groups.return_value = {
        "TargetGroups": [
            {
                "TargetGroupArn": "target-group-arn",
                "HealthCheckEnabled": True,
            }
        ]
    }

    mock_get_client.return_value = client

    modify_health_check(
        target_group_arn="target-group-arn",
        health_check_enabled="false",
        aws_region="eu-central-1",
    )

    client.modify_target_group.assert_called_once_with(
        TargetGroupArn="target-group-arn",
        HealthCheckEnabled=False,
    )


def test_modify_health_check_missing_target_group():

    with pytest.raises(
        ValueError,
        match="target group ARN is required",
    ):
        modify_health_check(
            target_group_arn=None,
            health_check_enabled="false",
            aws_region="eu-central-1",
        )


def test_modify_health_check_missing_value():

    with pytest.raises(
        ValueError,
        match="Health check enabled value is required",
    ):
        modify_health_check(
            target_group_arn="target-group-arn",
            health_check_enabled=None,
            aws_region="eu-central-1",
        )


def test_modify_health_check_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        modify_health_check(
            target_group_arn="target-group-arn",
            health_check_enabled="false",
            aws_region=None,
        )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_health_check_actions.delete_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_health_check_actions.load_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_health_check_actions.get_client")
def test_restore_health_check(
    mock_get_client,
    mock_load_state,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "target_group_arn": "target-group-arn",
        "health_check_enabled": True,
    }

    client = MagicMock()
    mock_get_client.return_value = client

    restore_health_check(
        aws_region="eu-central-1",
    )

    client.modify_target_group.assert_called_once_with(
        TargetGroupArn="target-group-arn",
        HealthCheckEnabled=True,
    )

    mock_delete_state.assert_called_once()


def test_restore_health_check_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        restore_health_check(
            aws_region=None,
        )
