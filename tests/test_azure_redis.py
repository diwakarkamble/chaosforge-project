import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.application.campaigns.builder import build_experiment
from chaosforge.application.discovery import discover_services, display_name
from chaosforge.catalog import ExperimentCatalog
from chaosforge.interfaces.cli.interactive import azure_redis_menu
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
    AzureRedisChaosIdentityService,
    redis_cache_contributor_assignment_command,
    redis_target_id,
)
from chaosforge.providers.azure.components.azure_redis.experiments.chaos_studio.actions import (
    redis_reboot,
)
from chaosforge.providers.azure.components.azure_redis.experiments.custom.actions import (
    redis_actions,
)


def test_azure_redis_catalog_separates_studio_and_custom_sdk_experiments():
    catalog = ExperimentCatalog()
    metadata = catalog.load_service("azure_redis")
    experiments = {item["id"]: item for item in metadata["experiments"]}

    assert experiments["azure-redis-reboot"]["engine"] == "Azure Chaos Studio"
    assert experiments["azure-redis-reboot"]["source"] == "Azure Chaos Studio"
    assert experiments["azure-redis-flush"]["engine"] == "Azure SDK"
    assert experiments["azure-redis-access-disruption"]["engine"] == "Azure SDK"
    for item in experiments.values():
        assert catalog.definition_path("azure_redis", item["json"]).is_file()
    assert "azure_redis" in discover_services("azure")
    assert "azure_redis" not in discover_services("aws")
    assert display_name("azure_redis") == "Azure Cache for Redis"


@pytest.mark.parametrize(
    ("experiment_id", "engine"),
    [
        ("azure-redis-reboot", "Azure Chaos Studio"),
        ("azure-redis-flush", "Azure SDK"),
        ("azure-redis-access-disruption", "Azure SDK"),
    ],
)
def test_azure_redis_builder_preserves_catalog_engine(monkeypatch, experiment_id, engine):
    added = MagicMock()
    monkeypatch.setattr("chaosforge.application.campaigns.builder.add", added)
    metadata = ExperimentCatalog().get_experiment("azure_redis", experiment_id)

    experiment = build_experiment(
        "azure_redis",
        metadata,
        {"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache"},
    )

    assert experiment.engine == engine
    assert experiment.variables["experiment_id"] == experiment_id
    assert "aws_region" not in experiment.variables


def test_flush_uses_redis_management_sdk(monkeypatch):
    client = SimpleNamespace(redis=MagicMock())
    client.redis.begin_flush_cache.return_value.result.return_value = "flushed"
    monkeypatch.setattr(redis_actions, "_redis_client", MagicMock(return_value=client))

    assert redis_actions.flush_cache("sub", "rg", "/redis/cache") == "flushed"
    client.redis.begin_flush_cache.assert_called_once_with("rg", "cache")


def test_access_disruption_restores_the_original_public_access_setting(monkeypatch, tmp_path):
    client = SimpleNamespace(
        redis=MagicMock(
            get=MagicMock(return_value=SimpleNamespace(public_network_access="Enabled"))
        )
    )
    client.redis.begin_update.return_value.result.return_value = "updated"
    monkeypatch.setattr(redis_actions, "_redis_client", MagicMock(return_value=client))
    monkeypatch.setattr(redis_actions, "_state_path", lambda *_: tmp_path / "state.json")

    assert redis_actions.disable_public_access("sub", "rg", "/redis/cache") == "updated"
    client.redis.begin_update.assert_called_once_with(
        "rg", "cache", {"properties": {"publicNetworkAccess": "Disabled"}}
    )

    assert redis_actions.restore_public_access("sub", "rg", "/redis/cache") == "updated"
    assert client.redis.begin_update.call_args_list[-1].args == (
        "rg", "cache", {"properties": {"publicNetworkAccess": "Enabled"}}
    )


def test_access_disruption_handles_missing_state_and_builds_runtime_state_path(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(redis_actions, "_state_path", lambda *_: missing)
    assert redis_actions.restore_public_access("sub", "rg", "/redis/cache") == (
        "No access-disruption state was recorded."
    )

    monkeypatch.undo()
    monkeypatch.setattr(
        redis_actions,
        "repository_paths",
        lambda: SimpleNamespace(runtime=tmp_path / "runtime"),
    )
    path = redis_actions._state_path("sub/id", "rg", "cache")
    assert path.parent.is_dir()
    assert path.name == "access-disruption-sub-id-rg-cache.json"


@pytest.mark.parametrize("value", ("", None, "  "))
def test_custom_redis_actions_require_all_resource_identifiers(value):
    with pytest.raises(ValueError):
        redis_actions.flush_cache("sub", value, "/redis/cache")
    with pytest.raises(ValueError):
        redis_actions.disable_public_access("sub", "rg", value)
    with pytest.raises(ValueError):
        redis_actions._redis_client(value)


def test_custom_redis_client_reports_missing_sdk(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def missing_redis_sdk(name, *args, **kwargs):
        if name == "azure.mgmt.redis":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_redis_sdk)
    with pytest.raises(RuntimeError, match="SDK dependencies"):
        redis_actions._redis_client("sub")


@pytest.mark.parametrize("value", ("", None))
def test_reboot_rejects_invalid_required_values_before_sdk_calls(value):
    with pytest.raises(ValueError):
        redis_reboot.run_experiment(value, "rg", "cache", "identity")
    with pytest.raises(ValueError):
        redis_reboot.run_experiment("sub", "rg", "cache", "identity", reboot_type="invalid")


def test_reboot_identifies_the_unavailable_azure_sdk_dependency(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def missing_chaos_sdk(name, *args, **kwargs):
        if name == "azure.mgmt.chaos":
            error = ImportError("missing Azure Chaos SDK")
            error.name = "azure.mgmt.chaos"
            raise error
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_chaos_sdk)
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=MagicMock()),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization.models",
        SimpleNamespace(RoleAssignmentCreateParameters=lambda **kwargs: kwargs),
    )

    with pytest.raises(RuntimeError, match="azure.mgmt.chaos") as error:
        redis_reboot.run_experiment("sub", "rg", "cache", "identity")

    assert "python -m pip install --upgrade -r requirements.txt" in str(error.value)


def test_reboot_registers_chaos_target_capability_and_starts_experiment(monkeypatch):
    chaos_client = SimpleNamespace(
        targets=MagicMock(), capabilities=MagicMock(), experiments=MagicMock()
    )
    chaos_client.experiments.begin_start.return_value.result.return_value = None
    chaos_client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    chaos_client.experiments.get_execution.return_value = SimpleNamespace(status="Succeeded")
    resource_client = SimpleNamespace(providers=MagicMock())
    redis_client = SimpleNamespace(
        redis=SimpleNamespace(get=MagicMock(return_value=SimpleNamespace(location="eastus")) )
    )

    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=MagicMock()))
    monkeypatch.setitem(sys.modules, "azure.mgmt.chaos", SimpleNamespace(ChaosManagementClient=lambda *_: chaos_client))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.chaos.models",
        SimpleNamespace(
            Capability=lambda **kwargs: kwargs,
            ChaosExperimentBranch=lambda **kwargs: kwargs,
            ChaosExperimentStep=lambda **kwargs: kwargs,
            ChaosTargetListSelector=lambda **kwargs: kwargs,
            DiscreteAction=lambda **kwargs: kwargs,
            Experiment=lambda **kwargs: kwargs,
            KeyValuePair=lambda **kwargs: kwargs,
            ManagedServiceIdentity=lambda **kwargs: kwargs,
            ManagedServiceIdentityType=SimpleNamespace(USER_ASSIGNED="UserAssigned"),
            Target=lambda **kwargs: kwargs,
            TargetReference=lambda **kwargs: kwargs,
            TargetReferenceType=SimpleNamespace(CHAOS_TARGET="ChaosTarget"),
        ),
    )
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.redis", SimpleNamespace(RedisManagementClient=lambda *_: redis_client)
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.resource.resources",
        SimpleNamespace(ResourceManagementClient=lambda *_: resource_client),
    )
    monkeypatch.setattr(redis_reboot.time, "time", lambda: 1)

    identity_id = "/subscriptions/sub/resourceGroups/identities/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaosforge-managed-identity"
    result = redis_reboot.run_experiment("sub", "rg", "cache", identity_id, "PrimaryNode", 2)

    resource_client.providers.register.assert_called_once_with("Microsoft.Chaos")
    chaos_client.targets.create_or_update.assert_called_once()
    assert chaos_client.targets.create_or_update.call_args.args[5] == {"properties": {}}
    chaos_client.capabilities.create_or_update.assert_called_once()
    chaos_client.experiments.begin_create_or_update.assert_called_once()
    experiment = chaos_client.experiments.begin_create_or_update.call_args.args[2]
    assert experiment["identity"] == {
        "type": "UserAssigned",
        "user_assigned_identities": {identity_id: {}},
    }
    action = experiment["steps"][0]["branches"][0]["actions"][0]
    assert action["parameters"] == [{"key": "RebootType", "value": "PrimaryNode"}]
    chaos_client.experiments.begin_start.assert_called_once_with(
        "rg", "chaosforge-redis-reboot-cache-1"
    )
    assert result["status"] == "started"


def test_reboot_sends_shard_id_only_for_clustered_redis(monkeypatch):
    chaos_client = SimpleNamespace(
        targets=MagicMock(), capabilities=MagicMock(), experiments=MagicMock()
    )
    chaos_client.experiments.begin_start.return_value.result.return_value = None
    chaos_client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    chaos_client.experiments.get_execution.return_value = SimpleNamespace(status="Succeeded")
    redis_client = SimpleNamespace(
        redis=SimpleNamespace(
            get=MagicMock(return_value=SimpleNamespace(location="eastus", shard_count=3))
        )
    )
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=MagicMock()))
    monkeypatch.setitem(sys.modules, "azure.mgmt.chaos", SimpleNamespace(ChaosManagementClient=lambda *_: chaos_client))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.chaos.models",
        SimpleNamespace(
            Capability=lambda **kwargs: kwargs,
            ChaosExperimentBranch=lambda **kwargs: kwargs,
            ChaosExperimentStep=lambda **kwargs: kwargs,
            ChaosTargetListSelector=lambda **kwargs: kwargs,
            DiscreteAction=lambda **kwargs: kwargs,
            Experiment=lambda **kwargs: kwargs,
            KeyValuePair=lambda **kwargs: kwargs,
            ManagedServiceIdentity=lambda **kwargs: kwargs,
            ManagedServiceIdentityType=SimpleNamespace(USER_ASSIGNED="UserAssigned"),
            Target=lambda **kwargs: kwargs,
            TargetReference=lambda **kwargs: kwargs,
            TargetReferenceType=SimpleNamespace(CHAOS_TARGET="ChaosTarget"),
        ),
    )
    monkeypatch.setitem(sys.modules, "azure.mgmt.redis", SimpleNamespace(RedisManagementClient=lambda *_: redis_client))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.resource.resources",
        SimpleNamespace(ResourceManagementClient=lambda *_: SimpleNamespace(providers=MagicMock())),
    )
    monkeypatch.setattr(redis_reboot.time, "time", lambda: 1)

    redis_reboot.run_experiment("sub", "rg", "cache", "identity", shard_id=2)

    experiment = chaos_client.experiments.begin_create_or_update.call_args.args[2]
    action = experiment["steps"][0]["branches"][0]["actions"][0]
    assert action["parameters"] == [
        {"key": "RebootType", "value": "AllNodes"},
        {"key": "ShardId", "value": "2"},
    ]


def test_redis_chaos_identity_discovers_by_name_and_accepts_inherited_contributor(monkeypatch):
    identity = SimpleNamespace(
        id="/subscriptions/sub/resourceGroups/identities/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaosforge-managed-identity",
        name="chaosforge-managed-identity",
        principal_id="principal",
    )
    msi = SimpleNamespace(
        user_assigned_identities=SimpleNamespace(list_by_subscription=lambda: [identity])
    )
    contributor = SimpleNamespace(
        role_definition_id=(
            "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/"
                "e0f68234-74aa-48ed-b826-c38b57376e17"
        )
    )
    authorization = SimpleNamespace(
        role_assignments=SimpleNamespace(list_for_scope=lambda *_args, **_kwargs: [contributor])
    )
    monkeypatch.setitem(sys.modules, "azure.mgmt.msi", SimpleNamespace(ManagedServiceIdentityClient=lambda *_: msi))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=lambda *_: authorization),
    )
    target_id = redis_target_id("sub", "rg", "cache")

    service = AzureRedisChaosIdentityService("sub", object())
    identities = service.list_identities()
    assert identities[0]["resource_group"] == "identities"
    assert service.readiness(identities[0]["id"], target_id)["status"] == "ready"
    assert redis_cache_contributor_assignment_command("principal", target_id).endswith(f"--scope {target_id}")


def test_redis_chaos_identity_uses_azure_supported_principal_filter(monkeypatch):
    calls = []
    assignment = SimpleNamespace(
        principal_id="principal",
        role_definition_id=(
            "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/"
            "e0f68234-74aa-48ed-b826-c38b57376e17"
        ),
    )
    authorization = SimpleNamespace(
        role_assignments=SimpleNamespace(
            list_for_scope=lambda scope, **kwargs: calls.append((scope, kwargs)) or [assignment]
        )
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=lambda *_: authorization),
    )
    target_id = redis_target_id("sub", "rg", "cache")

    assert AzureRedisChaosIdentityService("sub", object())._has_redis_cache_contributor(
        "principal", target_id
    )
    assert calls == [(target_id, {"filter": "principalId eq 'principal'"})]


@pytest.mark.parametrize(
    "role_definition_id",
    [
        "e0f68234-74aa-48ed-b826-c38b57376e17",
        "b24988ac-6180-42a0-ab88-20f7382dd24c",
        "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
    ],
)
def test_redis_chaos_identity_accepts_redis_contributor_or_broader_roles(
    monkeypatch, role_definition_id
):
    assignment = SimpleNamespace(
        principal_id="principal",
        role_definition_id=f"/roleDefinitions/{role_definition_id}",
    )
    authorization = SimpleNamespace(
        role_assignments=SimpleNamespace(list_for_scope=lambda *_args, **_kwargs: [assignment])
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=lambda *_: authorization),
    )

    assert AzureRedisChaosIdentityService("sub", object())._has_redis_cache_contributor(
        "principal", redis_target_id("sub", "rg", "cache")
    )


def test_redis_chaos_identity_bootstrap_creates_once_and_grants_target_role(monkeypatch):
    service = AzureRedisChaosIdentityService("sub", object())
    identity = {
        "id": "/identities/chaosforge-managed-identity",
        "name": "chaosforge-managed-identity",
        "principal_id": "principal",
    }
    grant = MagicMock()
    monkeypatch.setattr(service, "list_identities", lambda: [])
    monkeypatch.setattr(service, "create_identity", lambda resource_group: identity)
    monkeypatch.setattr(service, "_has_redis_cache_contributor", lambda *_args: False)
    monkeypatch.setattr(service, "grant_redis_cache_contributor", grant)
    monkeypatch.setattr(
        service,
        "readiness",
        lambda identity_id, target_id: {"status": "ready", "identity": identity},
    )

    assert service.bootstrap("identity-rg", "/redis") == {
        "status": "ready", "identity": identity
    }
    grant.assert_called_once_with(identity["id"], "/redis")


def test_redis_chaos_identity_create_grant_and_readiness_outcomes(monkeypatch):
    created = SimpleNamespace(
        id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaosforge-managed-identity",
        name="chaosforge-managed-identity",
        principal_id="principal",
    )
    msi = SimpleNamespace(
        user_assigned_identities=SimpleNamespace(
            list_by_subscription=lambda: [created],
            create_or_update=MagicMock(return_value=created),
        )
    )
    resource = SimpleNamespace(resource_groups=SimpleNamespace(get=lambda _: SimpleNamespace(location="eastus")))
    assignments = SimpleNamespace(create=MagicMock(), list_for_scope=lambda *_args, **_kwargs: [])
    monkeypatch.setitem(sys.modules, "azure.mgmt.msi", SimpleNamespace(ManagedServiceIdentityClient=lambda *_: msi))
    monkeypatch.setitem(sys.modules, "azure.mgmt.msi.models", SimpleNamespace(Identity=lambda **kwargs: kwargs))
    monkeypatch.setitem(sys.modules, "azure.mgmt.resource.resources", SimpleNamespace(ResourceManagementClient=lambda *_: resource))
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.authorization", SimpleNamespace(AuthorizationManagementClient=lambda *_: SimpleNamespace(role_assignments=assignments))
    )
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.authorization.models", SimpleNamespace(RoleAssignmentCreateParameters=lambda **kwargs: kwargs)
    )
    service = AzureRedisChaosIdentityService("sub", object())
    target_id = redis_target_id("sub", "rg", "cache")

    assert service.create_identity("rg")["resource_group"] == "rg"
    assert msi.user_assigned_identities.create_or_update.call_args.args[:2] == ("rg", "chaosforge-managed-identity")
    assert service.readiness("missing", target_id)["status"] == "missing"
    created.principal_id = None
    assert service.readiness(created.id, target_id)["status"] == "blocked"
    created.principal_id = "principal"
    assert service.readiness(created.id, target_id)["status"] == "missing_role"
    service.grant_redis_cache_contributor(created.id, target_id)
    assignments.create.assert_called_once()
    assert assignments.create.call_args.args[2]["principal_type"] == "ServicePrincipal"
    with pytest.raises(RuntimeError, match="could not be resolved"):
        service.grant_redis_cache_contributor("missing", target_id)


def test_redis_chaos_identity_creates_with_azure_cli_when_msi_sdk_is_unavailable(monkeypatch):
    service = AzureRedisChaosIdentityService("sub", object())
    monkeypatch.setitem(sys.modules, "azure.mgmt.msi", None)
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({
                "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaosforge-managed-identity",
                "name": "chaosforge-managed-identity",
                "principalId": "principal",
            }),
        ),
    )

    identity = service.create_identity("rg")

    assert identity["principal_id"] == "principal"


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (SimpleNamespace(returncode=1, stderr="forbidden", stdout=""), "forbidden"),
        (SimpleNamespace(returncode=0, stderr="", stdout="not-json"), "invalid managed identity response"),
        (SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({"id": "identity"})), "identity ID and principal ID"),
    ],
)
def test_redis_chaos_identity_cli_creation_reports_errors(monkeypatch, result, message):
    service = AzureRedisChaosIdentityService("sub", object())
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.subprocess.run",
        lambda *_args, **_kwargs: result,
    )

    with pytest.raises(RuntimeError, match=message):
        service._create_identity_with_cli("rg")


def test_redis_chaos_identity_cli_creation_explains_missing_cli(monkeypatch):
    service = AzureRedisChaosIdentityService("sub", object())
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    with pytest.raises(RuntimeError, match="azure-mgmt-msi"):
        service._create_identity_with_cli("rg")


def test_redis_chaos_identity_falls_back_to_azure_cli_discovery(monkeypatch):
    service = AzureRedisChaosIdentityService("sub", object())
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.msi",
        SimpleNamespace(ManagedServiceIdentityClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk denied"))),
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                [
                    {
                        "id": "/subscriptions/sub/resourceGroups/identities/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaosforge-managed-identity",
                        "name": "chaosforge-managed-identity",
                        "principal_id": "principal",
                    }
                ]
            ),
        ),
    )

    assert service.list_identities() == [
        {
            "id": "/subscriptions/sub/resourceGroups/identities/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaosforge-managed-identity",
            "name": "chaosforge-managed-identity",
            "resource_group": "identities",
            "principal_id": "principal",
        }
    ]


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (SimpleNamespace(returncode=1, stderr="forbidden", stdout=""), "forbidden"),
        (SimpleNamespace(returncode=0, stderr="", stdout="not-json"), "invalid managed identity list"),
        (SimpleNamespace(returncode=0, stderr="", stdout="{}"), "invalid managed identity list"),
    ],
)
def test_redis_chaos_identity_cli_fallback_reports_discovery_errors(monkeypatch, result, message):
    service = AzureRedisChaosIdentityService("sub", object())
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.msi",
        SimpleNamespace(ManagedServiceIdentityClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk denied"))),
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.subprocess.run",
        lambda *_args, **_kwargs: result,
    )

    with pytest.raises(RuntimeError, match=message):
        service.list_identities()


def test_redis_chaos_identity_cli_fallback_reports_missing_cli(monkeypatch):
    service = AzureRedisChaosIdentityService("sub", object())
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.msi",
        SimpleNamespace(ManagedServiceIdentityClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk denied"))),
    )
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    with pytest.raises(RuntimeError, match="Azure SDK or Azure CLI"):
        service.list_identities()


def test_redis_chaos_identity_rejects_duplicate_bootstrap_and_parses_scopes(monkeypatch):
    service = AzureRedisChaosIdentityService("sub", object())
    monkeypatch.setattr(service, "list_identities", lambda: [{"id": "one"}, {"id": "two"}])

    with pytest.raises(RuntimeError, match="Multiple identities"):
        service.bootstrap("rg", "/redis")

    assert redis_target_id("sub", "rg", "cache").endswith("/Microsoft.Cache/redis/cache")
    assert redis_cache_contributor_assignment_command("principal", "/redis").startswith("az role assignment create")


def test_redis_chaos_identity_bootstrap_reuses_identity_and_reports_ready(monkeypatch):
    service = AzureRedisChaosIdentityService("sub", object())
    identity = {"id": "identity", "principal_id": "principal"}
    monkeypatch.setattr(service, "list_identities", lambda: [identity])
    monkeypatch.setattr(service, "_has_redis_cache_contributor", lambda *_: True)
    readiness = MagicMock(return_value={"status": "ready"})
    monkeypatch.setattr(service, "readiness", readiness)

    assert service.bootstrap("rg", redis_target_id("sub", "rg", "cache")) == {"status": "ready"}
    readiness.assert_called_once_with("identity", redis_target_id("sub", "rg", "cache"))


def test_redis_chaos_identity_selection_bootstraps_and_reports_unready_states(monkeypatch):
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    service = MagicMock()
    service.list_identities.return_value = []
    service.bootstrap.return_value = {"status": "ready", "identity": {"id": "new"}}
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=MagicMock()))
    monkeypatch.setattr(azure_redis_menu, "AzureRedisChaosIdentityService", MagicMock(return_value=service))
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="s"))
    assert azure_redis_menu._select_chaos_identity("cache") == "new"

    identity = {"id": "identity", "name": "chaosforge-managed-identity", "resource_group": "rg", "principal_id": "principal"}
    service.list_identities.return_value = [identity, {**identity, "id": "other"}]
    service.readiness.return_value = {"status": "missing_role", "identity": identity, "message": "grant role"}
    report = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "info", report)
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="2"))
    assert azure_redis_menu._select_chaos_identity("cache") == "other"
    assert "grant role" in report.call_args.args[0]

    invalid = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "error", invalid)
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="bad"))
    assert azure_redis_menu._select_chaos_identity("cache") is None
    assert "Invalid Azure Chaos Identity" in invalid.call_args.args[0]

    service.list_identities.return_value = [identity]
    service.readiness.return_value = {"status": "ready"}
    assert azure_redis_menu._select_chaos_identity("cache") == "identity"


def test_redis_chaos_identity_selection_handles_discovery_and_bootstrap_failures(monkeypatch):
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=MagicMock()))
    service = MagicMock()
    service.list_identities.side_effect = RuntimeError("denied")
    monkeypatch.setattr(azure_redis_menu, "AzureRedisChaosIdentityService", MagicMock(return_value=service))
    report = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "error", report)
    assert azure_redis_menu._select_chaos_identity("cache") is None

    service.list_identities.side_effect = None
    service.list_identities.return_value = []
    service.bootstrap.side_effect = RuntimeError("no role")
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="s"))
    assert azure_redis_menu._select_chaos_identity("cache") is None
    assert "Could not set up" in report.call_args.args[0]

    service.bootstrap.side_effect = None
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="c"))
    assert azure_redis_menu._select_chaos_identity("cache") is None

    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="s"))
    service.bootstrap.return_value = {"status": "missing_role", "message": "grant role"}
    assert azure_redis_menu._select_chaos_identity("cache") is None
    assert report.call_args.args[0] == "grant role"


def test_collect_redis_inputs_collects_chaos_identity(monkeypatch):
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    monkeypatch.setattr(azure_redis_menu, "_select_redis_cache", lambda: "cache")
    monkeypatch.setattr(azure_redis_menu, "_select_chaos_identity", lambda name: "identity")

    assert azure_redis_menu.collect_redis_inputs({"inputs": [
        {"name": "redis_name", "type": "azure_redis_cache"},
        {"name": "chaos_identity_id", "type": "azure_redis_chaos_identity"},
    ]})["chaos_identity_id"] == "identity"

    monkeypatch.setattr(azure_redis_menu, "_select_chaos_identity", lambda name: None)
    assert azure_redis_menu.collect_redis_inputs({"inputs": [
        {"name": "chaos_identity_id", "type": "azure_redis_chaos_identity"},
    ]}) is None


def test_collect_redis_inputs_displays_defaults_on_the_generic_cli_layout(monkeypatch):
    printed = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "console", MagicMock(print=printed))
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value=""))

    variables = azure_redis_menu.collect_redis_inputs(
        {"inputs": [{"name": "duration", "label": "Duration", "default": "PT5M"}]}
    )

    assert variables["duration"] == "PT5M"
    printed.assert_any_call("[bold cyan]Duration[/bold cyan]")
    printed.assert_any_call("[bright_black]Default : PT5M[/bright_black]")


def test_collect_redis_sdk_inputs_selects_shared_component_resource(monkeypatch):
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    discovery = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "AzureResourceDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(
        azure_redis_menu,
        "list_component_resources",
        lambda *_: [{"id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache", "name": "cache"}],
    )
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(azure_redis_menu, "menu", MagicMock())
    monkeypatch.setattr(azure_redis_menu, "section", MagicMock())

    variables = azure_redis_menu.collect_redis_inputs({"inputs": [
        {"name": "resource_id", "type": "azure_component_resource"},
    ]})

    assert variables["resource_id"].endswith("/redis/cache")


def test_collect_redis_sdk_inputs_reports_discovery_and_selection_errors(monkeypatch):
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    report_error = MagicMock()
    report_info = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "error", report_error)
    monkeypatch.setattr(azure_redis_menu, "info", report_info)
    monkeypatch.setattr(azure_redis_menu, "AzureResourceDiscovery", MagicMock())
    metadata = {"inputs": [{"name": "resource_id", "type": "azure_component_resource"}]}

    monkeypatch.setattr(azure_redis_menu, "list_component_resources", MagicMock(side_effect=RuntimeError("denied")))
    assert azure_redis_menu.collect_redis_inputs(metadata) is None
    assert "Could not discover Azure Cache for Redis instances" in report_error.call_args.args[0]

    monkeypatch.setattr(azure_redis_menu, "list_component_resources", lambda *_: [])
    assert azure_redis_menu.collect_redis_inputs(metadata) is None
    report_info.assert_called_once_with("No Azure Cache for Redis instances were found in this resource group.")

    monkeypatch.setattr(azure_redis_menu, "list_component_resources", lambda *_: [{"id": "cache", "name": "cache"}])
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(return_value="invalid"))
    monkeypatch.setattr(azure_redis_menu, "menu", MagicMock())
    monkeypatch.setattr(azure_redis_menu, "section", MagicMock())
    assert azure_redis_menu.collect_redis_inputs(metadata) is None
    report_error.assert_called_with("Invalid Redis Cache selection.")



@pytest.mark.parametrize("status", ("Failed", "Cancelled", "Stopped"))
def test_reboot_wait_reports_terminal_failure(monkeypatch, status):
    client = SimpleNamespace(
        experiments=SimpleNamespace(
            list_all_executions=lambda *_: [SimpleNamespace(name="run")],
            get_execution=lambda *_: SimpleNamespace(status=status),
        )
    )
    monkeypatch.setattr(redis_reboot.time, "monotonic", lambda: 1)

    with pytest.raises(RuntimeError, match=status.lower()):
        redis_reboot._wait_for_completion(client, "rg", "experiment")


def test_reboot_wait_reports_azure_execution_failure_detail(monkeypatch):
    client = SimpleNamespace(
        experiments=SimpleNamespace(
            list_all_executions=lambda *_: [SimpleNamespace(name="run")],
            get_execution=lambda *_: SimpleNamespace(status="Failed"),
            execution_details=lambda *_: SimpleNamespace(
                details=[SimpleNamespace(properties=SimpleNamespace(message="Redis target rejected reboot"))]
            ),
        )
    )
    monkeypatch.setattr(redis_reboot.time, "monotonic", lambda: 1)

    with pytest.raises(RuntimeError, match="Redis target rejected reboot"):
        redis_reboot._wait_for_completion(client, "rg", "experiment")


def test_reboot_wait_reports_azure_execution_failure_reason(monkeypatch):
    client = SimpleNamespace(
        experiments=SimpleNamespace(
            list_all_executions=lambda *_: [SimpleNamespace(name="run")],
            get_execution=lambda *_: SimpleNamespace(status="Failed"),
            execution_details=lambda *_: SimpleNamespace(
                properties=SimpleNamespace(failure_reason="Azure rejected the selected Redis SKU")
            ),
        )
    )
    monkeypatch.setattr(redis_reboot.time, "monotonic", lambda: 1)

    with pytest.raises(RuntimeError, match="Azure rejected the selected Redis SKU"):
        redis_reboot._wait_for_completion(client, "rg", "experiment")


def test_reboot_failure_detail_prefers_action_error_and_falls_back_to_execution_detail():
    error_detail = SimpleNamespace(
        details=[SimpleNamespace(properties=SimpleNamespace(error="Action failed"))]
    )
    execution_detail = SimpleNamespace(details=[], error="Execution failed")

    assert redis_reboot._execution_failure_detail(
        SimpleNamespace(experiments=SimpleNamespace(execution_details=lambda *_: error_detail)),
        "rg",
        "experiment",
        "run",
    ) == "Action failed"
    assert redis_reboot._execution_failure_detail(
        SimpleNamespace(experiments=SimpleNamespace(execution_details=lambda *_: execution_detail)),
        "rg",
        "experiment",
        "run",
    ) == "Execution failed"


def test_reboot_wait_times_out(monkeypatch):
    client = SimpleNamespace(
        experiments=SimpleNamespace(
            list_all_executions=lambda *_: [SimpleNamespace(name="run")],
            get_execution=lambda *_: SimpleNamespace(status="Running"),
        )
    )
    clock = iter((0, 1))
    monkeypatch.setattr(redis_reboot.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(redis_reboot.time, "sleep", MagicMock())

    with pytest.raises(TimeoutError):
        redis_reboot._wait_for_completion(client, "rg", "experiment", timeout_seconds=1)


def test_reboot_wait_handles_execution_availability_and_succeeds(monkeypatch):
    executions = iter(([], [SimpleNamespace(name="run")]))
    client = SimpleNamespace(
        experiments=SimpleNamespace(
            list_all_executions=lambda *_: next(executions),
            get_execution=lambda *_: SimpleNamespace(status="Succeeded"),
        )
    )
    clock = iter((0, 1, 2))
    sleep = MagicMock()
    monkeypatch.setattr(redis_reboot.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(redis_reboot.time, "sleep", sleep)

    assert redis_reboot._wait_for_completion(client, "rg", "experiment", timeout_seconds=5) is None
    sleep.assert_called_once_with(5)


def test_reboot_wait_accepts_azure_success_status(monkeypatch):
    client = SimpleNamespace(
        experiments=SimpleNamespace(
            list_all_executions=lambda *_: [SimpleNamespace(name="run")],
            get_execution=lambda *_: SimpleNamespace(status="Success"),
        )
    )
    monkeypatch.setattr(redis_reboot.time, "monotonic", lambda: 1)

    assert redis_reboot._wait_for_completion(client, "rg", "experiment") is None


def test_redis_definition_modules_use_sdk_actions():
    catalog = ExperimentCatalog()
    for experiment_id in ("azure-redis-reboot", "azure-redis-flush", "azure-redis-access-disruption"):
        metadata = catalog.get_experiment("azure_redis", experiment_id)
        definition = json.loads(
            catalog.definition_path("azure_redis", metadata["json"]).read_text()
        )
        module = definition["method"][0]["provider"]["module"]
        assert "azure_redis.experiments" in module
        assert "toolkit" not in module


def test_redis_menu_uses_discovered_subscription_resource_group_and_cache(monkeypatch):
    context.azure_subscription = None
    context.azure_resource_group = None
    metadata = {
        "id": "azure-redis-flush",
        "name": "Flush Cache",
        "json": "custom/definitions/azure-redis-flush.json",
        "engine": "Azure SDK",
        "inputs": [
            {"name": "resource_id", "label": "Redis Cache", "type": "azure_component_resource", "required": True}
        ],
    }
    discovery = MagicMock()
    discovery.list_resource_groups.return_value = [{"id": "rg", "name": "Production"}]
    discovery.list_redis_caches.return_value = [{"id": "cache", "name": "orders"}]
    monkeypatch.setattr(azure_redis_menu, "get_cloud_identity", lambda *_args, **_kwargs: {
        "authenticated": True,
        "subscription_id": "sub",
        "name": "Platform",
    })
    monkeypatch.setattr(azure_redis_menu, "AzureResourceDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(azure_redis_menu, "get_experiments", lambda service: [metadata])
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(side_effect=["1", "1", "1"]))
    build = MagicMock(return_value=SimpleNamespace(name="Flush Cache"))
    monkeypatch.setattr(azure_redis_menu, "build_experiment", build)

    azure_redis_menu.redis_experiment_menu()

    assert build.call_args.args == (
        "azure_redis",
        metadata,
        {"subscription_id": "sub", "resource_group": "rg", "resource_id": "cache"},
    )
    discovery.list_resource_groups.assert_called_once_with()
    discovery.list_redis_caches.assert_called_once_with("rg")


def test_redis_menu_uses_shared_operation_tables(monkeypatch):
    context.azure_subscription = None
    context.azure_resource_group = None
    metadata = {
        "id": "azure-redis-flush",
        "name": "Flush Cache",
        "engine": "Azure SDK",
        "inputs": [
            {"name": "resource_id", "label": "Redis Cache", "type": "azure_component_resource", "required": True}
        ],
    }
    discovery = MagicMock()
    discovery.list_resource_groups.return_value = [{"id": "rg", "name": "Production"}]
    discovery.list_redis_caches.return_value = [{"id": "cache", "name": "orders"}]
    tables = MagicMock()
    sections = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "get_cloud_identity", lambda *_args, **_kwargs: {
        "authenticated": True, "subscription_id": "sub", "name": "Platform"
    })
    monkeypatch.setattr(azure_redis_menu, "AzureResourceDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(azure_redis_menu, "get_experiments", lambda _service: [metadata])
    monkeypatch.setattr(azure_redis_menu, "prompt", MagicMock(side_effect=["1", "1", "1"]))
    monkeypatch.setattr(azure_redis_menu, "menu", tables)
    monkeypatch.setattr(azure_redis_menu, "section", sections)
    monkeypatch.setattr(azure_redis_menu, "build_experiment", MagicMock(return_value=SimpleNamespace(name="Flush Cache")))

    azure_redis_menu.redis_experiment_menu()

    assert tables.call_args_list[0].args == ("Resource Groups", [(1, "Production")])
    assert tables.call_args_list[1].args == (
        "",
        [
            (1, "Flush Cache [bold green][Custom][/bold green] [bold red][IRREVERSIBLE][/bold red]"),
            (0, "Back"),
            ("M", "Main Menu"),
        ],
    )
    assert tables.call_args_list[2].args == ("Redis Caches", [(1, "orders")])
    sections.assert_any_call("Experiment Description")


def test_redis_menu_requires_logged_in_azure_identity(monkeypatch):
    context.azure_subscription = None
    context.azure_resource_group = None
    report_error = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "error", report_error)
    monkeypatch.setattr(azure_redis_menu, "get_cloud_identity", lambda *_args, **_kwargs: {
        "authenticated": False,
        "name": "Not logged in",
    })

    assert azure_redis_menu._ensure_azure_context() is False
    assert "Log in to Azure" in report_error.call_args.args[0]


def test_redis_menu_stops_when_context_is_unavailable(monkeypatch):
    monkeypatch.setattr(azure_redis_menu, "_ensure_azure_context", lambda: False)
    experiments = MagicMock()
    monkeypatch.setattr(azure_redis_menu, "get_experiments", experiments)

    assert azure_redis_menu.redis_experiment_menu() is None
    experiments.assert_not_called()
