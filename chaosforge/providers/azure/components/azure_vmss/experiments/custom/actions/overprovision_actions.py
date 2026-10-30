"""Azure VM Scale Set overprovision toggle actions."""

import json

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def disable_overprovision(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); vmss_name = resource_name(resource_id)
    client = _client(subscription_id); scale_set = client.virtual_machine_scale_sets.get(resource_group, vmss_name)
    _path(subscription_id, resource_group, vmss_name).write_text(json.dumps({"overprovision": scale_set.overprovision}), encoding="utf-8")
    return client.virtual_machine_scale_sets.begin_update(
        resource_group, vmss_name, {"properties": {"overprovision": False}}
    ).result()


def restore_overprovision(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); vmss_name = resource_name(resource_id)
    path = _path(subscription_id, resource_group, vmss_name)
    if not path.is_file(): return "No overprovision state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    result = _client(subscription_id).virtual_machine_scale_sets.begin_update(
        resource_group, vmss_name, {"properties": {"overprovision": state["overprovision"]}}
    ).result()
    path.unlink(missing_ok=True)
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.compute import ComputeManagementClient
    except ImportError as exc: raise RuntimeError("Azure Compute SDK dependencies are unavailable.") from exc
    return ComputeManagementClient(DefaultAzureCredential(), subscription_id)


def _path(*parts):
    path = repository_paths().runtime / "azure_vmss"; path.mkdir(parents=True, exist_ok=True)
    return path / ("overprovision-" + "-".join(parts).replace("/", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values): raise ValueError("All action inputs are required.")
