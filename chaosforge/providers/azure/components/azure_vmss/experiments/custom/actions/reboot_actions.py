"""Azure Compute SDK actions for VM Scale Set instance reboots."""

import random

from chaosforge.providers.azure.resource_id import resource_name


def restart_instances(subscription_id, resource_group, resource_id, instance_criteria=None):
    """Restart selected VMSS instances, or one random instance when none are selected."""
    _require(subscription_id, resource_group, resource_id)
    scale_set_name = resource_name(resource_id)
    client = _client(subscription_id)
    instance_ids = [
        str(criteria["instanceId"])
        for criteria in instance_criteria or []
        if isinstance(criteria, dict) and criteria.get("instanceId") is not None
    ]
    if not instance_ids:
        available = [
            str(instance.instance_id)
            for instance in client.virtual_machine_scale_set_vms.list(resource_group, scale_set_name)
            if getattr(instance, "instance_id", None) is not None
        ]
        if not available:
            raise ValueError("The selected virtual machine scale set has no instances.")
        instance_ids = [random.choice(available)]
    for instance_id in instance_ids:
        client.virtual_machine_scale_set_vms.begin_restart(
            resource_group, scale_set_name, instance_id
        ).result()
    return {"instance_ids": instance_ids}


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
