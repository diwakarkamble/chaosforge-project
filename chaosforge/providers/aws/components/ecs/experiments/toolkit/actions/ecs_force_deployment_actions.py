from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common import (
    delete_state,
    find_service,
    load_state,
    save_state,
    update_service,
)

EXPERIMENT_NAME = "ecs_force_deployment"


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
# Force Deployment
# ----------------------------------------------------------


def force_new_deployment(
    ecs_service,
    aws_region,
    ecs_cluster=None,
):

    cluster, _ = find_service(
        ecs_service,
        aws_region,
        ecs_cluster=ecs_cluster,
    )

    update_service(
        cluster,
        ecs_service,
        aws_region,
        forceNewDeployment=True,
    )

    print("Force deployment triggered.")


# ----------------------------------------------------------
# Rollback
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
