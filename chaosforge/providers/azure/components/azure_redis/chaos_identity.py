"""Reusable Azure Chaos Studio identity support for Redis experiments."""

from __future__ import annotations

import json
import subprocess
import uuid

from chaosforge.common.azure_cli import azure_cli_command
from chaosforge.providers.azure.rbac import (
    AZURE_BUILT_IN_ROLE_DEFINITION_IDS,
    accepted_role_definition_ids,
    accepted_role_names,
    assignment_satisfies,
)

CHAOS_IDENTITY_NAME = "chaosforge-managed-identity"
REDIS_CACHE_CONTRIBUTOR_ROLE_DEFINITION_ID = AZURE_BUILT_IN_ROLE_DEFINITION_IDS[
    "Redis Cache Contributor"
]
REDIS_CACHE_CONTRIBUTOR_ROLE_NAME = "Redis Cache Contributor"


class AzureRedisChaosIdentityService:
    """Discover and validate the shared UAMI used by Redis Chaos Studio runs."""

    def __init__(self, subscription_id, credential):
        self.subscription_id = subscription_id
        self.credential = credential
        self.last_bootstrap_outcome = {"identity_created": False, "role_assigned": False}

    def list_identities(self):
        try:
            from azure.mgmt.msi import ManagedServiceIdentityClient

            identities = ManagedServiceIdentityClient(
                self.credential, self.subscription_id
            ).user_assigned_identities.list_by_subscription()
            return [
                {
                    "id": identity.id,
                    "name": identity.name,
                    "resource_group": _resource_group(identity.id),
                    "principal_id": identity.principal_id,
                }
                for identity in identities
                if identity.name == CHAOS_IDENTITY_NAME
            ]
        except Exception as sdk_error:  # noqa: BLE001 - Azure CLI is the interactive fallback.
            try:
                result = subprocess.run(
                    azure_cli_command(
                        "identity", "list", "--subscription", self.subscription_id,
                        "--query", (
                            f"[?name=='{CHAOS_IDENTITY_NAME}']."
                            "{id:id,name:name,principal_id:principalId}"
                        ),
                        "--output", "json",
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
            except (FileNotFoundError, subprocess.SubprocessError) as cli_error:
                raise RuntimeError(
                    "Could not load Azure Chaos identities through the Azure SDK or Azure CLI."
                ) from cli_error
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip() or "Could not load Azure Chaos identities."
                ) from sdk_error
            try:
                identities = json.loads(result.stdout)
            except (TypeError, ValueError) as cli_error:
                raise RuntimeError("Azure CLI returned an invalid managed identity list.") from cli_error
            if not isinstance(identities, list):
                raise RuntimeError("Azure CLI returned an invalid managed identity list.")
            return [
                {
                    "id": str(identity.get("id") or ""),
                    "name": str(identity.get("name") or ""),
                    "resource_group": _resource_group(identity.get("id")),
                    "principal_id": str(identity.get("principal_id") or ""),
                }
                for identity in identities
                if identity.get("id") and identity.get("name") == CHAOS_IDENTITY_NAME
            ]

    def create_identity(self, resource_group):
        try:
            from azure.mgmt.msi import ManagedServiceIdentityClient
            from azure.mgmt.msi.models import Identity
            from azure.mgmt.resource.resources import ResourceManagementClient

            location = ResourceManagementClient(
                self.credential, self.subscription_id
            ).resource_groups.get(resource_group).location
            identity = ManagedServiceIdentityClient(
                self.credential, self.subscription_id
            ).user_assigned_identities.create_or_update(
                resource_group,
                CHAOS_IDENTITY_NAME,
                Identity(location=location, tags={"managed-by": "chaosforge", "purpose": "chaos-studio"}),
            )
            return {
                "id": identity.id,
                "name": identity.name,
                "resource_group": resource_group,
                "principal_id": identity.principal_id,
            }
        except (ImportError, ModuleNotFoundError):
            return self._create_identity_with_cli(resource_group)

    def _create_identity_with_cli(self, resource_group):
        try:
            result = subprocess.run(
                azure_cli_command(
                    "identity", "create",
                    "--name", CHAOS_IDENTITY_NAME,
                    "--resource-group", resource_group,
                    "--subscription", self.subscription_id,
                    "--output", "json",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                "Azure Managed Identity SDK is unavailable and Azure CLI could not create the identity. "
                "Install azure-mgmt-msi with 'python -m pip install -r requirements.txt' or install Azure CLI."
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip()
                or "Azure CLI could not create chaosforge-managed-identity."
            )
        try:
            identity = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Azure CLI returned an invalid managed identity response.") from exc
        identity_id = str(identity.get("id") or "")
        principal_id = str(identity.get("principalId") or "")
        if not identity_id or not principal_id:
            raise RuntimeError("Azure CLI did not return an identity ID and principal ID.")
        return {
            "id": identity_id,
            "name": str(identity.get("name") or CHAOS_IDENTITY_NAME),
            "resource_group": resource_group,
            "principal_id": principal_id,
        }

    def bootstrap(self, resource_group, target_id):
        """Explicitly create the reusable UAMI and target-scoped role if needed."""
        identities = self.list_identities()
        identity_created = False
        role_assigned = False
        if not identities:
            identity = self.create_identity(resource_group)
            identity_created = True
        elif len(identities) == 1:
            identity = identities[0]
        else:
            raise RuntimeError(
                f"Multiple identities named '{CHAOS_IDENTITY_NAME}' exist; select one explicitly."
            )
        if not self._has_redis_cache_contributor(identity["principal_id"], target_id):
            self.grant_redis_cache_contributor(identity["id"], target_id)
            role_assigned = True
        self.last_bootstrap_outcome = {
            "identity_created": identity_created,
            "role_assigned": role_assigned,
        }
        return self.readiness(identity["id"], target_id)

    def readiness(self, identity_id, target_id):
        identity = next((item for item in self.list_identities() if item["id"] == identity_id), None)
        if identity is None:
            return {"status": "missing", "message": "Selected chaos identity was not found."}
        if not identity["principal_id"]:
            return {"status": "blocked", "message": "Selected chaos identity has no principal ID yet."}
        if self._has_redis_cache_contributor(identity["principal_id"], target_id):
            return {
                "status": "ready",
                "identity": identity,
                "target_role": accepted_role_names(REDIS_CACHE_CONTRIBUTOR_ROLE_NAME),
            }
        return {
            "status": "missing_role",
            "identity": identity,
            "target_role": accepted_role_names(REDIS_CACHE_CONTRIBUTOR_ROLE_NAME),
            "message": (
                f"{accepted_role_names(REDIS_CACHE_CONTRIBUTOR_ROLE_NAME)} is required on the selected Redis cache "
                "or an inherited resource-group/subscription scope."
            ),
        }

    def grant_redis_cache_contributor(self, identity_id, target_id):
        from azure.mgmt.authorization import AuthorizationManagementClient
        from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

        identity = next((item for item in self.list_identities() if item["id"] == identity_id), None)
        if identity is None or not identity["principal_id"]:
            raise RuntimeError("The selected chaos identity could not be resolved.")
        client = AuthorizationManagementClient(self.credential, self.subscription_id)
        client.role_assignments.create(
            target_id,
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{identity['principal_id']}:{target_id}:{REDIS_CACHE_CONTRIBUTOR_ROLE_DEFINITION_ID}")),
            RoleAssignmentCreateParameters(
                role_definition_id=(
                    f"/subscriptions/{self.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/"
                    f"{REDIS_CACHE_CONTRIBUTOR_ROLE_DEFINITION_ID}"
                ),
                principal_id=identity["principal_id"],
                principal_type="ServicePrincipal",
            ),
        )

    def _has_redis_cache_contributor(self, principal_id, target_id):
        from azure.mgmt.authorization import AuthorizationManagementClient

        client = AuthorizationManagementClient(self.credential, self.subscription_id)
        role_definition_ids = accepted_role_definition_ids(REDIS_CACHE_CONTRIBUTOR_ROLE_NAME)
        for scope in _scopes(target_id):
            assignments = client.role_assignments.list_for_scope(
                scope, filter=f"principalId eq '{principal_id}'"
            )
            if any(assignment_satisfies(assignment, principal_id, role_definition_ids) for assignment in assignments):
                return True
        return False


def redis_target_id(subscription_id, resource_group, redis_name):
    return (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Cache/redis/{redis_name}"
    )


def redis_cache_contributor_assignment_command(principal_id, target_id):
    """Return a copyable Azure CLI command for the Redis target assignment."""
    return (
        "az role assignment create "
        f"--assignee-object-id {principal_id} "
        "--assignee-principal-type ServicePrincipal "
        f"--role '{REDIS_CACHE_CONTRIBUTOR_ROLE_NAME}' "
        f"--scope {target_id}"
    )


def _resource_group(resource_id):
    parts = str(resource_id or "").strip("/").split("/")
    return next((parts[index + 1] for index, part in enumerate(parts) if part.lower() == "resourcegroups"), "")


def _scopes(target_id):
    parts = target_id.rstrip("/").split("/")
    resource_group_index = next(index for index, part in enumerate(parts) if part.lower() == "resourcegroups")
    return [target_id, "/".join(parts[:resource_group_index + 2]), "/".join(parts[:3])]
