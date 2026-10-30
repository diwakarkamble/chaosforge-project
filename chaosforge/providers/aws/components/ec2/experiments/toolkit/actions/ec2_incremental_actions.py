import json
import time

from chaosforge.common.paths import repository_paths
from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions.ec2_common import (
    get_client,
)


def stop_instances_incrementally(
    instance_ids,
    step_quantity,
    step_duration,
    aws_region,
):
    """
    Stop EC2 instances incrementally in batches.

    Accepts either a list of instance IDs or a JSON/string
    representation of instance IDs.

    Examples:
        ["i-1", "i-2", "i-3"]
        '["i-1", "i-2", "i-3"]'
        "i-1"
    """

    if not instance_ids:
        raise ValueError("At least one EC2 instance ID is required.")

    step_quantity = int(step_quantity)

    if step_quantity < 1:
        raise ValueError("Step quantity must be at least 1.")

    step_duration = int(step_duration)

    if step_duration < 0:
        raise ValueError("Step duration cannot be negative.")

    instance_ids = _normalize(instance_ids)

    if not instance_ids:
        raise ValueError("At least one EC2 instance ID is required.")

    client = get_client(aws_region)
    states = _states(client, instance_ids)
    running = [instance_id for instance_id in instance_ids if states[instance_id] == "running"]
    path = _path(aws_region, instance_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"instance_ids": instance_ids, "running": running}), encoding="utf-8"
    )

    # ----------------------------------------------------------
    # Stop instances in batches
    # ----------------------------------------------------------

    for start in range(
        0,
        len(running),
        step_quantity,
    ):
        batch = running[start : start + step_quantity]

        print(f"Stopping EC2 instances: {batch}")

        client.stop_instances(
            InstanceIds=batch,
        )

        remaining = start + step_quantity

        if remaining < len(running):
            print(f"Waiting {step_duration} seconds before next batch.")

            time.sleep(step_duration)


def restore_incrementally_stopped_instances(instance_ids, aws_region):
    """Restart only instances that were running before the fault."""
    instance_ids = _normalize(instance_ids)
    path = _path(aws_region, instance_ids)
    if not path.is_file():
        return "No EC2 rollback state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["instance_ids"] != instance_ids:
        raise ValueError("Recorded EC2 rollback state belongs to another instance selection.")
    if state["running"]:
        get_client(aws_region).start_instances(InstanceIds=state["running"])
    path.unlink()


def _normalize(instance_ids):
    if isinstance(instance_ids, str):
        try:
            parsed = json.loads(instance_ids.strip())
        except json.JSONDecodeError:
            parsed = instance_ids
        instance_ids = [parsed] if isinstance(parsed, str) else parsed
    if not isinstance(instance_ids, (list, tuple)):
        raise TypeError("instance_ids must be an EC2 instance ID or a list of EC2 instance IDs.")
    return [str(instance_id).strip() for instance_id in instance_ids if str(instance_id).strip()]


def _states(client, instance_ids):
    states = {}
    for reservation in client.describe_instances(InstanceIds=instance_ids).get("Reservations", []):
        for instance in reservation.get("Instances", []):
            states[instance["InstanceId"]] = instance["State"]["Name"]
    if set(states) != set(instance_ids):
        raise ValueError("Could not resolve every selected EC2 instance.")
    return states


def _path(aws_region, instance_ids):
    return repository_paths().rollback / "ec2" / (
        f"incremental-stop-{aws_region}-{'-'.join(sorted(instance_ids))}.json"
    )
