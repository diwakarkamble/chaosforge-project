from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common import (
    delete_state,
    find_service,
    get_previous_task_definition,
    load_state,
    save_state,
    update_service,
)

EXPERIMENT_NAME = "ecs_task_definition_rollback"


# ----------------------------------------------------------
# Capture Current Task Definition
# ----------------------------------------------------------


def capture_current_task_definition(
    ecs_service,
    aws_region,
    ecs_cluster=None,
):

    cluster, service = find_service(
        ecs_service,
        aws_region,
        ecs_cluster=ecs_cluster,
    )

    save_state(
        EXPERIMENT_NAME,
        {
            "cluster": cluster,
            "service": ecs_service,
            "task_definition": service["taskDefinition"],
        },
    )

    print(f"Current Task Definition : {service['taskDefinition']}")


# ----------------------------------------------------------
# Rollback Task Definition
# ----------------------------------------------------------


def rollback_task_definition(
    ecs_service,
    aws_region,
    ecs_cluster=None,
):

    cluster, service = find_service(
        ecs_service,
        aws_region,
        ecs_cluster=ecs_cluster,
    )

    previous_task_definition = get_previous_task_definition(
        service["taskDefinition"],
        aws_region,
    )

    update_service(
        cluster,
        ecs_service,
        aws_region,
        taskDefinition=previous_task_definition,
        forceNewDeployment=True,
    )

    print(f"Rolled back to : {previous_task_definition}")


# ----------------------------------------------------------
# Restore Original Task Definition
# ----------------------------------------------------------


def restore_task_definition(
    ecs_service,
    aws_region,
    ecs_cluster=None,
):

    state = load_state(EXPERIMENT_NAME)

    update_service(
        state["cluster"],
        state["service"],
        aws_region,
        taskDefinition=state["task_definition"],
        forceNewDeployment=True,
    )

    print("Original task definition restored.")

    delete_state(EXPERIMENT_NAME)
