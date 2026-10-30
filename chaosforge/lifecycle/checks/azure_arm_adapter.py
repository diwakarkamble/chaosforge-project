"""Generic Azure Resource Manager lifecycle snapshots."""

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class AzureARMResourceAdapter(ResourceAdapter):
    """Capture availability information common to Azure ARM resources."""

    name = "azure-arm-resource-adapter"

    def capture(self, target):
        resource_id = target["resource_id"]
        subscription_id = target.get("subscription_id") or self._subscription_id(resource_id)

        try:
            from azure.core.exceptions import ResourceNotFoundError
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.resource.resources import ResourceManagementClient
        except ImportError as exc:
            raise RuntimeError(
                "Azure ARM SDK dependencies are unavailable. Reinstall ChaosForge dependencies."
            ) from exc

        try:
            client = ResourceManagementClient(DefaultAzureCredential(), subscription_id)
            api_version = self._api_version(client, resource_id)
            resource = client.resources.get_by_id(
                resource_id, api_version=api_version
            )
        except ResourceNotFoundError:
            return {"exists": False, "identity": {"id": resource_id}}

        properties = getattr(resource, "properties", None) or {}
        provisioning_state = (
            properties.get("provisioningState")
            if isinstance(properties, dict)
            else getattr(properties, "provisioning_state", None)
        )
        public_network_access = (
            properties.get("publicNetworkAccess")
            if isinstance(properties, dict)
            else getattr(properties, "public_network_access", None)
        )
        return {
            "exists": True,
            "identity": {
                "name": getattr(resource, "name", resource_id.rsplit("/", 1)[-1]),
                "id": getattr(resource, "id", resource_id),
                "type": getattr(resource, "type", None),
            },
            "state": {"provisioning_state": provisioning_state},
            "configuration": {"public_network_access": public_network_access},
        }

    @staticmethod
    def _subscription_id(resource_id):
        parts = resource_id.strip("/").split("/")
        try:
            return parts[parts.index("subscriptions") + 1]
        except (ValueError, IndexError) as exc:
            raise ValueError(
                "Azure lifecycle checks require subscription_id or an ARM resource_id."
            ) from exc

    @staticmethod
    def _api_version(client, resource_id):
        parts = resource_id.strip("/").split("/")
        try:
            provider_index = next(
                index
                for index, part in enumerate(parts)
                if part.lower() == "providers"
            )
            namespace = parts[provider_index + 1]
            resource_parts = parts[provider_index + 2 :]
            resource_type = "/".join(resource_parts[::2])
        except (StopIteration, IndexError) as exc:
            raise ValueError(
                "Azure lifecycle checks require a provider-qualified ARM resource_id."
            ) from exc

        provider = client.providers.get(namespace)
        provider_types = getattr(provider, "resource_types", None) or []
        metadata = next(
            (
                item
                for item in provider_types
                if str(getattr(item, "resource_type", "")).lower()
                == resource_type.lower()
            ),
            None,
        )
        versions = list(getattr(metadata, "api_versions", None) or [])
        if not versions:
            raise RuntimeError(
                f"Azure provider {namespace} did not publish API versions for "
                f"resource type {resource_type}."
            )
        stable_versions = [
            version for version in versions if "preview" not in version.lower()
        ]
        return max(stable_versions or versions)
