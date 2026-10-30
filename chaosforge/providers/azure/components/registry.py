"""Azure component resource discovery and Chaos Studio role contracts."""

COMPONENT_RESOURCES = {
    "azure_vm": ("virtual machines", "list_virtual_machines"),
    "azure_vmss": ("virtual machine scale sets", "list_virtual_machine_scale_sets"),
    "azure_app_service": ("app services", "list_web_apps"),
    "azure_functions": ("function apps", "list_function_apps"),
    "azure_key_vault": ("key vaults", "list_key_vaults"),
    "azure_cosmos_db": ("Cosmos DB accounts", "list_cosmos_db_accounts"),
    "azure_event_hub": ("Event Hubs namespaces", "list_event_hub_namespaces"),
    "azure_postgres_flexible": ("PostgreSQL flexible servers", "list_postgresql_flexible_servers"),
    "azure_container_apps": ("container apps", "list_container_apps"),
    "azure_redis": ("Redis caches", "list_redis_caches"),
}

COMPONENT_RESOURCE_TYPES = {
    "azure_vm": "Microsoft.Compute/virtualMachines",
    "azure_vmss": "Microsoft.Compute/virtualMachineScaleSets",
    "azure_app_service": "Microsoft.Web/sites",
    "azure_functions": "Microsoft.Web/sites",
    "azure_key_vault": "Microsoft.KeyVault/vaults",
    "azure_cosmos_db": "Microsoft.DocumentDB/databaseAccounts",
    "azure_event_hub": "Microsoft.EventHub/namespaces",
    "azure_postgres_flexible": "Microsoft.DBforPostgreSQL/flexibleServers",
    "azure_container_apps": "Microsoft.App/containerApps",
    "azure_redis": "Microsoft.Cache/Redis",
}


def list_component_resources(discovery, service, resource_group):
    try:
        _label, method_name = COMPONENT_RESOURCES[service]
    except KeyError:
        raise ValueError(f"Unsupported Azure component resource selector: {service}.") from None
    return getattr(discovery, method_name)(resource_group)
