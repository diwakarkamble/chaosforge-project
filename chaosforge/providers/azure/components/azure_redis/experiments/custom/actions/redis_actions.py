"""Azure Resource Manager operations for Redis experiments not in Chaos Studio."""

import json

from chaosforge.common.paths import repository_paths


def flush_cache(subscription_id, resource_group, resource_id):
    _require(resource_group, "resource_group")
    redis_name = _resource_name(resource_id)
    client = _redis_client(subscription_id)
    return client.redis.begin_flush_cache(resource_group, redis_name).result()


def disable_public_access(subscription_id, resource_group, resource_id):
    _require(resource_group, "resource_group")
    redis_name = _resource_name(resource_id)
    client = _redis_client(subscription_id)
    cache = client.redis.get(resource_group, redis_name)
    previous = getattr(cache, "public_network_access", None) or "Enabled"
    _state_path(subscription_id, resource_group, redis_name).write_text(
        json.dumps({"public_network_access": previous}), encoding="utf-8"
    )
    return client.redis.begin_update(
        resource_group, redis_name, {"properties": {"publicNetworkAccess": "Disabled"}}
    ).result()


def restore_public_access(subscription_id, resource_group, resource_id):
    _require(resource_group, "resource_group")
    redis_name = _resource_name(resource_id)
    path = _state_path(subscription_id, resource_group, redis_name)
    if not path.is_file():
        return "No access-disruption state was recorded."
    previous = json.loads(path.read_text(encoding="utf-8"))["public_network_access"]
    result = _redis_client(subscription_id).redis.begin_update(
        resource_group, redis_name, {"properties": {"publicNetworkAccess": previous}}
    ).result()
    path.unlink(missing_ok=True)
    return result


def _redis_client(subscription_id):
    _require(subscription_id, "subscription_id")
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.redis import RedisManagementClient
    except ImportError as exc:
        raise RuntimeError(
            "Azure Redis SDK dependencies are unavailable. Reinstall ChaosForge dependencies."
        ) from exc

    return RedisManagementClient(DefaultAzureCredential(), subscription_id)


def _state_path(subscription_id, resource_group, redis_name):
    path = repository_paths().runtime / "azure_redis"
    path.mkdir(parents=True, exist_ok=True)
    safe_name = "-".join((subscription_id, resource_group, redis_name)).replace("/", "-")
    return path / f"access-disruption-{safe_name}.json"


def _require(value, name):
    if not str(value or "").strip():
        raise ValueError(f"{name} is required.")


def _resource_name(resource_id):
    _require(resource_id, "resource_id")
    return str(resource_id).rstrip("/").rsplit("/", 1)[-1]
