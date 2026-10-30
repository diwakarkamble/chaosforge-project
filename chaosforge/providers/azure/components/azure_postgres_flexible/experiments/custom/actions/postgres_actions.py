"""Azure SDK actions for PostgreSQL Flexible Server custom experiments."""

import json

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def restart_server(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id)
    server_name = resource_name(resource_id)
    return _client(subscription_id).servers.begin_restart(resource_group, server_name).result()


def remove_firewall_rule(subscription_id, resource_group, resource_id, rule_name):
    _require(subscription_id, resource_group, resource_id, rule_name)
    server_name = resource_name(resource_id)
    client = _client(subscription_id)
    rule = client.firewall_rules.get(resource_group, server_name, rule_name)
    _state_path(subscription_id, resource_group, server_name, rule_name).write_text(json.dumps({
        "start_ip_address": rule.start_ip_address, "end_ip_address": rule.end_ip_address,
    }), encoding="utf-8")
    return client.firewall_rules.begin_delete(resource_group, server_name, rule_name).result()


def restore_firewall_rule(subscription_id, resource_group, resource_id, rule_name):
    _require(subscription_id, resource_group, resource_id, rule_name)
    server_name = resource_name(resource_id)
    path = _state_path(subscription_id, resource_group, server_name, rule_name)
    if not path.is_file():
        return "No firewall-rule state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    result = _client(subscription_id).firewall_rules.begin_create_or_update(
        resource_group,
        server_name,
        rule_name,
        {
            "properties": {
                "startIpAddress": state["start_ip_address"],
                "endIpAddress": state["end_ip_address"],
            }
        },
    ).result()
    path.unlink(missing_ok=True)
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient
    except ImportError as exc:
        raise RuntimeError("Azure PostgreSQL SDK dependencies are unavailable.") from exc
    return PostgreSQLManagementClient(DefaultAzureCredential(), subscription_id)


def _state_path(*parts):
    path = repository_paths().runtime / "azure_postgres_flexible"
    path.mkdir(parents=True, exist_ok=True)
    return path / ("firewall-" + "-".join(parts).replace("/", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values):
        raise ValueError("subscription_id, resource_group, server_name, and rule_name are required.")
