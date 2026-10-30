from copy import deepcopy

from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common import (
    delete_state,
    describe_task_definition,
    find_service,
    load_state,
    register_task_definition,
    save_state,
    update_service,
)

EXPERIMENT_NAME = "ecs_cpu_modification"


# ----------------------------------------------------------
# Capture Current Task Definition
# ----------------------------------------------------------


def capture_current_task_definition(
    ecs_service,
    aws_region,
):

    cluster, service = find_service(
        ecs_service,
        aws_region,
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
# Update CPU
# ----------------------------------------------------------


def update_cpu(
    ecs_service,
    target_cpu,
    aws_region,
):

    cluster, service = find_service(
        ecs_service,
        aws_region,
    )

    task_definition = describe_task_definition(
        service["taskDefinition"],
        aws_region,
    )

    task_definition = deepcopy(task_definition)

    task_definition["cpu"] = str(target_cpu)

    new_task_definition = register_task_definition(
        task_definition,
        aws_region,
    )

    update_service(
        cluster,
        ecs_service,
        aws_region,
        taskDefinition=new_task_definition,
        forceNewDeployment=True,
    )

    print(f"CPU updated to {target_cpu}")


# ----------------------------------------------------------
# Restore
# ----------------------------------------------------------


def restore_cpu(
    ecs_service,
    aws_region,
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
