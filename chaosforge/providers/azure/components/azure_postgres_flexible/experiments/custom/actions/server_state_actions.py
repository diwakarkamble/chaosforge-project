"""Reversible PostgreSQL Flexible Server stop actions for an exact target."""

import json
from pathlib import Path

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def stop_server(subscription_id, resource_group, resource_id):
    server_name = resource_name(resource_id)
    client = _client(subscription_id)
    server = client.servers.get(resource_group, server_name)
    was_running = str(getattr(server, "state", "")).lower() in {"ready", "running"}
    _path(subscription_id, resource_group, server_name).parent.mkdir(parents=True, exist_ok=True)
    _path(subscription_id, resource_group, server_name).write_text(
        json.dumps({"resource_id": resource_id, "was_running": was_running}), encoding="utf-8"
    )
    if was_running:
        return client.servers.begin_stop(resource_group, server_name).result()


def restore_server(subscription_id, resource_group, resource_id):
    server_name = resource_name(resource_id)
    path = _path(subscription_id, resource_group, server_name)
    if not path.is_file():
        return "No PostgreSQL server state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["resource_id"] != resource_id:
        raise ValueError("Recorded PostgreSQL rollback state belongs to another target.")
    result = (
        _client(subscription_id).servers.begin_start(resource_group, server_name).result()
        if state["was_running"]
        else None
    )
    path.unlink()
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient
    except ImportError as exc:
        raise RuntimeError("Azure PostgreSQL SDK dependencies are unavailable.") from exc
    return PostgreSQLManagementClient(DefaultAzureCredential(), subscription_id)


def _path(subscription_id, resource_group, server_name):
    return Path(repository_paths().rollback) / "azure_postgres_flexible" / (
        f"stop-{subscription_id}-{resource_group}-{server_name}.json"
    )
