"""Build and run Azure Chaos Studio service-direct classic experiments."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Mapping

from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
    CHAOS_IDENTITY_NAME,
)
from chaosforge.providers.azure.rbac import (
    AZURE_BUILT_IN_ROLE_DEFINITION_IDS,
    accepted_role_definition_ids,
    accepted_role_names,
    assignment_satisfies,
)

ROLE_DEFINITIONS = AZURE_BUILT_IN_ROLE_DEFINITION_IDS

def run_service_direct_classic_experiment(
    subscription_id,
    resource_group,
    target_resource_id,
    capability_urn,
    selector_target,
    chaos_identity_id,
    action_parameters=None,
    duration=None,
    selector_id="target",
    experiment_name=None,
    completion_check=None,
):
    """Run a service-direct classic fault; this intentionally excludes agent faults."""
    for value, name in (
        (subscription_id, "subscription_id"),
        (resource_group, "resource_group"),
        (target_resource_id, "target_resource_id"),
        (capability_urn, "capability_urn"),
        (selector_target, "selector_target"),
        (chaos_identity_id, "chaos_identity_id"),
        (selector_id, "selector_id"),
    ):
        _require(value, name)
    if action_parameters is not None and not isinstance(action_parameters, Mapping):
        raise ValueError("action_parameters must be a mapping of parameter names to values.")

    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.chaos import ChaosManagementClient
        from azure.mgmt.chaos.models import (
            Capability,
            ChaosExperimentBranch,
            ChaosExperimentStep,
            ChaosTargetListSelector,
            ContinuousAction,
            DiscreteAction,
            Experiment,
            KeyValuePair,
            ManagedServiceIdentity,
            ManagedServiceIdentityType,
            Target,
            TargetReference,
            TargetReferenceType,
        )
        from azure.mgmt.resource.resources import ResourceManagementClient
    except ImportError as exc:
        dependency = exc.name or str(exc)
        raise RuntimeError(
            f"Azure Chaos Studio dependency is unavailable or incompatible: {dependency}. "
            "Run `python -m pip install --upgrade -r requirements.txt` in the ChaosForge environment."
        ) from exc

    namespace, resource_type, resource_name = _target_parts(target_resource_id)
    credential = DefaultAzureCredential()
    chaos_client = ChaosManagementClient(credential, subscription_id)
    resource_client = ResourceManagementClient(credential, subscription_id)
    resource_client.providers.register("Microsoft.Chaos")

    chaos_client.targets.create_or_update(
        resource_group,
        namespace,
        resource_type,
        resource_name,
        selector_target,
        Target(properties={}),
    )
    capability_name = _capability_name(capability_urn)
    chaos_client.capabilities.create_or_update(
        resource_group,
        namespace,
        resource_type,
        resource_name,
        selector_target,
        capability_name,
        Capability(),
    )

    action_type = ContinuousAction if duration is not None else DiscreteAction
    action = action_type(
        name=capability_urn,
        selector_id=selector_id,
        parameters=[
            KeyValuePair(key=str(key), value=str(value))
            for key, value in (action_parameters or {}).items()
        ],
        **({"duration": duration} if duration is not None else {}),
    )
    name = experiment_name or _experiment_name(target_resource_id, capability_name)
    experiment = Experiment(
        location=resource_client.resource_groups.get(resource_group).location,
        identity=ManagedServiceIdentity(
            type=ManagedServiceIdentityType.USER_ASSIGNED,
            user_assigned_identities={chaos_identity_id: {}},
        ),
        steps=[
            ChaosExperimentStep(
                name="fault",
                branches=[ChaosExperimentBranch(name="service-direct", actions=[action])],
            )
        ],
        selectors=[
            ChaosTargetListSelector(
                id=selector_id,
                targets=[
                    TargetReference(
                        type=TargetReferenceType.CHAOS_TARGET,
                        id=f"{target_resource_id.rstrip('/')}/providers/Microsoft.Chaos/targets/{selector_target}",
                    )
                ],
            )
        ],
    )
    chaos_client.experiments.begin_create_or_update(resource_group, name, experiment).result()
    chaos_client.experiments.begin_start(resource_group, name).result()
    _wait_for_completion(chaos_client, resource_group, name, completion_check)
    return {"experiment_name": name, "target": target_resource_id, "status": "started"}

class AzureChaosIdentityService:
    """Bootstrap the shared ChaosForge UAMI with a supported target-scoped role."""

    def __init__(self, subscription_id, credential):
        self.subscription_id = subscription_id
        self.credential = credential
        self.last_bootstrap_outcome = {"identity_created": False, "role_assigned": False}

    def bootstrap(self, resource_group, target_id, role_name):
        _role_id(role_name)
        identities = self.list_identities()
        created = False
        assigned = False
        if not identities:
            identity = self.create_identity(resource_group)
            created = True
        elif len(identities) == 1:
            identity = identities[0]
        else:
            raise RuntimeError(f"Multiple identities named '{CHAOS_IDENTITY_NAME}' exist; select one explicitly.")
        if not self.has_role(identity["principal_id"], target_id, role_name):
            self.grant_role(identity["id"], target_id, role_name)
            assigned = True
        self.last_bootstrap_outcome = {"identity_created": created, "role_assigned": assigned}
        return self.readiness(identity["id"], target_id, role_name)

    def readiness(self, identity_id, target_id, role_name):
        _role_id(role_name)
        identity = next((item for item in self.list_identities() if item["id"] == identity_id), None)
        if identity is None:
            return {"status": "missing", "message": "Selected chaos identity was not found."}
        if not identity["principal_id"]:
            return {"status": "blocked", "message": "Selected chaos identity has no principal ID yet."}
        if self.has_role(identity["principal_id"], target_id, role_name):
            return {
                "status": "ready",
                "identity": identity,
                "target_role": accepted_role_names(role_name),
            }
        return {
            "status": "missing_role",
            "identity": identity,
            "target_role": accepted_role_names(role_name),
            "message": (
                f"{accepted_role_names(role_name)} is required on the selected target "
                "or an inherited resource-group/subscription scope."
            ),
        }

    def list_identities(self):
        from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
            AzureRedisChaosIdentityService,
        )

        return AzureRedisChaosIdentityService(self.subscription_id, self.credential).list_identities()

    def get_identity(self, identity_id):
        """Resolve an explicitly selected UAMI without changing default discovery."""
        parts = str(identity_id or "").strip("/").split("/")
        try:
            resource_group = parts[next(index for index, part in enumerate(parts) if part.casefold() == "resourcegroups") + 1]
            name = parts[-1]
        except (StopIteration, IndexError):
            raise ValueError("identity_id must be a valid user-assigned identity resource ID.") from None
        from azure.mgmt.msi import ManagedServiceIdentityClient

        identity = ManagedServiceIdentityClient(
            self.credential, self.subscription_id
        ).user_assigned_identities.get(resource_group, name)
        return {
            "id": identity.id,
            "name": identity.name,
            "resource_group": resource_group,
            "principal_id": identity.principal_id,
        }

    def create_identity(self, resource_group):
        from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
            AzureRedisChaosIdentityService,
        )

        return AzureRedisChaosIdentityService(self.subscription_id, self.credential).create_identity(resource_group)

    def grant_role(self, identity_id, target_id, role_name):
        from azure.mgmt.authorization import AuthorizationManagementClient
        from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

        identity = next((item for item in self.list_identities() if item["id"] == identity_id), None)
        if identity is None or not identity["principal_id"]:
            raise RuntimeError("The selected chaos identity could not be resolved.")
        role_id = _role_id(role_name)
        AuthorizationManagementClient(self.credential, self.subscription_id).role_assignments.create(
            target_id,
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"{identity['principal_id']}:{target_id}:{role_id}")),
            RoleAssignmentCreateParameters(
                role_definition_id=(
                    f"/subscriptions/{self.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/{role_id}"
                ),
                principal_id=identity["principal_id"],
                principal_type="ServicePrincipal",
            ),
        )

    def has_role(self, principal_id, target_id, role_name):
        from azure.mgmt.authorization import AuthorizationManagementClient

        role_ids = accepted_role_definition_ids(role_name)
        client = AuthorizationManagementClient(self.credential, self.subscription_id)
        for scope in _scopes(target_id):
            assignments = client.role_assignments.list_for_scope(
                scope, filter=f"principalId eq '{principal_id}'"
            )
            if any(assignment_satisfies(item, principal_id, role_ids) for item in assignments):
                return True
        return False

def role_assignment_command(principal_id, target_id, role_name):
    """Return a copyable Azure CLI command for a supported target role."""
    _role_id(role_name)
    return (
        "az role assignment create "
        f"--assignee-object-id {principal_id} --assignee-principal-type ServicePrincipal "
        f"--role '{role_name}' --scope {target_id}"
    )

def _target_parts(target_resource_id):
    parts = str(target_resource_id or "").strip("/").split("/")
    try:
        provider_index = next(index for index, part in enumerate(parts) if part.lower() == "providers")
        namespace = parts[provider_index + 1]
        values = parts[provider_index + 2 :]
    except (StopIteration, IndexError):
        raise ValueError("target_resource_id must be a valid Azure resource ID.") from None
    if len(values) < 2 or len(values) % 2:
        raise ValueError("target_resource_id must identify an Azure resource.")
    return namespace, "/".join(values[::2]), "/".join(values[1::2])

def _capability_name(capability_urn):
    match = re.search(r":([^:]+)/(\d+(?:\.\d+)*)$", capability_urn)
    if not match:
        raise ValueError("capability_urn must end with a capability name and version, such as reboot/1.0.")
    return f"{match.group(1).title()}-{match.group(2)}"

def _experiment_name(target_resource_id, capability_name):
    resource_name = _target_parts(target_resource_id)[2].replace("/", "-")
    safe = re.sub(r"[^a-z0-9-]", "-", f"{resource_name}-{capability_name}".lower()).strip("-")
    return f"chaosforge-classic-{safe[:36]}-{int(time.time())}"

def _role_id(role_name):
    try:
        return ROLE_DEFINITIONS[role_name]
    except KeyError:
        raise ValueError(f"Unsupported Chaos Studio target role: {role_name}.") from None

def _scopes(target_id):
    parts = target_id.rstrip("/").split("/")
    try:
        resource_group_index = next(index for index, part in enumerate(parts) if part.lower() == "resourcegroups")
    except StopIteration:
        raise ValueError("target_id must include an Azure resource group.") from None
    return [target_id, "/".join(parts[: resource_group_index + 2]), "/".join(parts[:3])]

def _require(value, name):
    if not str(value or "").strip():
        raise ValueError(f"{name} is required.")

def _wait_for_completion(
    client, resource_group, experiment_name, completion_check=None, timeout_seconds=480
):
    deadline = time.monotonic() + timeout_seconds
    last_status = "no execution reported"
    while time.monotonic() < deadline:
        if completion_check and completion_check():
            return
        executions = list(client.experiments.list_all_executions(resource_group, experiment_name))
        if executions:
            execution_name = executions[0].name
            status = str(client.experiments.get_execution(resource_group, experiment_name, execution_name).status).lower()
            last_status = status
            if status in {"succeeded", "success"}:
                return
            if status in {"failed", "cancelled", "stopped"}:
                detail = _execution_failure_detail(
                    client, resource_group, experiment_name, execution_name
                )
                raise RuntimeError(
                    f"Azure Chaos Studio experiment ended with status: {status}."
                    + (f" {detail}" if detail else "")
                )
        time.sleep(5)
    raise TimeoutError(
        "Timed out waiting for the Azure Chaos Studio experiment after "
        f"{timeout_seconds} seconds; last Azure status: {last_status}."
    )

def _execution_failure_detail(client, resource_group, experiment_name, execution_name):
    """Return Azure's action-level failure detail for a terminal execution."""
    try:
        details = client.experiments.execution_details(
            resource_group, experiment_name, execution_name
        )
    except Exception:  # noqa: BLE001 - the terminal status remains actionable.
        return ""
    properties = getattr(details, "properties", None) or details
    if failure_reason := getattr(properties, "failure_reason", None):
        return str(failure_reason)
    for detail in getattr(properties, "details", []) or []:
        item = getattr(detail, "properties", None) or detail
        if error := getattr(item, "error", None):
            return str(error)
        if message := getattr(item, "message", None):
            return str(message)
    run_information = getattr(properties, "run_information", None)
    for step in getattr(run_information, "steps", None) or []:
        for branch in getattr(step, "branches", None) or []:
            for action in getattr(branch, "actions", None) or []:
                for target in getattr(action, "targets", None) or []:
                    error = getattr(target, "error", None)
                    if not error:
                        continue
                    code = getattr(error, "code", None)
                    message = getattr(error, "message", None)
                    if code and message:
                        return f"{code}: {message}"
                    if message:
                        return str(message)
                    if code:
                        return str(code)
    return str(getattr(details, "error", "") or getattr(details, "message", ""))
