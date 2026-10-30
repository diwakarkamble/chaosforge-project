"""Reversible App Service stop actions for an exact selected target."""

import json
from pathlib import Path

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def stop_app_service(subscription_id, resource_group, resource_id):
    app_name = resource_name(resource_id)
    client = _client(subscription_id)
    app = client.web_apps.get(resource_group, app_name)
    was_running = str(getattr(app, "state", "")).lower() == "running"
    _path(subscription_id, resource_group, app_name).parent.mkdir(parents=True, exist_ok=True)
    _path(subscription_id, resource_group, app_name).write_text(
        json.dumps({"resource_id": resource_id, "was_running": was_running}), encoding="utf-8"
    )
    if was_running:
        return client.web_apps.stop(resource_group, app_name)


def restore_app_service(subscription_id, resource_group, resource_id):
    app_name = resource_name(resource_id)
    path = _path(subscription_id, resource_group, app_name)
    if not path.is_file():
        return "No App Service state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    if state["resource_id"] != resource_id:
        raise ValueError("Recorded App Service rollback state belongs to another target.")
    result = _client(subscription_id).web_apps.start(resource_group, app_name) if state["was_running"] else None
    path.unlink()
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.web import WebSiteManagementClient
    except ImportError as exc:
        raise RuntimeError("Azure App Service SDK dependencies are unavailable.") from exc
    return WebSiteManagementClient(DefaultAzureCredential(), subscription_id)


def _path(subscription_id, resource_group, app_name):
    return Path(repository_paths().rollback) / "azure_app_service" / (
        f"stop-{subscription_id}-{resource_group}-{app_name}.json"
    )
