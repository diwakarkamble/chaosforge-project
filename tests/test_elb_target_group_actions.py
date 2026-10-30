from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions import (
    modify_target_group_attribute,
    restore_target_group_attribute,
)


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.get_client")
def test_modify_target_group_attribute(mock_get_client):

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

    modify_target_group_attribute(
        target_group_arn="target-group-arn",
        attribute_key="deregistration_delay.timeout_seconds",
        attribute_value="60",
        aws_region="eu-central-1",
    )

    client.modify_target_group_attributes.assert_called_once_with(
        TargetGroupArn="target-group-arn",
        Attributes=[
            {
                "Key": "deregistration_delay.timeout_seconds",
                "Value": "60",
            }
        ],
    )


def test_modify_target_group_attribute_missing_target_group():

    with pytest.raises(
        ValueError,
        match="Target group ARN is required",
    ):
        modify_target_group_attribute(
            target_group_arn=None,
            attribute_key="test",
            attribute_value="test",
            aws_region="eu-central-1",
        )


def test_modify_target_group_attribute_missing_key():

    with pytest.raises(
        ValueError,
        match="Target group attribute key is required",
    ):
        modify_target_group_attribute(
            target_group_arn="target-group-arn",
            attribute_key=None,
            attribute_value="test",
            aws_region="eu-central-1",
        )


def test_modify_target_group_attribute_missing_value():

    with pytest.raises(
        ValueError,
        match="Target group attribute value is required",
    ):
        modify_target_group_attribute(
            target_group_arn="target-group-arn",
            attribute_key="test",
            attribute_value=None,
            aws_region="eu-central-1",
        )


def test_modify_target_group_attribute_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        modify_target_group_attribute(
            target_group_arn="target-group-arn",
            attribute_key="test",
            attribute_value="test",
            aws_region=None,
        )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._delete_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._load_state")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.get_client")
def test_restore_target_group_attribute(
    mock_get_client,
    mock_load_state,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "target_group_arn": "target-group-arn",
        "attribute_key": "deregistration_delay.timeout_seconds",
        "original_value": "300",
    }

    client = MagicMock()
    mock_get_client.return_value = client

    restore_target_group_attribute(
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

    mock_delete_state.assert_called_once()


def test_restore_target_group_attribute_missing_region():

    with pytest.raises(
        ValueError,
        match="AWS region is required",
    ):
        restore_target_group_attribute(
            aws_region=None,
        )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._get_state_file")
def test_save_state(mock_get_state_file):

    from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions import (
        _save_state,
    )

    state = {
        "target_group_arn": "target-group-arn",
        "attribute_key": "deregistration_delay.timeout_seconds",
        "original_value": "300",
    }

    mock_get_state_file.return_value = "test-state.json"

    with (
        patch(
            "builtins.open",
            mock_open(),
        ) as mock_file,
        patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.json.dump") as mock_json_dump,
    ):
        _save_state(state)

    mock_file.assert_called_once_with(
        "test-state.json",
        "w",
        encoding="utf-8",
    )

    mock_json_dump.assert_called_once_with(
        state,
        mock_file.return_value.__enter__.return_value,
        indent=2,
    )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.os.path.exists")
def test_load_state(mock_exists, mock_get_state_file):

    from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions import (
        _load_state,
    )

    state = {
        "target_group_arn": "target-group-arn",
        "attribute_key": "deregistration_delay.timeout_seconds",
        "original_value": "300",
    }

    mock_get_state_file.return_value = "test-state.json"
    mock_exists.return_value = True

    with (
        patch(
            "builtins.open",
            mock_open(),
        ) as mock_file,
        patch(
            "chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.json.load",
            return_value=state,
        ),
    ):
        result = _load_state()

    assert result == state

    mock_file.assert_called_once_with(
        "test-state.json",
        encoding="utf-8",
    )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.os.path.exists")
def test_load_state_missing_file(
    mock_exists,
    mock_get_state_file,
):

    from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions import (
        _load_state,
    )

    mock_get_state_file.return_value = "missing-state.json"
    mock_exists.return_value = False

    with pytest.raises(
        FileNotFoundError,
        match="Target group attribute state not found",
    ):
        _load_state()


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.os.remove")
def test_delete_state(
    mock_remove,
    mock_exists,
    mock_get_state_file,
):

    from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions import (
        _delete_state,
    )

    mock_get_state_file.return_value = "test-state.json"
    mock_exists.return_value = True

    _delete_state()

    mock_remove.assert_called_once_with(
        "test-state.json",
    )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._get_state_file")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.os.remove")
def test_delete_state_missing_file(
    mock_remove,
    mock_exists,
    mock_get_state_file,
):

    from chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions import (
        _delete_state,
    )

    mock_get_state_file.return_value = "missing-state.json"
    mock_exists.return_value = False

    _delete_state()

    mock_remove.assert_not_called()


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.get_client")
def test_modify_target_group_attribute_attribute_not_found(
    mock_get_client,
):

    client = MagicMock()

    client.describe_target_group_attributes.return_value = {
        "Attributes": [
            {
                "Key": "some.other.attribute",
                "Value": "123",
            }
        ]
    }

    mock_get_client.return_value = client

    with pytest.raises(
        ValueError,
        match="Target group attribute.*was not found",
    ):
        modify_target_group_attribute(
            target_group_arn="target-group-arn",
            attribute_key="deregistration_delay.timeout_seconds",
            attribute_value="60",
            aws_region="eu-central-1",
        )

    client.modify_target_group_attributes.assert_not_called()


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.get_client")
def test_modify_target_group_attribute_empty_attributes(
    mock_get_client,
):

    client = MagicMock()

    client.describe_target_group_attributes.return_value = {"Attributes": []}

    mock_get_client.return_value = client

    with pytest.raises(
        ValueError,
        match="Target group attribute.*was not found",
    ):
        modify_target_group_attribute(
            target_group_arn="target-group-arn",
            attribute_key="deregistration_delay.timeout_seconds",
            attribute_value="60",
            aws_region="eu-central-1",
        )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions.get_client")
@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._save_state")
def test_modify_target_group_attribute_numeric_value(
    mock_save_state,
    mock_get_client,
):

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

    modify_target_group_attribute(
        target_group_arn="target-group-arn",
        attribute_key="deregistration_delay.timeout_seconds",
        attribute_value=60,
        aws_region="eu-central-1",
    )

    mock_save_state.assert_called_once_with(
        {
            "target_group_arn": "target-group-arn",
            "attribute_key": "deregistration_delay.timeout_seconds",
            "original_value": "300",
        }
    )

    client.modify_target_group_attributes.assert_called_once_with(
        TargetGroupArn="target-group-arn",
        Attributes=[
            {
                "Key": "deregistration_delay.timeout_seconds",
                "Value": "60",
            }
        ],
    )


@patch("chaosforge.providers.aws.components.elb.experiments.toolkit.actions.elb_target_group_actions._load_state")
def test_restore_target_group_attribute_propagates_missing_state(
    mock_load_state,
):

    mock_load_state.side_effect = FileNotFoundError(
        "Target group attribute state not found"
    )

    with pytest.raises(
        FileNotFoundError,
        match="Target group attribute state not found",
    ):
        restore_target_group_attribute(
            aws_region="eu-central-1",
        )
