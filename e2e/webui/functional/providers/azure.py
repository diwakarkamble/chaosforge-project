"""Structured Azure resource lookup for manifest-driven functional E2E tests."""

from __future__ import annotations

from typing import Any

CHILD_ALIASES = {
    "azure_vmss_instances": "instances",
    "azure_app_service_slots": "slots",
    "azure_function_slots": "slots",
    "azure_container_app_revisions": "revisions",
    "azure_key_vault_certificates": "certificates",
    "azure_key_vault_secrets": "secrets",
    "azure_event_hub_entities": "event_hubs",
    "azure_postgres_flexible_firewall_rules": "firewall_rules",
    "azure_cosmos_db_regions": "regions",
}


def resolve(target: dict[str, Any]) -> tuple[str, list[dict[str, str]], str]:
    """Resolve a target, preserving the original functional-runner contract."""
    if target.get("target_type") == "tags":
        return resolve_tagged(target)
    status, items, error = _resource_list(target)
    if status != "found":
        return status, items, error
    matches = [_resource(item) for item in items if _matches(item, target)]
    return _one(matches, target, "resource")


def resolve_tagged_roots(target: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    """Find tagged ARM roots without selecting a child resource."""
    status, items, error = _resource_list(target)
    if status != "found":
        return status, items, error
    matches = [item for item in items if _matches(item, target)]
    if not matches:
        return "missing", [], f"No Azure {target['service']} resource matched {target['target']!r}."
    if len(matches) != 1:
        return "ambiguous", [_resource(item) for item in matches], (
            f"Azure {target['service']} root selection matched {len(matches)} resources."
        )
    return "found", matches, ""


def resolve_tagged(target: dict[str, Any]) -> tuple[str, list[dict[str, str]], str]:
    """Resolve one tagged root and, when requested, one child in its resource graph.

    Set ``child`` to one of ``instances``, ``slots``, ``revisions``,
    ``certificates``, ``secrets``, ``event_hubs``, ``firewall_rules``, or
    ``regions``. Omitting it resolves the tagged ARM root itself.
    """
    status, roots, error = resolve_tagged_roots(target)
    if status != "found":
        return status, [_resource(item) for item in roots], error
    root = roots[0]
    child = str(target.get("child") or "").strip()
    if not child:
        return "found", [_resource(root)], ""
    return resolve_child(root, child, target)


def resolve_graph(target: dict[str, Any], resource_fields: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, str]], str]:
    """Resolve ordered Azure metadata resource fields into one safe graph.

    The first field resolves the tagged ARM root. Descendants declare a
    ``parent`` and use their metadata ``resource_type`` (or explicit ``child``)
    to select a supported child. Tagged ARM descendants repeat the root tag
    predicate; untaggable descendants must be the sole candidate.
    """
    if not resource_fields:
        return "found", {}, ""
    selected: dict[str, dict[str, str]] = {}
    roots: dict[str, Any] = {}
    for field in resource_fields:
        name = str(field["name"])
        parent_name = field.get("parent")
        if parent_name:
            if parent_name not in roots:
                return "unsupported", selected, f"Azure graph field {name!r} has unresolved parent {parent_name!r}."
            child = _child_name(field)
            if not child:
                return "unsupported", selected, f"Azure graph field {name!r} has no supported child type."
            status, resources, error = resolve_child(roots[parent_name], child, target)
        else:
            status, candidates, error = resolve_tagged_roots(target)
            resources = [_resource(item) for item in candidates]
            if status == "found":
                roots[name] = candidates[0]
        if status != "found":
            return status, selected, f"{name}: {error}"
        selected[name] = resources[0]
        if parent_name:
            # Every child remains rooted at the ARM resource for subsequent descendants.
            roots[name] = roots[parent_name]
    return "found", selected, ""


def resolve_child(root: dict[str, Any], child: str, target: dict[str, Any]) -> tuple[str, list[dict[str, str]], str]:
    """Resolve a child of ``root`` without ever arbitrarily selecting one."""
    child = child.strip().casefold()
    if child in {"slots", "instances", "revisions", "certificates", "secrets", "firewall_rules"}:
        status, matches, error = _sdk_children(root, child, target)
    elif child == "regions":
        locations = (root.get("properties") or {}).get("locations") or []
        matches = [
            {"id": f"{str(root['id']).rstrip('/')}/locations/{item['locationName']}", "name": str(item["locationName"])}
            for item in locations if item.get("locationName")
        ]
        status, error = "found", ""
    else:
        return "unsupported", [], f"Azure tagged resource graph does not support child {child!r}."
    if status != "found":
        return status, matches, error
    # Instances, revisions, Key Vault objects, firewall rules, and Cosmos
    # regions cannot be safely tag-filtered. One is required, never a default.
    return _one(matches, target, child)


def list_event_hub_entities(root: dict[str, Any], target: dict[str, Any]) -> tuple[str, list[dict[str, str]], str]:
    """List namespace entities for wildcard state changes without choosing one."""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.eventhub import EventHubManagementClient

        subscription_id = target.get("subscription_id") or _subscription(root)
        client = EventHubManagementClient(DefaultAzureCredential(), subscription_id)
        entities = client.event_hubs.list_by_namespace(_group(root), root["name"])
        return "found", [
            {
                "id": entity.id or f"{root['id'].rstrip('/')}/eventhubs/{entity.name}",
                "name": entity.name,
            }
            for entity in entities
            if entity.name
        ], ""
    except Exception as exc:  # noqa: BLE001 - surfaces developer Azure SDK setup failures.
        return "environment_error", [], f"Azure Event Hubs SDK lookup failed: {exc}"


def _sdk_children(root: dict[str, Any], child: str, target: dict[str, Any]):
    """Resolve Azure provider/data-plane children through their SDK clients."""
    try:
        from azure.identity import DefaultAzureCredential

        subscription_id = target.get("subscription_id") or _subscription(root)
        credential = DefaultAzureCredential()
        group = _group(root)
        if child == "instances":
            from azure.mgmt.compute import ComputeManagementClient

            items = ComputeManagementClient(credential, subscription_id).virtual_machine_scale_set_vms.list(group, root["name"])
            matches = [{"id": str(item.instance_id), "name": f"Instance {item.instance_id}"} for item in items if item.instance_id is not None]
        elif child == "slots":
            from azure.mgmt.web import WebSiteManagementClient

            items = WebSiteManagementClient(credential, subscription_id).web_apps.list_slots(group, root["name"])
            matches = [
                {"id": item.id, "name": item.name.rsplit("/", 1)[-1]}
                for item in items
                if item.id and item.name and _has_tags({"tags": item.tags or {}}, target["target"])
            ]
        elif child == "revisions":
            from azure.mgmt.appcontainers import ContainerAppsAPIClient

            items = ContainerAppsAPIClient(credential, subscription_id).container_apps_revisions.list_revisions(group, root["name"])
            matches = [{"id": item.name, "name": item.name} for item in items if item.name]
        elif child in {"certificates", "secrets"}:
            vault_url = f"https://{root['name']}.vault.azure.net"
            if child == "certificates":
                from azure.keyvault.certificates import CertificateClient

                items = CertificateClient(vault_url, credential).list_properties_of_certificates()
            else:
                from azure.keyvault.secrets import SecretClient

                items = SecretClient(vault_url, credential).list_properties_of_secrets()
            matches = [{"id": item.name, "name": item.name} for item in items if item.name]
        elif child == "firewall_rules":
            from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient

            items = PostgreSQLManagementClient(credential, subscription_id).firewall_rules.list_by_server(group, root["name"])
            matches = [{"id": item.name, "name": item.name} for item in items if item.name]
        else:
            return "unsupported", [], f"Azure SDK child resolver does not support {child!r}."
        return "found", matches, ""
    except Exception as exc:  # noqa: BLE001 - cloud SDK setup failures are functional test errors.
        return "environment_error", [], f"Azure SDK child lookup failed for {child}: {exc}"


def resolve_chaos_identity(value: str, subscription_id: str = "") -> tuple[str, str, str]:
    """Resolve a user-assigned identity name to its ARM ID for the Web UI."""
    value = str(value or "").strip()
    if value.startswith("/"):
        return "found", value, ""
    if not subscription_id:
        return "missing", "", "Azure identity name requires a subscription ID."
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.msi import ManagedServiceIdentityClient

        identities = ManagedServiceIdentityClient(
            DefaultAzureCredential(), subscription_id
        ).user_assigned_identities.list_by_subscription()
        matches = [identity.id for identity in identities if identity.name == value and identity.id]
    except Exception as exc:  # noqa: BLE001 - surfaces SDK identity lookup failures.
        return "environment_error", "", f"Azure identity SDK lookup failed: {exc}"
    if len(matches) != 1:
        result = "missing" if not matches else "ambiguous"
        return result, "", f"Azure Chaos identity name {value!r} matched {len(matches)} identities."
    return "found", str(matches[0]), ""


def _resource_list(target: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    subscription_id = target.get("subscription_id")
    if not subscription_id:
        return "environment_error", [], "Azure tag mode requires --e2e-azure-subscription or AZURE_SUBSCRIPTION_ID."
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.resource.resources import ResourceManagementClient

        resources = ResourceManagementClient(
            DefaultAzureCredential(), subscription_id
        ).resources.list(filter=f"resourceType eq '{target['resource_type']}'")
        items = [
            {
                "id": item.id,
                "name": item.name,
                "type": getattr(item, "type", ""),
                "tags": getattr(item, "tags", None) or {},
                "resourceGroup": _group({"id": item.id}),
                "properties": getattr(item, "properties", None) or {},
            }
            for item in resources
            if item.id and item.name
        ]
        if target.get("resource_group"):
            items = [
                item
                for item in items
                if item["resourceGroup"].casefold() == target["resource_group"].casefold()
            ]
        return "found", items, ""
    except Exception as exc:  # noqa: BLE001 - Azure SDK discovery failure is actionable.
        return "environment_error", [], f"Azure SDK resource lookup failed: {exc}"




def _matches(item: dict[str, Any], target: dict[str, Any]) -> bool:
    if str(item.get("type", "")).casefold() != target["resource_type"].casefold():
        return False
    if target["target_type"] == "name":
        return str(item.get("name", "")).casefold() == str(target["target"]).casefold()
    if target["target_type"] == "resource_id":
        return str(item.get("id", "")).rstrip("/").casefold() == str(target["target"]).rstrip("/").casefold()
    return _has_tags(item, target["target"])


def _has_tags(item: dict[str, Any], wanted: dict[str, Any]) -> bool:
    tags = {str(key).strip().casefold(): str(value).strip().casefold() for key, value in (item.get("tags") or {}).items()}
    return all(tags.get(str(key).strip().casefold()) == str(value).strip().casefold() for key, value in wanted.items())


def _one(items: list[dict[str, str]], target: dict[str, Any], kind: str):
    if not items:
        return "missing", [], f"No Azure {target['service']} {kind} matched {target['target']!r}."
    if len(items) != 1:
        return "ambiguous", items, f"Azure {target['service']} {kind} selection matched {len(items)} resources."
    return "found", items, ""


def _group(resource: dict[str, Any]) -> str:
    parts = str(resource["id"]).strip("/").split("/")
    return parts[parts.index("resourceGroups") + 1]


def _subscription(resource: dict[str, Any]) -> str:
    parts = str(resource["id"]).strip("/").split("/")
    return parts[parts.index("subscriptions") + 1]


def _child_name(field: dict[str, Any]) -> str:
    value = str(field.get("child") or field.get("resource_type") or "").strip().casefold()
    return CHILD_ALIASES.get(
        value,
        value if value in {"slots", "instances", "revisions", "certificates", "secrets", "firewall_rules", "regions"} else "",
    )


def _resource(item: dict[str, Any]) -> dict[str, str]:
    return {"id": str(item["id"]), "name": str(item["name"])}
