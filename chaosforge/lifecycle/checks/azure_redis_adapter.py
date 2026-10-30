"""Lifecycle snapshots for Azure Cache for Redis resources."""

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class AzureRedisAdapter(ResourceAdapter):
    name = "azure-redis-adapter"

    def capture(self, target):
        subscription_id = target["subscription_id"]
        resource_group = target["resource_group"]
        redis_name = str(target.get("redis_name") or "").strip()
        if not redis_name:
            resource_id = str(target.get("resource_id") or "").rstrip("/")
            if not resource_id:
                raise ValueError("redis_name or resource_id is required for Azure Redis lifecycle checks.")
            redis_name = resource_id.rsplit("/", 1)[-1]
        try:
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.redis import RedisManagementClient
        except ImportError as exc:
            raise RuntimeError(
                "Azure Redis SDK dependencies are unavailable. Reinstall ChaosForge dependencies."
            ) from exc

        cache = RedisManagementClient(DefaultAzureCredential(), subscription_id).redis.get(
            resource_group, redis_name
        )
        return {
            "exists": True,
            "identity": {
                "name": getattr(cache, "name", redis_name),
                "id": getattr(cache, "id", None),
            },
            "state": {
                "provisioning_state": getattr(cache, "provisioning_state", None),
            },
            "configuration": {
                "public_network_access": getattr(cache, "public_network_access", None),
                "sku": getattr(getattr(cache, "sku", None), "name", None),
            },
        }
