"""Azure Chaos Studio Redis reboot fault executed with the Azure SDK."""

import re
import time

CAPABILITY_URN = "urn:csci:microsoft:azureClusteredCacheForRedis:reboot/1.0"
TARGET_NAME = "Microsoft-AzureClusteredCacheForRedis"


def run_experiment(subscription_id, resource_group, redis_name, chaos_identity_id, reboot_type="AllNodes", shard_id=0):
    _require(subscription_id, "subscription_id")
    _require(resource_group, "resource_group")
    _require(redis_name, "redis_name")
    _require(chaos_identity_id, "chaos_identity_id")
    if reboot_type not in {"AllNodes", "PrimaryNode", "SecondaryNode"}:
        raise ValueError("reboot_type must be AllNodes, PrimaryNode, or SecondaryNode.")

    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.chaos import ChaosManagementClient
        from azure.mgmt.chaos.models import (
            Capability,
            ChaosExperimentBranch,
            ChaosExperimentStep,
            ChaosTargetListSelector,
            DiscreteAction,
            Experiment,
            KeyValuePair,
            ManagedServiceIdentity,
            ManagedServiceIdentityType,
            Target,
            TargetReference,
            TargetReferenceType,
        )
        from azure.mgmt.redis import RedisManagementClient
        from azure.mgmt.resource.resources import ResourceManagementClient
    except ImportError as exc:
        dependency = exc.name or str(exc)
        raise RuntimeError(
            f"Azure Redis reboot dependency is unavailable or incompatible: {dependency}. "
            "Run `python -m pip install --upgrade -r requirements.txt` in the ChaosForge environment."
        ) from exc

    credential = DefaultAzureCredential()
    redis_client = RedisManagementClient(credential, subscription_id)
    cache = redis_client.redis.get(resource_group, redis_name)
    chaos_client = ChaosManagementClient(credential, subscription_id)
    ResourceManagementClient(credential, subscription_id).providers.register("Microsoft.Chaos")
    chaos_client.targets.create_or_update(
        resource_group,
        "Microsoft.Cache",
        "redis",
        redis_name,
        TARGET_NAME,
        Target(properties={}),
    )
    chaos_client.capabilities.create_or_update(
        resource_group,
        "Microsoft.Cache",
        "redis",
        redis_name,
        TARGET_NAME,
        "Reboot-1.0",
        Capability(),
    )

    cache_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Cache/redis/{redis_name}"
    )
    experiment_name = _experiment_name(redis_name)
    parameters = [KeyValuePair(key="RebootType", value=reboot_type)]
    if getattr(cache, "shard_count", None):
        parameters.append(KeyValuePair(key="ShardId", value=str(int(shard_id))))

    experiment = Experiment(
        location=cache.location,
        identity=ManagedServiceIdentity(
            type=ManagedServiceIdentityType.USER_ASSIGNED,
            user_assigned_identities={chaos_identity_id: {}},
        ),
        steps=[
            ChaosExperimentStep(
                name="reboot",
                branches=[
                    ChaosExperimentBranch(
                        name="redis",
                        actions=[
                            DiscreteAction(
                                name=CAPABILITY_URN,
                                selector_id="redis",
                                parameters=parameters,
                            )
                        ],
                    )
                ],
            )
        ],
        selectors=[
            ChaosTargetListSelector(
                id="redis",
                targets=[
                    TargetReference(
                        type=TargetReferenceType.CHAOS_TARGET,
                        id=f"{cache_id}/providers/Microsoft.Chaos/targets/{TARGET_NAME}",
                    )
                ],
            )
        ],
    )
    chaos_client.experiments.begin_create_or_update(resource_group, experiment_name, experiment).result()
    chaos_client.experiments.begin_start(resource_group, experiment_name).result()
    _wait_for_completion(chaos_client, resource_group, experiment_name)
    return {"experiment_name": experiment_name, "target": cache_id, "status": "started"}


def _experiment_name(redis_name):
    safe_name = re.sub(r"[^a-z0-9-]", "-", redis_name.lower()).strip("-")
    return f"chaosforge-redis-reboot-{safe_name[:32]}-{int(time.time())}"


def _require(value, name):
    if not str(value or "").strip():
        raise ValueError(f"{name} is required.")


def _wait_for_completion(client, resource_group, experiment_name, timeout_seconds=300):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        executions = list(client.experiments.list_all_executions(resource_group, experiment_name))
        if not executions:
            time.sleep(5)
            continue
        status = str(
            client.experiments.get_execution(
                resource_group, experiment_name, executions[0].name
            ).status
        ).lower()
        if status in {"succeeded", "success"}:
            return
        if status in {"failed", "cancelled", "stopped"}:
            detail = _execution_failure_detail(
                client, resource_group, experiment_name, executions[0].name
            )
            raise RuntimeError(
                f"Azure Chaos Studio Redis reboot ended with status: {status}."
                + (f" {detail}" if detail else "")
            )
        time.sleep(5)
    raise TimeoutError("Timed out waiting for the Azure Chaos Studio Redis reboot.")


def _execution_failure_detail(client, resource_group, experiment_name, execution_name):
    """Return Azure's action-level failure detail without masking a terminal state."""
    try:
        details = client.experiments.execution_details(
            resource_group, experiment_name, execution_name
        )
    except Exception:  # noqa: BLE001 - status is still the primary failure signal.
        return ""
    properties = getattr(details, "properties", None) or details
    failure_reason = getattr(properties, "failure_reason", None)
    if failure_reason:
        return str(failure_reason)
    for detail in getattr(properties, "details", []) or []:
        properties = getattr(detail, "properties", None) or detail
        error = getattr(properties, "error", None)
        if error:
            return str(error)
        message = getattr(properties, "message", None)
        if message:
            return str(message)
    return str(getattr(details, "error", "") or getattr(details, "message", ""))
