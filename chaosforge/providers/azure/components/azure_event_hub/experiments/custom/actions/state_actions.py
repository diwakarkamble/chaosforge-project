"""Reversible Event Hubs entity-state disruption actions."""

import json
from pathlib import Path

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def change_event_hub_state(subscription_id, resource_group, resource_id, desired_state, event_hubs):
    """Capture selected entity states before applying the requested disruption."""
    names = _names(event_hubs)
    namespace = resource_name(resource_id)
    client = _client(subscription_id)
    if names == ["*"]:
        names = [item.name for item in client.event_hubs.list_by_namespace(resource_group, namespace)]
    if not names:
        raise ValueError("The selected Event Hubs namespace has no Event Hub entities.")
    snapshots = {}
    for name in names:
        entity = client.event_hubs.get(resource_group, namespace, name)
        snapshots[name] = getattr(entity, "status", None)
    _path(subscription_id, resource_group, namespace).parent.mkdir(parents=True, exist_ok=True)
    _path(subscription_id, resource_group, namespace).write_text(
        json.dumps({"resource_id": resource_id, "entities": snapshots}), encoding="utf-8"
    )
    for name in names:
        entity = client.event_hubs.get(resource_group, namespace, name)
        entity.status = desired_state
        client.event_hubs.create_or_update(resource_group, namespace, name, entity)


def restore_event_hub_state(subscription_id, resource_group, resource_id):
    """Restore exact states captured for the selected namespace."""
    namespace = resource_name(resource_id)
    path = _path(subscription_id, resource_group, namespace)
    if not path.is_file():
        return "No Event Hub state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["resource_id"] != resource_id:
        raise ValueError("Recorded Event Hub rollback state belongs to another namespace.")
    client = _client(subscription_id)
    for name, status in state["entities"].items():
        entity = client.event_hubs.get(resource_group, namespace, name)
        entity.status = status
        client.event_hubs.create_or_update(resource_group, namespace, name, entity)
    path.unlink()


def _names(value):
    names = [name.strip() for name in str(value).split(",") if name.strip()]
    if not names or ("*" in names and names != ["*"]):
        raise ValueError("event_hubs must be '*' or a comma-separated list of Event Hub names.")
    return names


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.eventhub import EventHubManagementClient
    except ImportError as exc:
        raise RuntimeError("Azure Event Hubs SDK dependencies are unavailable.") from exc
    return EventHubManagementClient(DefaultAzureCredential(), subscription_id)


def _path(subscription_id, resource_group, namespace):
    return Path(repository_paths().rollback) / "azure_event_hub" / (
        f"{subscription_id}-{resource_group}-{namespace}.json"
    )
