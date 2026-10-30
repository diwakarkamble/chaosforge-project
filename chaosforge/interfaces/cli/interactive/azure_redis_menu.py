"""Interactive Azure Cache for Redis experiment menu."""

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
from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
    CHAOS_IDENTITY_NAME,
    AzureRedisChaosIdentityService,
    redis_cache_contributor_assignment_command,
    redis_target_id,
)
from chaosforge.providers.azure.components.registry import list_component_resources
from chaosforge.providers.azure.discovery import AzureResourceDiscovery


def _ensure_azure_context():
    identity = get_cloud_identity("azure", refresh=True)
    subscription_id = identity.get("subscription_id") or context.azure_subscription
    if not identity.get("authenticated") or not subscription_id:
        error("Log in to Azure before selecting an Azure Cache for Redis target.")
        return False

    try:
        groups = AzureResourceDiscovery(subscription_id).list_resource_groups()
    except (ImportError, RuntimeError, ValueError) as exc:
        error(f"Could not discover Azure resource groups: {exc}")
        return False

    if not groups:
        error("No Azure resource groups were found in the active subscription.")
        return False

    section(f"Azure Subscription: {identity['name']}")
    menu("Resource Groups", [(index, group["name"]) for index, group in enumerate(groups, start=1)])
    try:
        resource_group = groups[int(prompt("Select Resource Group")) - 1]["id"]
    except (ValueError, IndexError):
        error("Invalid Resource Group selection.")
        return False

    context.azure_subscription = subscription_id
    context.azure_account_name = identity["name"]
    context.azure_resource_group = resource_group
    return True


def _select_redis_cache():
    try:
        caches = AzureResourceDiscovery(context.azure_subscription).list_redis_caches(
            context.azure_resource_group
        )
    except (ImportError, RuntimeError, ValueError) as exc:
        error(f"Could not discover Azure Cache for Redis instances: {exc}")
        return None
    if not caches:
        info("No Azure Cache for Redis instances were found in this resource group.")
        return None

    section("Azure Cache for Redis")
    menu("Redis Caches", [(index, cache["name"]) for index, cache in enumerate(caches, start=1)])
    try:
        return caches[int(prompt("Select Redis Cache")) - 1]["id"]
    except (ValueError, IndexError):
        error("Invalid Redis Cache selection.")
        return None


def _select_chaos_identity(redis_name):
    try:
        from azure.identity import DefaultAzureCredential

        service = AzureRedisChaosIdentityService(
            context.azure_subscription, DefaultAzureCredential()
        )
        identities = service.list_identities()
    except (ImportError, RuntimeError, ValueError) as exc:
        error(f"Could not discover {CHAOS_IDENTITY_NAME}: {exc}")
        return None
    if not identities:
        console.print(
            f"[yellow]Azure Chaos identity '{CHAOS_IDENTITY_NAME}' was not found.[/yellow]"
        )
        console.print("[cyan]S[/cyan] Set up identity and Redis target permission now")
        console.print("[cyan]C[/cyan] Cancel")
        if prompt("Choice").strip().lower() != "s":
            return None
        target_id = redis_target_id(
            context.azure_subscription, context.azure_resource_group, redis_name
        )
        try:
            readiness = service.bootstrap(context.azure_resource_group, target_id)
        except Exception as exc:  # noqa: BLE001 - Azure RBAC errors vary by tenant.
            error(
                f"Could not set up '{CHAOS_IDENTITY_NAME}'. You need Managed Identity Contributor "
                f"on the identity resource group and Owner or User Access Administrator on {target_id}. {exc}"
            )
            return None
        if readiness["status"] != "ready":
            error(readiness.get("message", "Azure Chaos identity is not ready."))
            return None
        return readiness["identity"]["id"]
    identity = identities[0]
    if len(identities) > 1:
        console.print("\n[bold cyan]Select Azure Chaos Identity[/bold cyan]")
        for index, candidate in enumerate(identities, start=1):
            console.print(
                f"[bold bright_cyan]{index}[/bold bright_cyan]. "
                f"{candidate['name']} ({candidate['resource_group']})"
            )
        try:
            identity = identities[int(prompt("Select Azure Chaos Identity")) - 1]
        except (ValueError, IndexError):
            error("Invalid Azure Chaos Identity selection.")
            return None
    target_id = redis_target_id(
        context.azure_subscription, context.azure_resource_group, redis_name
    )
    readiness = service.readiness(identity["id"], target_id)
    if readiness["status"] != "ready":
        principal_id = readiness.get("identity", identity).get("principal_id", "")
        info(
            "Could not confirm the Azure Chaos identity role before execution: "
            + readiness.get("message", "Azure Chaos identity is not ready.")
        )
        if principal_id:
            console.print("\n[bold yellow]Required Azure role assignment:[/bold yellow]")
            console.print(redis_cache_contributor_assignment_command(principal_id, target_id))
    else:
        info(f"Azure Chaos identity ready: {identity['name']}")
    return identity["id"]


def collect_redis_inputs(metadata):
    """Collect Azure Redis inputs for creation or in-place campaign edits."""
    variables = {
        "subscription_id": context.azure_subscription or "",
        "resource_group": context.azure_resource_group or "",
    }
    for field in metadata.get("inputs", []):
        if field.get("type") == "azure_redis_cache":
            value = _select_redis_cache()
            if value is None:
                return None
            variables[field["name"]] = value
            continue
        if field.get("type") == "azure_component_resource":
            try:
                resources = list_component_resources(
                    AzureResourceDiscovery(context.azure_subscription),
                    "azure_redis",
                    context.azure_resource_group,
                )
            except (ImportError, RuntimeError, ValueError) as exc:
                error(f"Could not discover Azure Cache for Redis instances: {exc}")
                return None
            if not resources:
                info("No Azure Cache for Redis instances were found in this resource group.")
                return None
            section("Azure Cache for Redis")
            menu("Redis Caches", [(index, item["name"]) for index, item in enumerate(resources, start=1)])
            try:
                variables[field["name"]] = resources[int(prompt("Select Redis Cache")) - 1]["id"]
            except (ValueError, IndexError):
                error("Invalid Redis Cache selection.")
                return None
            continue
        if field.get("type") == "azure_redis_chaos_identity":
            value = _select_chaos_identity(variables.get("redis_name", ""))
            if value is None:
                return None
            variables[field["name"]] = value
            continue
        default = field.get("default")
        console.print()
        console.print(f"[bold cyan]{field['label']}[/bold cyan]")
        if default is not None:
            console.print(f"[bright_black]Default : {default}[/bright_black]")
        value = prompt(">").strip()
        if not value and default is not None:
            value = default
        if field.get("required") and str(value or "").strip() == "":
            error(f"{field['label']} is required.")
            return None
        if field.get("type") == "integer" and value != "":
            try:
                value = int(value)
            except (TypeError, ValueError):
                error(f"{field['label']} must be an integer.")
                return None
        if field.get("type") == "choice" and value not in field.get("choices", []):
            error(f"{field['label']} must be one of: {', '.join(field['choices'])}.")
            return None
        variables[field["name"]] = value
    return variables


def redis_experiment_menu():
    if not _ensure_azure_context():
        return

    while True:
        experiments = get_experiments("azure_redis")
        console.print()
        section("Azure Cache for Redis")
        menu(
            "",
            [
                (
                    index,
                    f"{metadata['name']} {rich_engine_label(present_experiment('azure_redis', metadata))}",
                )
                for index, metadata in enumerate(experiments, start=1)
            ]
            + [(0, "Back"), ("M", "Main Menu")],
        )

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

        description = get_experiment_description("azure_redis", metadata.get("id", ""))
        section("Experiment Description")
        console.print(f"[bold]Description:[/bold] {description.get('description', metadata['name'])}")
        console.print(f"[bold yellow]Potential Impact:[/bold yellow] {description.get('impact', 'Review the configured fault impact.')}")
        console.print(f"[bold green]Expected Behavior:[/bold green] {description.get('expected_behavior', 'Verify workload recovery after cleanup.')}")

        variables = collect_redis_inputs(metadata)
        if variables is None:
            continue

        experiment = build_experiment("azure_redis", metadata, variables)
        console.print(f"[bold green]Experiment created:[/bold green] {experiment.name}")
        return
