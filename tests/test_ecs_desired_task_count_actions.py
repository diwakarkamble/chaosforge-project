from unittest.mock import patch

from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions import (
    capture_current_desired_count,
    restore_desired_count,
    update_desired_count,
)

# ----------------------------------------------------------
# Capture Desired Count
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.save_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.find_service")
def test_capture_current_desired_count(
    mock_find_service,
    mock_save_state,
):

    mock_find_service.return_value = (
        "cluster-1",
        {
            "desiredCount": 3,
        },
    )

    capture_current_desired_count(
        "demo-service",
        "eu-west-1",
    )

    mock_save_state.assert_called_once()


# ----------------------------------------------------------
# Update Desired Count
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.find_service")
def test_update_desired_count(
    mock_find_service,
    mock_update_service,
):

    mock_find_service.return_value = (
        "cluster-1",
        {},
    )

    update_desired_count(
        "demo-service",
        5,
        "eu-west-1",
    )

    mock_update_service.assert_called_once_with(
        "cluster-1",
        "demo-service",
        "eu-west-1",
        desiredCount=5,
    )


# ----------------------------------------------------------
# Restore Desired Count
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.delete_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.load_state")
def test_restore_desired_count(
    mock_load_state,
    mock_update_service,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "cluster": "cluster-1",
        "service": "demo-service",
        "desired_count": 2,
    }

    restore_desired_count(
        "demo-service",
        "eu-west-1",
    )

    mock_update_service.assert_called_once_with(
        "cluster-1",
        "demo-service",
        "eu-west-1",
        desiredCount=2,
    )

    mock_delete_state.assert_called_once()


# ----------------------------------------------------------
# Desired Count Converted To Int
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.find_service")
def test_update_desired_count_string(
    mock_find_service,
    mock_update_service,
):

    mock_find_service.return_value = (
        "cluster-1",
        {},
    )

    update_desired_count(
        "demo-service",
        "10",
        "eu-west-1",
    )

    kwargs = mock_update_service.call_args.kwargs

    assert kwargs["desiredCount"] == 10


# ----------------------------------------------------------
# Save State Called
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.save_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.find_service")
def test_capture_calls_save_state(
    mock_find_service,
    mock_save_state,
):

    mock_find_service.return_value = (
        "cluster-1",
        {
            "desiredCount": 1,
        },
    )

    capture_current_desired_count(
        "demo-service",
        "eu-west-1",
    )

    mock_save_state.assert_called_once()


# ----------------------------------------------------------
# Delete State Called
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.delete_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_desired_task_count_actions.load_state")
def test_restore_calls_delete_state(
    mock_load_state,
    mock_update_service,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "cluster": "cluster",
        "service": "service",
        "desired_count": 1,
    }

    restore_desired_count(
        "service",
        "eu-west-1",
    )

    mock_delete_state.assert_called_once()
