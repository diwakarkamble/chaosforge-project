"""Azure Event Hubs namespace public-network disruption actions."""

import json

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def disable_public_access(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); namespace_name = resource_name(resource_id)
    client = _client(subscription_id)
    namespace = client.namespaces.get(resource_group, namespace_name)
    _path(subscription_id, resource_group, namespace_name).write_text(json.dumps({"public_network_access": namespace.public_network_access}), encoding="utf-8")
    namespace.public_network_access = "Disabled"
    return client.namespaces.update(resource_group, namespace_name, namespace)


def restore_public_access(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); namespace_name = resource_name(resource_id)
    path = _path(subscription_id, resource_group, namespace_name)
    if not path.is_file(): return "No public-access state was recorded."
    client = _client(subscription_id)
    namespace = client.namespaces.get(resource_group, namespace_name)
    namespace.public_network_access = json.loads(path.read_text(encoding="utf-8"))["public_network_access"]
    result = client.namespaces.update(resource_group, namespace_name, namespace)
    path.unlink(missing_ok=True)
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.eventhub import EventHubManagementClient
    except ImportError as exc: raise RuntimeError("Azure Event Hubs SDK dependencies are unavailable.") from exc
    return EventHubManagementClient(DefaultAzureCredential(), subscription_id)


def _path(*parts):
    path = repository_paths().runtime / "azure_event_hub"; path.mkdir(parents=True, exist_ok=True)
    return path / ("public-access-" + "-".join(parts).replace("/", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values): raise ValueError("All action inputs are required.")
