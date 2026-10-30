from unittest.mock import patch

from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions import (
    capture_current_task_definition,
    restore_cpu,
    update_cpu,
)

# ----------------------------------------------------------
# Capture Current Task Definition
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.save_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.find_service")
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

    assert (
        capture_current_task_definition(
            "demo-service",
            "eu-west-1",
        )
        is None
    )

    mock_save_state.assert_called_once()


# ----------------------------------------------------------
# Update CPU
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.register_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.describe_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.find_service")
def test_update_cpu(
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
        "cpu": "256",
    }

    mock_register.return_value = "task:2"

    assert (
        update_cpu(
            "demo-service",
            512,
            "eu-west-1",
        )
        is None
    )

    mock_register.assert_called_once()

    task_definition = mock_register.call_args.args[0]

    assert task_definition["cpu"] == "512"

    mock_update.assert_called_once()


# ----------------------------------------------------------
# Restore CPU
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.delete_state")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.load_state")
def test_restore_cpu(
    mock_load_state,
    mock_update,
    mock_delete,
):

    mock_load_state.return_value = {
        "cluster": "cluster-1",
        "service": "demo-service",
        "task_definition": "task:1",
    }

    assert (
        restore_cpu(
            "demo-service",
            "eu-west-1",
        )
        is None
    )

    mock_update.assert_called_once()

    mock_delete.assert_called_once()


# ----------------------------------------------------------
# CPU updated correctly
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.register_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.describe_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.find_service")
def test_update_cpu_changes_value(
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
        "cpu": "256",
    }

    mock_register.return_value = "task:new"

    update_cpu(
        "service",
        1024,
        "eu-west-1",
    )

    task_definition = mock_register.call_args.args[0]

    assert task_definition["cpu"] == "1024"


# ----------------------------------------------------------
# Register called once
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.update_service")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.register_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.describe_task_definition")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_cpu_modification_actions.find_service")
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

    update_cpu(
        "service",
        2048,
        "eu-west-1",
    )

    mock_register.assert_called_once()
