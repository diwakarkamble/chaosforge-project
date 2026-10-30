from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions import (
    disable_cross_zone,
    get_cross_zone_status,
    restore_cross_zone,
)

TARGET_GROUP_ARN = (
    "arn:aws:elasticloadbalancing:eu-central-1:"
    "123456789012:targetgroup/test/1234567890abcdef"
)
AWS_REGION = "eu-central-1"


# ----------------------------------------------------------
# get_cross_zone_status
# ----------------------------------------------------------


def test_get_cross_zone_status():
    client = MagicMock()

    client.describe_target_group_attributes.return_value = {
        "Attributes": [
            {
                "Key": "load_balancing.cross_zone.enabled",
                "Value": "true",
            }
        ]
    }

    with patch(
        "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.get_client",
        return_value=client,
    ):
        result = get_cross_zone_status(
            TARGET_GROUP_ARN,
            AWS_REGION,
        )

    assert result == "true"

    client.describe_target_group_attributes.assert_called_once_with(
        TargetGroupArn=TARGET_GROUP_ARN,
    )


def test_get_cross_zone_status_missing_target_group():
    with pytest.raises(
        ValueError,
        match="ELB target group ARN is required",
    ):
        get_cross_zone_status(
            None,
            AWS_REGION,
        )


def test_get_cross_zone_status_missing_region():
    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        get_cross_zone_status(
            TARGET_GROUP_ARN,
            None,
        )


def test_get_cross_zone_status_attribute_not_found():
    client = MagicMock()

    client.describe_target_group_attributes.return_value = {
        "Attributes": [
            {
                "Key": "some.other.attribute",
                "Value": "true",
            }
        ]
    }

    with (
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.get_client",
            return_value=client,
        ),
        pytest.raises(
            RuntimeError,
            match="Cross-zone load balancing attribute was not found",
        ),
    ):
        get_cross_zone_status(
            TARGET_GROUP_ARN,
            AWS_REGION,
        )


# ----------------------------------------------------------
# disable_cross_zone
# ----------------------------------------------------------


def test_disable_cross_zone():
    client = MagicMock()

    with (
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.get_cross_zone_status",
            return_value="true",
        ),
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.get_client",
            return_value=client,
        ),
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.save_state",
        ) as save_state,
    ):
        disable_cross_zone(
            TARGET_GROUP_ARN,
            AWS_REGION,
        )

    save_state.assert_called_once_with(
        "chaosforge_elb_cross_zone",
        {
            "target_group_arn": TARGET_GROUP_ARN,
            "original_value": "true",
        },
    )

    client.modify_target_group_attributes.assert_called_once_with(
        TargetGroupArn=TARGET_GROUP_ARN,
        Attributes=[
            {
                "Key": "load_balancing.cross_zone.enabled",
                "Value": "false",
            }
        ],
    )


def test_disable_cross_zone_missing_target_group():
    with pytest.raises(
        ValueError,
        match="ELB target group ARN is required",
    ):
        disable_cross_zone(
            None,
            AWS_REGION,
        )


def test_disable_cross_zone_missing_region():
    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        disable_cross_zone(
            TARGET_GROUP_ARN,
            None,
        )


# ----------------------------------------------------------
# restore_cross_zone
# ----------------------------------------------------------


def test_restore_cross_zone():
    client = MagicMock()

    state = {
        "target_group_arn": TARGET_GROUP_ARN,
        "original_value": "true",
    }

    with (
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.load_state",
            return_value=state,
        ),
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.get_client",
            return_value=client,
        ),
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_cross_zone_actions.delete_state",
        ) as delete_state,
    ):
        restore_cross_zone(
            AWS_REGION,
        )

    client.modify_target_group_attributes.assert_called_once_with(
        TargetGroupArn=TARGET_GROUP_ARN,
        Attributes=[
            {
                "Key": "load_balancing.cross_zone.enabled",
                "Value": "true",
            }
        ],
    )

    delete_state.assert_called_once_with(
        "chaosforge_elb_cross_zone",
    )


def test_restore_cross_zone_missing_region():
    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        restore_cross_zone(
            None,
        )
