"""Shared interactive menu for Azure component Chaos Studio experiments."""

from azure.identity import DefaultAzureCredential

from chaosforge.application.campaigns.builder import build_experiment
from chaosforge.application.experiment_descriptions import get_experiment_description
from chaosforge.application.experiment_presentation import present_experiment, rich_engine_label
from chaosforge.application.metadata import get_experiments
from chaosforge.application.services.cloud_identity import get_cloud_identity
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import section
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.interfaces.cli.interactive.ui.status import error, info
from chaosforge.interfaces.cli.interactive.ui.tables import menu
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.azure.chaos_studio.classic import AzureChaosIdentityService
from chaosforge.providers.azure.chaos_studio.classic_faults import fault_details
from chaosforge.providers.azure.components.registry import list_component_resources
from chaosforge.providers.azure.discovery import AzureResourceDiscovery


def _select(items, label):
    menu(label, [(index, item["name"]) for index, item in enumerate(items, start=1)])
    try:
        return items[int(prompt(f"Select {label}").strip()) - 1]["id"]
    except (ValueError, IndexError):
        error(f"Invalid {label} selection.")
        return None


def _context(service):
    identity = get_cloud_identity("azure", refresh=True)
    subscription_id = identity.get("subscription_id") or context.azure_subscription
    if not identity.get("authenticated") or not subscription_id:
        error("Log in to Azure before selecting an Azure target.")
        return None
    discovery = AzureResourceDiscovery(subscription_id)
    try:
        resource_group = _select(discovery.list_resource_groups(), "Resource Group")
        if resource_group is None:
            return None
        resource_id = _select(list_component_resources(discovery, service, resource_group), "Target Resource")
    except (ImportError, RuntimeError, ValueError) as exc:
        error(f"Could not discover Azure resources: {exc}")
        return None
    if resource_id is None:
        return None
    context.azure_subscription = subscription_id
    context.azure_resource_group = resource_group
    return subscription_id, resource_group, resource_id


def _identity(service, experiment_id, subscription_id, resource_group, resource_id):
    _urn, _target, role_name = fault_details(service, experiment_id)
    identity_service = AzureChaosIdentityService(subscription_id, DefaultAzureCredential())
    try:
        identities = identity_service.list_identities()
    except (ImportError, RuntimeError, ValueError) as exc:
        error(f"Could not discover chaosforge-managed-identity: {exc}")
        return None
    if not identities:
        if prompt(f"Set up chaosforge-managed-identity with {role_name}? (Y/N)").strip().lower() != "y":
            return None
        try:
            readiness = identity_service.bootstrap(resource_group, resource_id, role_name)
        except RuntimeError as exc:
            error(str(exc))
            return None
        if readiness.get("status") != "ready":
            error(readiness.get("message", "Azure Chaos identity is not ready."))
            return None
        return readiness["identity"]["id"]
    identity = identities[0]
    readiness = identity_service.readiness(identity["id"], resource_id, role_name)
    if readiness.get("status") != "ready":
        info(
            "Could not confirm the Azure Chaos identity role before execution: "
            + readiness.get("message", f"{role_name} is required on the selected target.")
        )
    else:
        info(f"Azure Chaos identity ready: {identity['name']}")
    return identity["id"]


def azure_component_experiment_menu(service):
    while True:
        experiments = get_experiments(service)
        section(service.replace("azure_", "Azure ").replace("_", " ").title())
        menu("", [(index, f"{item['name']} {rich_engine_label(present_experiment(service, item))}") for index, item in enumerate(experiments, start=1)] + [(0, "Back"), ("M", "Main Menu")])
        choice = prompt("Select Experiment").strip().lower()
        if choice == "0":
            return
        if choice == "m":
            raise BackToMainMenu
        try:
            metadata = experiments[int(choice) - 1]
        except (ValueError, IndexError):
            error("Invalid Selection")
            continue
        description = get_experiment_description(service, metadata["id"])
        section("Experiment Description")
        console.print(f"[bold]Description:[/bold] {description.get('description', metadata['name'])}")
        console.print(f"[bold yellow]Potential Impact:[/bold yellow] {description.get('impact', 'Review the configured fault impact.')}")
        console.print(f"[bold green]Expected Behavior:[/bold green] {description.get('expected_behavior', 'Verify workload recovery after cleanup.')}")
        selected = _context(service)
        if selected is None:
            continue
        subscription_id, resource_group, resource_id = selected
        variables = {"subscription_id": subscription_id, "resource_group": resource_group, "resource_id": resource_id}
        if metadata.get("engine") != "Azure SDK":
            identity_id = _identity(service, metadata["id"], subscription_id, resource_group, resource_id)
            if identity_id is None:
                continue
            variables["chaos_identity_id"] = identity_id
        for field in metadata.get("inputs", []):
            if field["name"] in variables:
                continue
            default = field.get("default")
            console.print()
            console.print(f"[bold cyan]{field['label']}[/bold cyan]")
            if default is not None:
                console.print(f"[bright_black]Default : {default}[/bright_black]")
            value = prompt(">").strip() or (default if default is not None else "")
            variables[field["name"]] = value
        experiment = build_experiment(service, metadata, variables)
        console.print(f"[bold green]Experiment created:[/bold green] {experiment.name}")
        return
