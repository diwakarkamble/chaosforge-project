"""Azure SDK actions for Container Apps custom experiments."""

import json

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def restart_revision(subscription_id, resource_group, resource_id, revision_name):
    _require(subscription_id, resource_group, resource_id, revision_name)
    app_name = resource_name(resource_id)
    return _client(subscription_id).container_apps_revisions.restart_revision(
        resource_group, app_name, revision_name
    )


def shift_traffic(subscription_id, resource_group, resource_id, revision_name, weight=100):
    _require(subscription_id, resource_group, resource_id, revision_name)

    app_name = resource_name(resource_id)
    client = _client(subscription_id)

    app = client.container_apps.get(resource_group, app_name)
    configuration = app.configuration
    ingress = configuration.ingress

    _state_path(
        subscription_id,
        resource_group,
        app_name,
        "traffic",
    ).write_text(
        json.dumps({
            "traffic": [
                {
                    "revisionName": item.revision_name,
                    "weight": item.weight,
                    "label": getattr(item, "label", None),
                    "latestRevision": getattr(item, "latest_revision", None),
                }
                for item in (ingress.traffic or [])
            ]
        }),
        encoding="utf-8",
    )

    from azure.mgmt.appcontainers.models import TrafficWeight

    ingress.traffic = [
        TrafficWeight(
            revision_name=revision_name,
            weight=int(weight),
            latest_revision=False,
        )
    ]

    return client.container_apps.begin_create_or_update(
        resource_group,
        app_name,
        app,
    ).result()


def restore_traffic(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id)
    app_name = resource_name(resource_id)
    path = _state_path(subscription_id, resource_group, app_name, "traffic")
    if not path.is_file():
        return "No traffic state was recorded."
    app = _client(subscription_id).container_apps.get(resource_group, app_name)
    app.configuration.ingress.traffic = json.loads(path.read_text(encoding="utf-8"))["traffic"]
    result = _client(subscription_id).container_apps.begin_create_or_update(resource_group, app_name, app).result()
    path.unlink(missing_ok=True)
    return result


def scale_revision_to_zero(subscription_id, resource_group, resource_id, revision_name):
    _require(subscription_id, resource_group, resource_id, revision_name)
    app_name = resource_name(resource_id)
    client = _client(subscription_id)
    revision = client.container_apps_revisions.get_revision(resource_group, app_name, revision_name)
    _state_path(subscription_id, resource_group, app_name, revision_name).write_text(json.dumps({
        "active": revision.active,
    }), encoding="utf-8")
    return client.container_apps_revisions.deactivate_revision(resource_group, app_name, revision_name)


def restore_revision_scale(subscription_id, resource_group, resource_id, revision_name):
    _require(subscription_id, resource_group, resource_id, revision_name)
    app_name = resource_name(resource_id)
    path = _state_path(subscription_id, resource_group, app_name, revision_name)
    if not path.is_file():
        return "No revision-scale state was recorded."
    client = _client(subscription_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    result = (
        client.container_apps_revisions.activate_revision(resource_group, app_name, revision_name)
        if state["active"]
        else None
    )
    path.unlink(missing_ok=True)
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.appcontainers import ContainerAppsAPIClient
    except ImportError as exc:
        raise RuntimeError("Azure Container Apps SDK dependencies are unavailable.") from exc
    return ContainerAppsAPIClient(DefaultAzureCredential(), subscription_id)


def _state_path(*parts):
    path = repository_paths().runtime / "azure_container_apps"
    path.mkdir(parents=True, exist_ok=True)
    return path / ("-".join(parts).replace("/", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values):
        raise ValueError("All action inputs are required.")
