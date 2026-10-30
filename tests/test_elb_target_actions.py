from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions import (
    deregister_target,
    restore_target,
)

# ----------------------------------------------------------
# Deregister validation
# ----------------------------------------------------------


def test_deregister_requires_target_group_arn():

    with pytest.raises(
        ValueError,
        match="ELB target group ARN is required",
    ):
        deregister_target(
            target_group_arn="",
            target_id="target-123",
            aws_region="test-region",
        )


def test_deregister_requires_target_id():

    with pytest.raises(
        ValueError,
        match="ELB target ID is required",
    ):
        deregister_target(
            target_group_arn="tg-arn-123",
            target_id="",
            aws_region="test-region",
        )


def test_deregister_requires_aws_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        deregister_target(
            target_group_arn="tg-arn-123",
            target_id="target-123",
            aws_region="",
        )


# ----------------------------------------------------------
# Deregister
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.save_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_target_registration")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_client")
def test_deregister_target(
    mock_get_client,
    mock_get_target_registration,
    mock_save_state,
):

    client = mock_get_client.return_value

    mock_get_target_registration.return_value = {
        "target_group_arn": "tg-arn-123",
        "target_id": "target-123",
        "port": 8080,
    }

    deregister_target(
        target_group_arn="tg-arn-123",
        target_id="target-123",
        aws_region="test-region",
    )

    mock_get_target_registration.assert_called_once_with(
        "tg-arn-123",
        "target-123",
        "test-region",
    )

    mock_save_state.assert_called_once_with(
        "chaosforge_elb_target",
        {
            "target_group_arn": "tg-arn-123",
            "target_id": "target-123",
            "port": 8080,
        },
    )

    client.deregister_targets.assert_called_once_with(
        TargetGroupArn="tg-arn-123",
        Targets=[
            {
                "Id": "target-123",
                "Port": 8080,
            }
        ],
    )


# ----------------------------------------------------------
# Deregister without explicit port
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.save_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_target_registration")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_client")
def test_deregister_target_without_port(
    mock_get_client,
    mock_get_target_registration,
    mock_save_state,
):

    client = mock_get_client.return_value

    mock_get_target_registration.return_value = {
        "target_group_arn": "tg-arn-123",
        "target_id": "target-123",
        "port": None,
    }

    deregister_target(
        target_group_arn="tg-arn-123",
        target_id="target-123",
        aws_region="test-region",
    )

    mock_save_state.assert_called_once_with(
        "chaosforge_elb_target",
        {
            "target_group_arn": "tg-arn-123",
            "target_id": "target-123",
            "port": None,
        },
    )

    client.deregister_targets.assert_called_once_with(
        TargetGroupArn="tg-arn-123",
        Targets=[
            {
                "Id": "target-123",
            }
        ],
    )


# ----------------------------------------------------------
# Target not found
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_target_registration")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_client")
def test_deregister_target_not_found(
    mock_get_client,
    mock_get_target_registration,
):

    mock_get_target_registration.side_effect = RuntimeError(
        "ELB target 'target-missing' not found"
    )

    with pytest.raises(
        RuntimeError,
        match="ELB target 'target-missing' not found",
    ):
        deregister_target(
            target_group_arn="tg-arn-123",
            target_id="target-missing",
            aws_region="test-region",
        )


# ----------------------------------------------------------
# Restore
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.delete_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_client")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.load_state")
def test_restore_target(
    mock_load_state,
    mock_get_client,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "target_group_arn": "tg-arn-123",
        "target_id": "target-123",
        "port": 8080,
    }

    restore_target(
        aws_region="test-region",
    )

    mock_load_state.assert_called_once_with(
        "chaosforge_elb_target",
    )

    client.register_targets.assert_called_once_with(
        TargetGroupArn="tg-arn-123",
        Targets=[
            {
                "Id": "target-123",
                "Port": 8080,
            }
        ],
    )

    mock_delete_state.assert_called_once_with(
        "chaosforge_elb_target",
    )


# ----------------------------------------------------------
# Restore without explicit port
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.delete_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.get_client")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.load_state")
def test_restore_target_without_port(
    mock_load_state,
    mock_get_client,
    mock_delete_state,
):

    client = mock_get_client.return_value

    mock_load_state.return_value = {
        "target_group_arn": "tg-arn-123",
        "target_id": "target-123",
        "port": None,
    }

    restore_target(
        aws_region="test-region",
    )

    client.register_targets.assert_called_once_with(
        TargetGroupArn="tg-arn-123",
        Targets=[
            {
                "Id": "target-123",
            }
        ],
    )

    mock_delete_state.assert_called_once_with(
        "chaosforge_elb_target",
    )


# ----------------------------------------------------------
# Restore state missing
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_actions.load_state")
def test_restore_state_missing(mock_load_state):

    mock_load_state.side_effect = FileNotFoundError("State file not found")

    with pytest.raises(
        FileNotFoundError,
        match="State file not found",
    ):
        restore_target(
            aws_region="test-region",
        )


# ----------------------------------------------------------
# Restore validation
# ----------------------------------------------------------


def test_restore_requires_aws_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        restore_target(
            aws_region="",
        )
