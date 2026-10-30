from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common import (
    delete_state,
    find_service,
    load_state,
    save_state,
    update_service,
)

EXPERIMENT_NAME = "ecs_desired_task_count"


# ----------------------------------------------------------
# Capture current desired count
# ----------------------------------------------------------


def capture_current_desired_count(ecs_service, aws_region):

    cluster, service = find_service(ecs_service, aws_region)

    save_state(
        EXPERIMENT_NAME,
        {
            "cluster": cluster,
            "service": ecs_service,
            "desired_count": service["desiredCount"],
        },
    )

    print(f"Original desired count: {service['desiredCount']}")


# ----------------------------------------------------------
# Update desired count
# ----------------------------------------------------------


def update_desired_count(ecs_service, target_desired_count, aws_region):

    cluster, _ = find_service(ecs_service, aws_region)

    update_service(
        cluster,
        ecs_service,
        aws_region,
        desiredCount=int(target_desired_count),
    )

    print(f"Desired count updated to {target_desired_count}")


# ----------------------------------------------------------
# Restore desired count
# ----------------------------------------------------------


def restore_desired_count(ecs_service, aws_region):

    state = load_state(EXPERIMENT_NAME)

    update_service(
        state["cluster"],
        state["service"],
        aws_region,
        desiredCount=state["desired_count"],
    )

    print(f"Desired count restored to {state['desired_count']}")

    delete_state(EXPERIMENT_NAME)
