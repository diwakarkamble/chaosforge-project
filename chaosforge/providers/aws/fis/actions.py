import json
import os
import time

import boto3

from chaosforge.providers.aws.fis.catalog import FISCatalog
from chaosforge.providers.aws.fis.template_builder import FISTemplateBuilder


def create_experiment(
    experiment_name,
    description,
    created_by,
    service_id,
    experiment_id,
    target_arn,
    role_arn,
    region,
    recovery_file="",
    cleanup=None,
    **kwargs,
):
    if not str(target_arn or "").strip():
        raise ValueError("Target resource is required for an AWS FIS experiment.")
    if not str(role_arn or "").strip():
        raise ValueError("FIS execution role ARN is required.")

    auto_delete_template = kwargs.get("auto_delete_template", "N")
    poll_interval = float(kwargs.get("poll_interval", 10))
    execution_timeout = float(kwargs.get("execution_timeout", 900))

    catalog = FISCatalog()
    service = catalog.get_service(service_id)
    experiment = catalog.get_experiment(service_id, experiment_id)
    if service is None:
        raise ValueError(f"Unknown service '{service_id}'")
    if experiment is None:
        raise ValueError(f"Unknown experiment '{experiment_id}'")

    template_id = None
    try:
        parameters = {}
        supplied_parameters = kwargs.get("fis_action_parameters_json", "{}")
        if isinstance(supplied_parameters, str):
            try:
                supplied_parameters = json.loads(supplied_parameters or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid serialized AWS FIS action parameters.") from exc
        if not isinstance(supplied_parameters, dict):
            raise TypeError("AWS FIS action parameters must be a JSON object.")
        for parameter in experiment.get("parameters", []):
            name = parameter["name"]
            parameters[name] = supplied_parameters.get(
                name,
                kwargs.get(name, parameter.get("default")),
            )
        builder = FISTemplateBuilder()
        template = builder.build(
            service=service,
            experiment=experiment,
            experiment_name=experiment_name,
            description=description,
            target_arn=target_arn,
            role_arn=role_arn,
            parameters=parameters,
            region=region,
            created_by=created_by,
        )
        print()
        print("=" * 70)
        print("Generated FIS Template")
        print("=" * 70)
        print(json.dumps(template, indent=2))
        client = boto3.client("fis", region_name=region)
        response = client.create_experiment_template(**template)
        template_id = response["experimentTemplate"]["id"]
        if recovery_file:
            with open(recovery_file, "w", encoding="utf-8") as handle:
                json.dump({"template_id": template_id}, handle)
        print()
        print("=" * 70)
        print("Template Created")
        print("=" * 70)
        print(f"Template ID : {template_id}")

        response = client.start_experiment(experimentTemplateId=template_id)
        running_experiment_id = response["experiment"]["id"]
        if recovery_file:
            with open(recovery_file, "w", encoding="utf-8") as handle:
                json.dump({"template_id": template_id, "experiment_id": running_experiment_id}, handle)

        status = response["experiment"]["state"]["status"]
        experiment_state = response["experiment"].get("state", {})
        print()
        print("=" * 70)
        print("Experiment Started")
        print("=" * 70)
        print(f"Experiment ID : {running_experiment_id}")
        print(f"Status        : {status}")
        print("=" * 70)
        print()
        print("=" * 70)
        print("Waiting for experiment to finish...")
        print("=" * 70)

        terminal_states = {"completed", "stopped", "failed", "cancelled"}
        started_at = time.monotonic()
        while status not in terminal_states:
            if time.monotonic() - started_at >= execution_timeout:
                raise TimeoutError(
                    f"AWS FIS experiment {running_experiment_id} did not finish within "
                    f"{execution_timeout:g} seconds (last state: {status})."
                )
            response = client.get_experiment(id=running_experiment_id)
            experiment_state = response["experiment"].get("state", {})
            status = experiment_state.get("status", "unknown")
            print(f"Current State : {status}")
            if status not in terminal_states:
                time.sleep(poll_interval)

        if status != "completed":
            reason = experiment_state.get("reason") or "No failure reason was returned by AWS FIS."
            raise RuntimeError(
                f"AWS FIS experiment {running_experiment_id} ended with status '{status}': {reason}"
            )
        failed_actions = [
            f"{action_name}={action.get('state', {}).get('status')}: "
            f"{action.get('state', {}).get('reason') or 'no reason returned'}"
            for action_name, action in response["experiment"].get("actions", {}).items()
            if action.get("state", {}).get("status") not in {None, "completed"}
        ]
        if failed_actions:
            raise RuntimeError("AWS FIS action did not complete successfully: " + "; ".join(failed_actions))
    finally:
        if str(auto_delete_template).upper() == "Y":
            if template_id:
                print()
                print("=" * 70)
                print("Deleting FIS Template...")
                print("=" * 70)
                client.delete_experiment_template(id=template_id)
                print(f"Template {template_id} deleted.")
                print("=" * 70)
            if cleanup:
                cleanup()


def recover_interrupted_experiment(recovery_file, region):
    """Stop an active FIS run and remove the template created for it."""
    messages = []
    success = True

    if not recovery_file or not os.path.exists(recovery_file):
        return {
            "success": False,
            "messages": ["No FIS recovery state was recorded; manual verification is required."],
        }

    with open(recovery_file, encoding="utf-8") as handle:
        state = json.load(handle)

    client = boto3.client("fis", region_name=region)
    experiment_id = state.get("experiment_id")
    template_id = state.get("template_id")

    if experiment_id:
        try:
            status = client.get_experiment(id=experiment_id)["experiment"]["state"]["status"]
            if status not in {"completed", "stopped", "failed"}:
                client.stop_experiment(id=experiment_id)
                messages.append(f"Stop requested for FIS experiment {experiment_id}.")
            else:
                messages.append(f"FIS experiment {experiment_id} is already {status}.")
        except Exception as exc:  # noqa: BLE001
            success = False
            messages.append(f"Failed to stop FIS experiment {experiment_id}: {exc}")

    if template_id:
        try:
            client.delete_experiment_template(id=template_id)
            messages.append(f"Deleted FIS template {template_id}.")
        except Exception as exc:  # noqa: BLE001
            success = False
            messages.append(f"Failed to delete FIS template {template_id}: {exc}")

    return {"success": success, "messages": messages}


def start_experiment(template_id, region):

    client = boto3.client("fis", region_name=region)

    response = client.start_experiment(experimentTemplateId=template_id)

    experiment = response["experiment"]

    return experiment


def stop_experiment(experiment_id, region):

    client = boto3.client("fis", region_name=region)

    response = client.stop_experiment(id=experiment_id)

    experiment = response["experiment"]

    return experiment


def delete_template(template_id, region):

    client = boto3.client("fis", region_name=region)

    response = client.get_experiment_template(id=template_id)

    template = response["experimentTemplate"]

    print()
    print("=" * 70)
    print("Delete FIS Template")
    print("=" * 70)

    print(f"Template ID  : {template['id']}")
    print(f"Description  : {template.get('description', '-')}")

    print()

    confirm = (
        input("Are you sure you want to delete this template? (y/n): ").strip().lower()
    )

    if confirm != "y":
        print("\nDeletion cancelled.")
        return

    client.delete_experiment_template(id=template_id)

    print()
    print("=" * 70)
    print("Template Deleted Successfully")
    print("=" * 70)


def execute_management_action(experiment_id, variables):
    """Run direct AWS SDK operations that formerly used Toolkit JSON wrappers."""
    region = variables["aws_region"]
    if experiment_id == "fis-start-template":
        return start_experiment(variables["experiment_template_id"], region)
    if experiment_id == "fis-stop-experiment":
        return stop_experiment(variables["experiment_id"], region)
    if experiment_id == "fis-delete-template":
        return delete_template(variables["template_id"], region)
    raise ValueError(f"Unsupported direct FIS management action '{experiment_id}'.")
