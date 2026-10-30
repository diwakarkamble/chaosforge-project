from unittest.mock import patch

from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions import (
    capture_current_task_definition,
    restore_memory,
    update_memory,
)

# ----------------------------------------------------------
# Capture Current Task Definition
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.save_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.find_service")
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
# Update Memory
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.register_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.describe_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.find_service")
def test_update_memory(
    mock_find_service,
    mock_describe,
    mock_register,
    mock_update,
):

    mock_find_service.return_value = (
        "cluster-1",
        {
            "taskDefinition": "task:1",
        },
    )

    mock_describe.return_value = {
        "family": "demo",
        "networkMode": "awsvpc",
        "containerDefinitions": [],
        "memory": "512",
    }

    mock_register.return_value = "task:2"

    update_memory(
        "demo-service",
        1024,
        "eu-west-1",
    )

    task_definition = mock_register.call_args.args[0]

    assert task_definition["memory"] == "1024"

    mock_update.assert_called_once()


# ----------------------------------------------------------
# Restore Memory
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.delete_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.load_state")
def test_restore_memory(
    mock_load_state,
    mock_update,
    mock_delete,
):

    mock_load_state.return_value = {
        "cluster": "cluster-1",
        "service": "demo-service",
        "task_definition": "task:1",
    }

    restore_memory(
        "demo-service",
        "eu-west-1",
    )

    mock_update.assert_called_once()

    mock_delete.assert_called_once()


# ----------------------------------------------------------
# Memory Updated Correctly
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.register_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.describe_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.find_service")
def test_update_memory_changes_value(
    mock_find_service,
    mock_describe,
    mock_register,
    mock_update,
):

    mock_find_service.return_value = (
        "cluster",
        {
            "taskDefinition": "task:1",
        },
    )

    mock_describe.return_value = {
        "family": "demo",
        "networkMode": "awsvpc",
        "containerDefinitions": [],
        "memory": "512",
    }

    mock_register.return_value = "task:new"

    update_memory(
        "service",
        2048,
        "eu-west-1",
    )

    task_definition = mock_register.call_args.args[0]

    assert task_definition["memory"] == "2048"


# ----------------------------------------------------------
# Register Called Once
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.register_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.describe_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_memory_modification_actions.find_service")
def test_register_called_once(
    mock_find_service,
    mock_describe,
    mock_register,
    mock_update,
):

    mock_find_service.return_value = (
        "cluster",
        {
            "taskDefinition": "task:1",
        },
    )

    mock_describe.return_value = {
        "family": "demo",
        "networkMode": "awsvpc",
        "containerDefinitions": [],
    }

    mock_register.return_value = "task:new"

    update_memory(
        "service",
        4096,
        "eu-west-1",
    )

    mock_register.assert_called_once()
