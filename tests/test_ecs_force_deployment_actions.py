from unittest.mock import patch

from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions import (
    capture_current_task_definition,
    force_new_deployment,
    restore_task_definition,
)

# ----------------------------------------------------------
# Capture Current Task Definition
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.save_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.find_service")
def test_capture_current_task_definition(
    mock_find_service,
    mock_save_state,
):

    mock_find_service.return_value = (
        "cluster-1",
        {
            "taskDefinition": "task:1",
        },
    )

    capture_current_task_definition(
        "demo-service",
        "eu-west-1",
    )

    mock_save_state.assert_called_once()


# ----------------------------------------------------------
# Force Deployment
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.find_service")
def test_force_new_deployment(
    mock_find_service,
    mock_update_service,
):

    mock_find_service.return_value = (
        "cluster-1",
        {},
    )

    force_new_deployment(
        "demo-service",
        "eu-west-1",
    )

    mock_update_service.assert_called_once_with(
        "cluster-1",
        "demo-service",
        "eu-west-1",
        forceNewDeployment=True,
    )


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.find_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.update_service")
def test_force_new_deployment_uses_selected_cluster(mock_update_service, mock_find_service):
    mock_find_service.return_value = ("cluster-1", {})

    force_new_deployment("demo-service", "eu-west-1", ecs_cluster="selected-cluster")

    mock_find_service.assert_called_once_with(
        "demo-service", "eu-west-1", ecs_cluster="selected-cluster"
    )


# ----------------------------------------------------------
# Restore Task Definition
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.delete_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.load_state")
def test_restore_task_definition(
    mock_load_state,
    mock_update_service,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "cluster": "cluster-1",
        "service": "demo-service",
        "task_definition": "task:1",
    }

    restore_task_definition(
        "demo-service",
        "eu-west-1",
    )

    mock_update_service.assert_called_once_with(
        "cluster-1",
        "demo-service",
        "eu-west-1",
        taskDefinition="task:1",
        forceNewDeployment=True,
    )

    mock_delete_state.assert_called_once()


# ----------------------------------------------------------
# Save State Called
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.save_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.find_service")
def test_capture_calls_save_state(
    mock_find_service,
    mock_save_state,
):

    mock_find_service.return_value = (
        "cluster-1",
        {
            "taskDefinition": "task:1",
        },
    )

    capture_current_task_definition(
        "demo-service",
        "eu-west-1",
    )

    mock_save_state.assert_called_once()


# ----------------------------------------------------------
# Delete State Called
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.delete_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_force_deployment_actions.load_state")
def test_restore_calls_delete_state(
    mock_load_state,
    mock_update_service,
    mock_delete_state,
):

    mock_load_state.return_value = {
        "cluster": "cluster",
        "service": "service",
        "task_definition": "task:1",
    }

    restore_task_definition(
        "service",
        "eu-west-1",
    )

    mock_delete_state.assert_called_once()
