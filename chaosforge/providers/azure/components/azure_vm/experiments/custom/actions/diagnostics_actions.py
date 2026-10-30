"""Azure VM boot-diagnostics toggle actions."""

import json

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def disable_boot_diagnostics(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); vm_name = resource_name(resource_id)
    client = _client(subscription_id); vm = client.virtual_machines.get(resource_group, vm_name)
    boot = vm.diagnostics_profile.boot_diagnostics if vm.diagnostics_profile else None
    _path(subscription_id, resource_group, vm_name).write_text(json.dumps({"enabled": getattr(boot, "enabled", None), "storage_uri": getattr(boot, "storage_uri", None)}), encoding="utf-8")
    return client.virtual_machines.begin_update(
        resource_group,
        vm_name,
        {"properties": {"diagnosticsProfile": {"bootDiagnostics": {"enabled": False}}}},
    ).result()


def restore_boot_diagnostics(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); vm_name = resource_name(resource_id)
    path = _path(subscription_id, resource_group, vm_name)
    if not path.is_file(): return "No boot-diagnostics state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    result = _client(subscription_id).virtual_machines.begin_update(
        resource_group,
        vm_name,
        {
            "properties": {
                "diagnosticsProfile": {
                    "bootDiagnostics": {
                        "enabled": state["enabled"],
                        "storageUri": state["storage_uri"],
                    }
                }
            }
        },
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
    path = repository_paths().runtime / "azure_vm"; path.mkdir(parents=True, exist_ok=True)
    return path / ("boot-diagnostics-" + "-".join(parts).replace("/", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values): raise ValueError("All action inputs are required.")
