"""
Generic Input Engine

Reads experiment metadata,
collects user inputs,
returns variables dictionary.
"""

from chaosforge.application.component_fis import bind_component_fis, fis_target_selector
from chaosforge.application.duration import LOCAL_DURATION_FIELDS, iso8601_duration
from chaosforge.application.field_help import display_label, field_help
from chaosforge.application.validation.input import Validator
from chaosforge.engines.chaos_mesh.target_contract import is_workload_experiment
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.resource_selector import ResourceSelector
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import title
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.interfaces.cli.interactive.ui.status import error
from chaosforge.interfaces.cli.interactive.ui.tables import menu
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.aws.fis.catalog import FISCatalog


def get_input(message):

    value = prompt(message).strip()

    if value.lower() == "m":
        raise BackToMainMenu

    return value


def _validate_fis_parameter(parameter, value):
    field = dict(parameter)

    if "duration" in parameter["name"]:
        field["type"] = "iso8601_duration"

    valid, message = Validator.validate(field, value)

    if not valid:
        return False, value, message

    field_type = field.get("type")

    if field_type == "number":
        number = float(value)
        value = int(number) if number.is_integer() else number
    elif field_type == "boolean" and not isinstance(value, bool):
        value = str(value).strip().lower() in {"true", "yes", "y", "1"}

    return True, value, ""


def collect_inputs(metadata, prefill=None, edit_mode=False):

    if prefill is None:
        prefill = {}

    variables = dict(prefill)

    #
    # Automatically use application region
    #

    variables.setdefault("aws_region", context.region)

    inputs = metadata.get("inputs", [])

    if metadata.get("service") == "fis" and prefill.get("service_id") and prefill.get("experiment_id"):
        metadata = bind_component_fis(metadata, prefill["service_id"], prefill["experiment_id"])
        inputs = metadata["inputs"]

    if not inputs:
        return variables

    title(metadata["name"])

    catalog = FISCatalog()

    selector = None

    for field in inputs:
        while True:
            name = field["name"]
            if name in LOCAL_DURATION_FIELDS:
                field = {**field, "type": "iso8601_duration"}

            if any(
                variables.get(condition) != expected
                for condition, expected in field.get("visible_when", {}).items()
            ):
                break

            default = variables.get(name, field.get("default"))
            if name in LOCAL_DURATION_FIELDS and default not in (None, ""):
                default = iso8601_duration(default)

            #
            # Skip fields already supplied
            #

            if name in variables and not edit_mode:
                if name == "service_id" and selector is None:
                    selector = ResourceSelector(
                        variables.get("aws_region", "eu-central-1")
                    )

                elif name == "experiment_id":
                    experiment = catalog.get_experiment(
                        variables["service_id"], variables["experiment_id"]
                    )

                    if experiment:
                        for parameter in experiment.get("parameters", []):
                            pname = parameter["name"]

                            if pname in variables:
                                continue

                            while True:
                                default = parameter.get("default")
                                console.print()
                                console.print(f"[bold cyan]{parameter['label']}[/bold cyan]")
                                if default is not None:
                                    console.print(f"[bright_black]Default : {default}[/bright_black]")
                                value = prompt(">").strip()

                                if value == "":
                                    value = default

                                valid, value, message = _validate_fis_parameter(
                                    parameter, value
                                )

                                if valid:
                                    break

                                error(message)

                            variables[pname] = value

                break

            #
            # ----------------------------------------------------
            # FIS : Experiment Selection
            # ----------------------------------------------------
            #

            elif name == "experiment_id":
                experiments = catalog.get_experiments(variables["service_id"])

                menu(
                    "Available Experiments",
                    [
                        (index, experiment["name"])
                        for index, experiment in enumerate(experiments, start=1)
                    ],
                )

                choice = get_input("Select Experiment")

                try:
                    experiment = experiments[int(choice) - 1]

                except (ValueError, IndexError):
                    error("Invalid Selection")

                    continue

                variables["experiment_id"] = experiment["id"]

                for parameter in experiment.get("parameters", []):
                    parameter_name = parameter["name"]

                    #
                    # ----------------------------------------------------
                    # FIS parameter: AWS resource selection
                    # ----------------------------------------------------
                    #

                    if parameter.get("type") == "aws_resource":
                        if selector is None:
                            selector = ResourceSelector(
                                variables.get(
                                    "aws_region",
                                    "eu-central-1",
                                )
                            )

                        resource_type = parameter.get("resource_type")

                        if not resource_type:
                            raise ValueError(
                                f"Missing resource_type for FIS parameter "
                                f"'{parameter_name}'"
                            )

                        resource = selector.select(resource_type)

                        if resource is None:
                            return None

                        return_key = parameter.get(
                            "return",
                            parameter.get(
                                "value_key",
                                "id",
                            ),
                        )

                        value = resource.get(return_key)

                        if value is None:
                            raise ValueError(
                                f"Resource '{resource_type}' does not contain "
                                f"'{return_key}'"
                            )

                        variables[parameter_name] = value

                        continue

                    #
                    # ----------------------------------------------------
                    # FIS parameter: Normal input
                    # ----------------------------------------------------
                    #

                    current = variables.get(
                        parameter_name,
                        parameter.get("default", ""),
                    )

                    while True:
                        console.print()
                        console.print(f"[bold cyan]{parameter['label']}[/bold cyan]")
                        if current not in (None, ""):
                            console.print(f"[bright_black]Default : {current}[/bright_black]")
                        value = get_input(">")

                        if value == "":
                            value = current

                        valid, value, message = _validate_fis_parameter(
                            parameter, value
                        )

                        if valid:
                            break

                        error(message)

                    variables[parameter_name] = value

                break

            #
            # ----------------------------------------------------
            # FIS : Target ARN
            # ----------------------------------------------------
            #

            elif name == "target_arn":
                if edit_mode and str(variables.get(name) or "").strip():
                    break

                if selector is None:
                    selector = ResourceSelector(
                        variables.get("aws_region", "eu-central-1")
                    )

                experiment = catalog.get_experiment(
                    variables["service_id"],
                    variables.get("experiment_id"),
                )
                selector_service = fis_target_selector(variables["service_id"], experiment or {})

                # ECS -> Running Task
                if variables["service_id"] == "ecs":
                    resource = selector.select("ecs_task")

                #
                # S3 Bucket
                #

                elif variables["service_id"] == "s3":
                    resource = selector.select("s3")

                #
                # FIS-specific target discovery
                #

                elif selector_service:
                    resource = selector.select(selector_service)

                elif (experiment or {}).get("resource_type"):
                    raise LookupError(
                        f"FIS target selection is not supported for resource type "
                        f"'{experiment['resource_type']}'."
                    )

                #
                # All other AWS services
                #

                else:
                    resource = selector.select(variables["service_id"])

                if resource is None:
                    return None

                target = resource.get("arn") or resource.get("id")

                if not target:
                    raise ValueError("Selected resource does not contain an ARN or ID.")

                variables["target_arn"] = target

                break

            #
            # ----------------------------------------------------
            # Generic AWS Resource Selection
            # ----------------------------------------------------
            #

            elif field.get("type") == "aws_resource":
                resource_type = field.get("resource_type")

                # EKS resources must always be reselected in edit mode.
                # Prevents stale Kubernetes namespace/pod targets from
                # being reused from a previous campaign.
                is_eks_resource = resource_type in (
                    "eks",
                    "eks-namespace",
                    "eks-deployment",
                    "eks-pod",
                    "eks-node",
                )

                if edit_mode and name in variables and not is_eks_resource:
                    break

                if selector is None:
                    selector = ResourceSelector(
                        variables.get("aws_region", "eu-central-1")
                    )

                parent = field.get("parent")

                #
                # Multiple AWS resource selection
                #

                if field.get("multiple"):
                    resource_type = field["resource_type"]

                    resources = selector.select_multiple(resource_type)

                    if resources is None:
                        return None

                    return_value = field.get(
                        "return",
                        "id",
                    )

                    variables[name] = [
                        resource.get(return_value) for resource in resources
                    ]

                    break

                if parent:
                    parent = field.get("parent")

                    parent_field = next(
                        (f for f in inputs if f["name"] == parent), None
                    )

                    parent_type = parent_field["resource_type"]

                    #
                    # EC2 -> EBS Volume
                    #

                    if parent_type == "ec2" and field["resource_type"] in (
                        "ebs-volume",
                        "ebs-volume-available",
                    ):
                        if field["resource_type"] == "ebs-volume":
                            resource = selector.select_ebs_volume(variables[parent])

                        else:
                            resource = selector.select_available_ebs_volume(
                                variables[parent]
                            )

                        if resource is None:
                            return None

                        variables[name] = resource.get(field.get("return", "id"))

                        #
                        # Preserve EBS device name for the experiment
                        #

                        if resource.get("device_name"):
                            variables["device_name"] = resource["device_name"]

                        break

                    parent_label = parent_field.get("label", "Selected Resource")
                    child_label = field.get("label", "Related Resource")
                    console.print()
                    console.print(
                        f"[bold cyan]Loading {child_label}[/bold cyan] "
                        f"for {parent_label}: [bold]{variables[parent]}[/bold]"
                    )

                    #
                    # ASG -> Available EBS Volume
                    #

                    if (
                        parent_type == "autoscaling-group"
                        and field["resource_type"] == "ebs-volume-asg-available"
                    ):
                        resource = selector.select_available_ebs_volume_for_asg(
                            variables[parent]
                        )

                        if resource is None:
                            return None

                        variables[name] = resource.get(field.get("return", "id"))

                        #
                        # Preserve selected device name if discovery
                        # provides one.
                        #

                        if resource.get("device_name"):
                            variables["device_name"] = resource["device_name"]

                        break

                    #
                    # EKS Namespace -> Deployment
                    #
                    # Deployment discovery requires both:
                    #   1. EKS cluster
                    #   2. Kubernetes namespace
                    #
                    # Both values come from previous dropdown selections.
                    #

                    child_parent_value = variables[parent]

                    if parent_type == "eks-namespace" and field["resource_type"] in (
                        "eks-deployment",
                        "eks-pod",
                    ):
                        child_parent_value = (
                            variables["eks_cluster"],
                            variables[parent],
                        )

                    elif parent_type == "eks-namespace" and field["resource_type"] == "eks-container":
                        child_parent_value = (
                            variables["eks_cluster"],
                            variables[parent],
                            {
                                "pod": variables.get("pod", ""),
                                "deployment": variables.get("deployment", ""),
                            },
                        )

                    elif parent_type == "eks-pod" and field["resource_type"] == "eks-volume":
                        child_parent_value = (
                            variables["eks_cluster"],
                            variables["namespace"],
                            variables[parent],
                        )

                    resource = selector.select_child(
                        parent_type,
                        child_parent_value,
                        field["resource_type"],
                    )

                    if resource is None:
                        return None

                    #
                    # Save selected child resource
                    #

                    variables[name] = resource.get(field.get("return", "name"))

                    if (
                        is_workload_experiment(metadata.get("id"))
                        and field.get("resource_type") == "eks-pod"
                    ):
                        pod_context = selector.discovery.get_eks_pod_context(
                            variables["eks_cluster"], variables["namespace"], variables[name]
                        )
                        variables["target_mode"] = "pod"
                        variables["owning_deployment"] = pod_context["owning_deployment"]
                        variables["labels"] = pod_context["labels"]

                    if (
                        is_workload_experiment(metadata.get("id"))
                        and field.get("resource_type") == "eks-deployment"
                    ):
                        deployment_context = selector.discovery.get_eks_deployment_context(
                            variables["eks_cluster"], variables["namespace"], variables[name]
                        )
                        variables["labels"] = deployment_context["labels"]
                        variables["owning_deployment"] = variables[name]

                    #
                    # Preserve original replica count for EKS Replica Reduction
                    #

                    if field["resource_type"] == "eks-deployment":
                        variables["original_replicas"] = resource.get(
                            "replicas",
                            0,
                        )

                    #
                    # Preserve ECS cluster for actions
                    #

                    if field["resource_type"] == "ecs-service":
                        variables["ecs_cluster"] = variables[parent]

                else:
                    resource = selector.select(field["resource_type"])

                    if resource is None:
                        return None

                    variables[name] = resource.get(field.get("return", "name"))

                if field.get("resource_type") == "ecs_service":
                    variables["ecs_cluster"] = resource["cluster"]

                # Preserve API Gateway protocol
                if field.get("resource_type") == "apigateway":
                    context.apigateway_protocol = resource.get("protocol", "REST")

                break

            elif field.get("type") == "aws_fis_template":
                from chaosforge.providers.aws.fis.service import FISService

                templates = FISService(
                    variables.get("aws_region", "eu-central-1")
                ).list_templates()
                if not templates:
                    error("No FIS experiment templates were found in this region.")
                    return None
                menu(
                    "FIS Experiment Templates",
                    [
                        (
                            index,
                            f"{template['id']} - {template.get('description') or 'No description'}",
                        )
                        for index, template in enumerate(templates, start=1)
                    ],
                )
                try:
                    variables[name] = templates[int(get_input("Select FIS Template")) - 1]["id"]
                except (ValueError, IndexError):
                    error("Invalid FIS template selection.")
                    return None
                break

            #
            # ----------------------------------------------------
            # Generic Fields
            # ----------------------------------------------------
            #

            if (
                is_workload_experiment(metadata.get("id"))
                and name == "target_mode"
            ):
                menu(
                    "Select Target Mode",
                    [
                        (1, "By Deployment - target pods via deployment label selector"),
                        (2, "By Pod - target a single specific pod directly"),
                    ],
                )
                choice = get_input(">")
                if choice == "1":
                    variables[name] = "deployment"
                    break
                if choice == "2":
                    variables[name] = "pod"
                    break
                error("Invalid Selection")
                continue

            if (
                is_workload_experiment(metadata.get("id"))
                and name == "mode"
                and variables.get("target_mode") == "pod"
            ):
                variables[name] = "one"
                console.print("[cyan]Chaos mode: one (auto-set for single pod target)[/cyan]")
                break

            if (
                is_workload_experiment(metadata.get("id"))
                and name == "mode"
            ):
                menu(
                    "Select Chaos Mode",
                    [
                        (0, "Back"),
                        (1, "one - randomly pick one pod"),
                        (2, "all - target all matching pods"),
                        (3, "fixed - target an exact number of pods"),
                        (4, "fixed-percent - target a percentage of pods"),
                        (5, "random-max-percent - randomly target up to a percentage"),
                    ],
                )
                modes = {"1": "one", "2": "all", "3": "fixed", "4": "fixed-percent", "5": "random-max-percent"}
                choice = get_input(">")
                if choice == "0":
                    return None
                if choice in modes:
                    variables[name] = modes[choice]
                    break
                error("Invalid Selection")
                continue

            if name == "chaos_value":
                mode = variables.get("chaos_mode", variables.get("mode", ""))
                if mode not in {"fixed", "fixed-percent", "random-max-percent"}:
                    break

            console.print()

            #
            # Display field label
            #

            console.print(f"[bold cyan]{display_label(field)}[/bold cyan]")

            console.print(f"[bright_black]{field_help(field)}[/bright_black]")

            #
            # Show allowed range (if defined)
            #

            if "min" in field or "max" in field:
                minimum = field.get("min", "-")
                maximum = field.get("max", "-")

                console.print(
                    f"[bright_black]Allowed Range : {minimum} - {maximum}[/bright_black]"
                )

            #
            # Show default value (if defined)
            #

            if default is not None:
                console.print(f"[bright_black]Default : {default}[/bright_black]")

            console.print()

            #
            # Read user input
            #

            prompt_text = "Enter true or false" if field.get("type") == "boolean" else ">"
            value = get_input(prompt_text)

            #
            # Use default when user presses Enter
            #

            if value == "" and default is not None:
                value = default

            #
            # Convert value according to field type
            #

            field_type = field.get("type")

            try:
                if field_type == "integer":
                    value = int(value)

                elif field_type == "float":
                    value = float(value)

                elif field_type == "boolean":
                    if isinstance(value, bool):
                        pass

                    else:
                        normalized = str(value).strip().lower()

                        if normalized in ("true", "yes", "y", "1"):
                            value = True

                        elif normalized in ("false", "no", "n", "0"):
                            value = False

                        else:
                            raise ValueError("Enter a valid boolean value.")

                elif field_type == "string":
                    value = str(value)

            except (TypeError, ValueError) as exc:
                error(str(exc))

                continue

            if name == "chaos_value":
                mode = variables.get("chaos_mode", variables.get("mode", ""))
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    error("Mode Value must be a whole number.")
                    continue
                if mode == "fixed" and number < 1:
                    error("Mode Value must be at least 1 for fixed mode.")
                    continue
                if mode in {"fixed-percent", "random-max-percent"} and not 1 <= number <= 100:
                    error("Mode Value must be between 1 and 100 for percentage modes.")
                    continue
                value = str(number)

            #
            # Validate converted value
            #

            valid, message = Validator.validate(field, value)

            if not valid:
                error(message)

                continue

            #
            # Save converted value
            #

            variables[name] = value

            break
    return variables
