"""Azure Cosmos DB public-network disruption actions."""

import json

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def disable_public_access(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); account_name = resource_name(resource_id)
    client = _client(subscription_id)
    account = client.database_accounts.get(resource_group, account_name)
    _path(subscription_id, resource_group, account_name).write_text(json.dumps({"public_network_access": account.public_network_access}), encoding="utf-8")
    return client.database_accounts.begin_update(
        resource_group, account_name, {"properties": {"publicNetworkAccess": "Disabled"}}
    ).result()


def restore_public_access(subscription_id, resource_group, resource_id):
    _require(subscription_id, resource_group, resource_id); account_name = resource_name(resource_id)
    path = _path(subscription_id, resource_group, account_name)
    if not path.is_file(): return "No public-access state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    result = _client(subscription_id).database_accounts.begin_update(
        resource_group,
        account_name,
        {"properties": {"publicNetworkAccess": state["public_network_access"]}},
    ).result()
    path.unlink(missing_ok=True)
    return result


def _client(subscription_id):
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.cosmosdb import CosmosDBManagementClient
    except ImportError as exc: raise RuntimeError("Azure Cosmos DB SDK dependencies are unavailable.") from exc
    return CosmosDBManagementClient(DefaultAzureCredential(), subscription_id)


def _path(*parts):
    path = repository_paths().runtime / "azure_cosmos_db"; path.mkdir(parents=True, exist_ok=True)
    return path / ("public-access-" + "-".join(parts).replace("/", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values): raise ValueError("All action inputs are required.")
