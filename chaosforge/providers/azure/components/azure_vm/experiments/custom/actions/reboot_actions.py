"""Azure Compute SDK action for virtual machine reboots."""

from chaosforge.providers.azure.resource_id import resource_name


def restart_virtual_machine(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id)
    return _client(subscription_id).virtual_machines.begin_restart(
        resource_group, resource_name(resource_id)
    ).result()


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.compute import ComputeManagementClient
    except ImportError as exc:
        raise RuntimeError("Azure Compute SDK dependencies are unavailable.") from exc
    return ComputeManagementClient(DefaultAzureCredential(), subscription_id)


def _require(*values):
    if not all(str(value or "").strip() for value in values):
        raise ValueError("subscription_id, resource_group, and resource_id are required.")
