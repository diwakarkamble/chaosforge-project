"""Subscription-scoped Azure resource discovery shared by interfaces."""

import importlib
import json
import re
import subprocess

from chaosforge.common.azure_cli import azure_cli_command

_SUBSCRIPTION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def resolve_subscription_id(value="", *, account=None):
    """Return the canonical Azure subscription UUID for an ID, name, or active login."""
    value = str(value or "").strip()
    if _SUBSCRIPTION_ID.fullmatch(value):
        return value
    if isinstance(account, dict):
        subscription_id = str(account.get("id") or "").strip()
        if _SUBSCRIPTION_ID.fullmatch(subscription_id):
            return subscription_id
    command = azure_cli_command("account", "show")
    if value:
        command.extend(["--subscription", value])
    command.extend(["--output", "json"])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=15
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Azure CLI ('az') is required to resolve the subscription ID.") from exc
    except subprocess.SubprocessError as exc:
        raise RuntimeError(f"Could not resolve Azure subscription: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or f"Could not resolve Azure subscription '{value or 'active subscription'}'."
        )
    try:
        account = json.loads(result.stdout)
        if not isinstance(account, dict):
            raise ValueError("Azure account response must be an object.")
        subscription_id = str(account.get("id") or "").strip()
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("Azure account response did not contain a valid subscription ID.") from exc
    if not _SUBSCRIPTION_ID.fullmatch(subscription_id):
        raise RuntimeError("Azure account response did not contain a valid subscription ID.")
    return subscription_id


class AzureResourceDiscovery:
    def __init__(self, subscription_id):
        if not str(subscription_id or "").strip():
            raise ValueError("Azure subscription ID is required.")
        self.subscription_id = subscription_id

    def list_resource_groups(self):
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.resource import ResourceManagementClient

            client = ResourceManagementClient(DefaultAzureCredential(), self.subscription_id)
            return [
                {"id": group.name, "name": group.name}
                for group in client.resource_groups.list()
                if group.name
            ]
        except Exception as sdk_error:  # noqa: BLE001 - CLI is the interactive fallback.
            try:
                result = subprocess.run(
                    azure_cli_command(
                        "group",
                        "list",
                        "--subscription",
                        self.subscription_id,
                        "--query",
                        "[].name",
                        "--output",
                        "json",
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
            except (FileNotFoundError, subprocess.SubprocessError) as cli_error:
                raise RuntimeError(
                    "Could not load Azure resource groups through the Azure SDK or Azure CLI. "
                    "Run 'az login' and verify subscription access."
                ) from cli_error
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip()
                    or "Could not load Azure resource groups. Verify subscription access."
                ) from sdk_error
            try:
                names = json.loads(result.stdout)
            except (TypeError, ValueError) as cli_error:
                raise RuntimeError("Azure CLI returned an invalid resource group list.") from cli_error
            if not isinstance(names, list):
                raise RuntimeError("Azure CLI returned an invalid resource group list.")
            return [
                {"id": str(name), "name": str(name)}
                for name in names
                if str(name).strip()
            ]

    def list_virtual_machines(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.compute",
            client_name="ComputeManagementClient",
            operation_path="virtual_machines.list",
            cli_command=["az", "vm", "list"],
            component_name="virtual machines",
        )

    def list_virtual_machine_scale_sets(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.compute",
            client_name="ComputeManagementClient",
            operation_path="virtual_machine_scale_sets.list",
            cli_command=["az", "vmss", "list"],
            component_name="virtual machine scale sets",
        )

    def list_virtual_machine_scale_set_instances(self, resource_group, scale_set_name):
        resource_group = str(resource_group or "").strip()
        scale_set_name = str(scale_set_name or "").strip()
        if not resource_group or not scale_set_name:
            raise ValueError("Azure resource group and virtual machine scale set are required.")
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.compute import ComputeManagementClient

            client = ComputeManagementClient(DefaultAzureCredential(), self.subscription_id)
            instances = client.virtual_machine_scale_set_vms.list(resource_group, scale_set_name)
            return [
                {"id": str(instance.instance_id), "name": f"Instance {instance.instance_id}"}
                for instance in instances
                if getattr(instance, "instance_id", None) is not None
            ]
        except Exception as sdk_error:  # noqa: BLE001 - CLI is the interactive fallback.
            command = azure_cli_command(
                "vmss", "list-instances", "--resource-group", resource_group,
                "--name", scale_set_name, "--subscription", self.subscription_id,
                "--query", "[].instanceId", "--output", "json",
            )
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False, timeout=15
                )
            except (FileNotFoundError, subprocess.SubprocessError) as cli_error:
                raise RuntimeError(
                    "Could not load Azure virtual machine scale set instances through the Azure SDK or Azure CLI."
                ) from cli_error
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip() or "Could not load Azure virtual machine scale set instances."
                ) from sdk_error
            try:
                instance_ids = json.loads(result.stdout)
            except (TypeError, ValueError) as cli_error:
                raise RuntimeError("Azure CLI returned an invalid virtual machine scale set instance list.") from cli_error
            if not isinstance(instance_ids, list):
                raise RuntimeError("Azure CLI returned an invalid virtual machine scale set instance list.")
            return [
                {"id": str(instance_id), "name": f"Instance {instance_id}"}
                for instance_id in instance_ids
                if str(instance_id).strip()
            ]

    def list_web_apps(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.web",
            client_name="WebSiteManagementClient",
            operation_path="web_apps.list_by_resource_group",
            cli_command=["az", "webapp", "list"],
            component_name="web apps",
            predicate=lambda resource: "functionapp" not in str(
                self._value(resource, "kind") or ""
            ).lower(),
        )

    def list_function_apps(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.web",
            client_name="WebSiteManagementClient",
            operation_path="web_apps.list_by_resource_group",
            cli_command=["az", "webapp", "list"],
            component_name="function apps",
            predicate=lambda resource: "functionapp" in str(
                self._value(resource, "kind") or ""
            ).lower(),
        )

    def list_key_vaults(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.keyvault",
            client_name="KeyVaultManagementClient",
            operation_path="vaults.list_by_resource_group",
            cli_command=["az", "keyvault", "list"],
            component_name="key vaults",
        )

    def list_cosmos_db_accounts(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.cosmosdb",
            client_name="CosmosDBManagementClient",
            operation_path="database_accounts.list_by_resource_group",
            cli_command=["az", "cosmosdb", "list"],
            component_name="Cosmos DB accounts",
        )

    def list_event_hub_namespaces(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.eventhub",
            client_name="EventHubManagementClient",
            operation_path="namespaces.list_by_resource_group",
            cli_command=["az", "eventhubs", "namespace", "list"],
            component_name="Event Hubs namespaces",
        )

    def list_postgresql_flexible_servers(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.rdbms.postgresql_flexibleservers",
            client_name="PostgreSQLManagementClient",
            operation_path="servers.list_by_resource_group",
            cli_command=["az", "postgres", "flexible-server", "list"],
            component_name="PostgreSQL flexible servers",
        )

    def list_container_apps(self, resource_group):
        return self._list_components(
            resource_group,
            module="azure.mgmt.appcontainers",
            client_name="ContainerAppsAPIClient",
            operation_path="container_apps.list_by_resource_group",
            cli_command=["az", "containerapp", "list"],
            component_name="container apps",
        )

    @staticmethod
    def _value(resource, field):
        return resource.get(field) if isinstance(resource, dict) else getattr(resource, field, None)

    def _list_components(
        self,
        resource_group,
        *,
        module,
        client_name,
        operation_path,
        cli_command,
        component_name,
        predicate=None,
    ):
        """List resource-group components through the SDK, then Azure CLI if needed."""
        resource_group = str(resource_group or "").strip()
        if not resource_group:
            raise ValueError("Azure resource group is required.")
        try:
            from azure.identity import DefaultAzureCredential

            client_type = getattr(importlib.import_module(module), client_name)
            operation = client_type(DefaultAzureCredential(), self.subscription_id)
            for part in operation_path.split("."):
                operation = getattr(operation, part)
            resources = operation(resource_group)
            return self._component_items(resources, predicate)
        except Exception as sdk_error:  # noqa: BLE001 - CLI is the interactive fallback.
            command = azure_cli_command(
                *cli_command[1:],
                "--resource-group",
                resource_group,
                "--subscription",
                self.subscription_id,
                "--output",
                "json",
            )
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False, timeout=15
                )
            except (FileNotFoundError, subprocess.SubprocessError) as cli_error:
                raise RuntimeError(
                    f"Could not load Azure {component_name} through the Azure SDK or Azure CLI. "
                    "Run 'az login' and verify subscription access."
                ) from cli_error
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip() or f"Could not load Azure {component_name}."
                ) from sdk_error
            try:
                resources = json.loads(result.stdout)
            except (TypeError, ValueError) as cli_error:
                raise RuntimeError(f"Azure CLI returned an invalid {component_name} list.") from cli_error
            if not isinstance(resources, list):
                raise RuntimeError(f"Azure CLI returned an invalid {component_name} list.")
            return self._component_items(resources, predicate)

    def _component_items(self, resources, predicate):
        items = []
        for resource in resources:
            name = self._value(resource, "name")
            resource_id = self._value(resource, "id")
            if not name or not resource_id or (predicate and not predicate(resource)):
                continue
            items.append({"id": str(resource_id), "name": str(name)})
        return sorted(items, key=lambda item: item["name"].lower())

    def list_aks_cluster_names(self, resource_group):
        """List AKS cluster names within one selected resource group."""
        if not str(resource_group or "").strip():
            return []
        try:
            result = subprocess.run(
                azure_cli_command(
                    "aks", "list", "--resource-group", resource_group,
                    "--subscription", self.subscription_id,
                    "--query", "[].name", "--output", "json",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Could not load AKS clusters through the Azure CLI.") from exc
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Could not load AKS clusters.")
        try:
            names = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Azure CLI returned an invalid AKS cluster list.") from exc
        if not isinstance(names, list):
            raise RuntimeError("Azure CLI returned an invalid AKS cluster list.")
        return [str(name) for name in names if str(name).strip()]

    def list_redis_caches(self, resource_group):
        if not str(resource_group or "").strip():
            raise ValueError("Azure resource group is required.")
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.redis import RedisManagementClient

        client = RedisManagementClient(DefaultAzureCredential(), self.subscription_id)
        return [
            {"id": cache.name, "name": cache.name}
            for cache in client.redis.list_by_resource_group(resource_group)
            if cache.name
        ]
