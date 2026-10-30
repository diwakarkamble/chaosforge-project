"""Azure SDK actions for App Service slot swap experiments."""

import json

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def swap_slots(subscription_id, resource_group, resource_id, source_slot, target_slot):
    _require(subscription_id, resource_group, resource_id, source_slot, target_slot)
    app_name = resource_name(resource_id)
    _state_path(subscription_id, resource_group, app_name).write_text(json.dumps({
        "source_slot": source_slot, "target_slot": target_slot
    }), encoding="utf-8")
    return _client(subscription_id).web_apps.begin_swap_slot(
        resource_group, app_name, source_slot, {"targetSlot": target_slot, "preserveVnet": False}
    ).result()


def restore_slot_swap(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id)
    app_name = resource_name(resource_id)
    path = _state_path(subscription_id, resource_group, app_name)
    if not path.is_file():
        return "No slot-swap state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    result = _client(subscription_id).web_apps.begin_swap_slot(
        resource_group,
        app_name,
        state["target_slot"],
        {"targetSlot": state["source_slot"], "preserveVnet": False},
    ).result()
    path.unlink(missing_ok=True)
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.web import WebSiteManagementClient
    except ImportError as exc:
        raise RuntimeError("Azure App Service SDK dependencies are unavailable.") from exc
    return WebSiteManagementClient(DefaultAzureCredential(), subscription_id)


def _state_path(*parts):
    path = repository_paths().runtime / "azure_app_service"
    path.mkdir(parents=True, exist_ok=True)
    return path / ("slot-swap-" + "-".join(parts).replace("/", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values):
        raise ValueError("All action inputs are required.")
