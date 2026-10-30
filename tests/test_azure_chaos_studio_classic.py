import sys
from builtins import __import__ as builtin_import
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.providers.azure import rbac
from chaosforge.providers.azure.chaos_studio import classic, classic_faults


def _sdk(monkeypatch, chaos_client, resource_client):
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=MagicMock()))
    monkeypatch.setitem(sys.modules, "azure.mgmt.chaos", SimpleNamespace(ChaosManagementClient=lambda *_: chaos_client))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.chaos.models",
        SimpleNamespace(
            Capability=lambda **kwargs: kwargs, ChaosExperimentBranch=lambda **kwargs: kwargs,
            ChaosExperimentStep=lambda **kwargs: kwargs, ChaosTargetListSelector=lambda **kwargs: kwargs,
            ContinuousAction=lambda **kwargs: kwargs, DiscreteAction=lambda **kwargs: kwargs,
            Experiment=lambda **kwargs: kwargs,
            KeyValuePair=lambda **kwargs: kwargs, ManagedServiceIdentity=lambda **kwargs: kwargs,
            ManagedServiceIdentityType=SimpleNamespace(USER_ASSIGNED="UserAssigned"),
            Target=lambda **kwargs: kwargs, TargetReference=lambda **kwargs: kwargs,
            TargetReferenceType=SimpleNamespace(CHAOS_TARGET="ChaosTarget"),
        ),
    )
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.resource.resources", SimpleNamespace(ResourceManagementClient=lambda *_: resource_client)
    )


def test_runs_generic_service_direct_classic_fault(monkeypatch):
    chaos = SimpleNamespace(targets=MagicMock(), capabilities=MagicMock(), experiments=MagicMock())
    chaos.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    chaos.experiments.get_execution.return_value = SimpleNamespace(status="Succeeded")
    resource = SimpleNamespace(
        providers=MagicMock(), resource_groups=SimpleNamespace(get=lambda _: SimpleNamespace(location="eastus"))
    )
    _sdk(monkeypatch, chaos, resource)
    monkeypatch.setattr(classic.time, "time", lambda: 1)

    result = classic.run_service_direct_classic_experiment(
        "sub", "rg", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app",
        "urn:csci:microsoft:azureAppService:restart/1.0", "Microsoft-AzureAppService", "/identity",
        action_parameters={"slot": "production"}, duration="PT2M",
    )

    assert resource.providers.register.call_args.args == ("Microsoft.Chaos",)
    assert chaos.targets.create_or_update.call_args.args[:5] == (
        "rg", "Microsoft.Web", "sites", "app", "Microsoft-AzureAppService"
    )
    assert chaos.targets.create_or_update.call_args.args[5] == {"properties": {}}
    assert chaos.capabilities.create_or_update.call_args.args[5] == "Restart-1.0"
    experiment = chaos.experiments.begin_create_or_update.call_args.args[2]
    action = experiment["steps"][0]["branches"][0]["actions"][0]
    assert action["parameters"] == [{"key": "slot", "value": "production"}]
    assert action["duration"] == "PT2M"
    assert result["target"].endswith("Microsoft.Web/sites/app")


@pytest.mark.parametrize("role", classic.ROLE_DEFINITIONS)
def test_role_assignment_command_supports_service_direct_roles(role):
    assert f"--role '{role}'" in classic.role_assignment_command("principal", "/target", role)


def test_identity_bootstrap_assigns_requested_role(monkeypatch):
    service = classic.AzureChaosIdentityService("sub", object())
    identity = {"id": "/identity", "principal_id": "principal"}
    grant = MagicMock()
    monkeypatch.setattr(service, "list_identities", lambda: [identity])
    monkeypatch.setattr(service, "has_role", lambda *_: False)
    monkeypatch.setattr(service, "grant_role", grant)
    monkeypatch.setattr(service, "readiness", lambda *_: {"status": "ready"})

    assert service.bootstrap("identity-rg", "/target", "Website Contributor") == {"status": "ready"}
    grant.assert_called_once_with("/identity", "/target", "Website Contributor")
    assert service.last_bootstrap_outcome == {"identity_created": False, "role_assigned": True}


def test_classic_helper_validates_inputs_and_target_id():
    with pytest.raises(ValueError, match="target_resource_id is required"):
        classic.run_service_direct_classic_experiment("sub", "rg", "", "urn:x:y/1.0", "target", "identity")
    with pytest.raises(ValueError, match="valid Azure resource ID"):
        classic._target_parts("not-a-resource")
    assert "--role 'Contributor'" in classic.role_assignment_command(
        "principal", "/target", "Contributor"
    )
    with pytest.raises(ValueError, match="Unsupported"):
        classic.role_assignment_command("principal", "/target", "Unknown Role")


def test_azure_role_policy_displays_data_plane_alternatives_and_rejects_unknown_roles():
    assert rbac.accepted_role_names("Key Vault Certificates Officer") == (
        "Key Vault Certificates Officer, Key Vault Administrator"
    )
    with pytest.raises(ValueError, match="Unsupported"):
        rbac.accepted_role_definition_ids("Unknown Role")


@pytest.mark.parametrize("service, experiment_id", classic_faults.CLASSIC_FAULTS)
def test_classic_fault_details_and_action_parameters(service, experiment_id):
    urn, target, role = classic_faults.fault_details(service, experiment_id)
    assert urn.startswith("urn:csci:microsoft:")
    assert target.startswith("Microsoft-")
    assert role in classic.ROLE_DEFINITIONS
    values = {
        "abrupt_shutdown": True,
        "instances": "[\"0\"]",
        "read_region": "eastus",
        "desired_state": "Disabled",
        "event_hubs": "*",
        "certificate_name": "certificate",
        "enabled": False,
    }
    assert isinstance(classic_faults.action_parameters(service, experiment_id, values), dict)


def test_key_vault_temporary_faults_expose_a_duration_input():
    import json
    from pathlib import Path

    metadata = json.loads(
        Path("chaosforge/providers/azure/components/azure_key_vault/experiments/metadata.json").read_text()
    )
    inputs = {
        experiment["id"]: {field["name"] for field in experiment["inputs"]}
        for experiment in metadata["experiments"]
    }

    assert "duration" in inputs["azure-key-vault-disable-certificate"]
    assert "duration" in inputs["azure-key-vault-update-certificate-policy"]


def test_classic_fault_details_rejects_unknown_experiment():
    with pytest.raises(ValueError, match="Unsupported Azure Chaos Studio"):
        classic_faults.fault_details("azure_vm", "unknown")


@pytest.mark.parametrize(
    ("experiment_id", "values", "expected"),
    [
        ("azure-vm-shutdown", {}, {"abruptShutdown": False}),
        (
                "azure-vmss-shutdown",
                {"abrupt_shutdown": True, "instances": "[0]"},
                {"abruptShutdown": True, "instances": '["0"]'},
        ),
        ("azure-cosmos-db-failover", {"read_region": "westus"}, {"readRegion": "westus"}),
        (
            "azure-key-vault-update-certificate-policy",
            {"certificate_name": "cert", "enabled": True},
            {"certificateName": "cert", "enabled": True},
        ),
    ],
)
def test_classic_fault_parameter_translation(experiment_id, values, expected):
    assert classic_faults.action_parameters("azure_vm", experiment_id, values) == expected


def test_key_vault_classic_faults_require_certificate_data_plane_role():
    for experiment_id in (
        "azure-key-vault-deny-access",
        "azure-key-vault-disable-certificate",
        "azure-key-vault-increment-certificate-version",
        "azure-key-vault-update-certificate-policy",
    ):
        assert classic_faults.fault_details("azure_key_vault", experiment_id)[2] == "Key Vault Certificates Officer"
    assert classic.ROLE_DEFINITIONS["Key Vault Certificates Officer"] == "a4417e6f-fecd-4de8-b567-7b0420556985"


def test_classic_identity_service_covers_create_readiness_and_grant_paths(monkeypatch):
    service = classic.AzureChaosIdentityService("sub", object())
    identity = {"id": "/identity", "principal_id": "principal"}
    monkeypatch.setattr(service, "list_identities", lambda: [])
    monkeypatch.setattr(service, "create_identity", lambda _: identity)
    monkeypatch.setattr(service, "has_role", lambda *_: False)
    grant = MagicMock()
    monkeypatch.setattr(service, "grant_role", grant)
    monkeypatch.setattr(service, "readiness", lambda *_: {"status": "ready", "identity": identity})
    assert service.bootstrap("rg", "/target", "Virtual Machine Contributor")["status"] == "ready"
    grant.assert_called_once_with("/identity", "/target", "Virtual Machine Contributor")

    service = classic.AzureChaosIdentityService("sub", object())
    monkeypatch.setattr(service, "list_identities", lambda: [])
    assert service.readiness("missing", "/target", "Virtual Machine Contributor")["status"] == "missing"
    monkeypatch.setattr(service, "list_identities", lambda: [{"id": "/identity", "principal_id": ""}])
    assert service.readiness("/identity", "/target", "Virtual Machine Contributor")["status"] == "blocked"
    monkeypatch.setattr(service, "list_identities", lambda: [identity])
    monkeypatch.setattr(service, "has_role", lambda *_: False)
    assert service.readiness("/identity", "/target", "Virtual Machine Contributor")["status"] == "missing_role"


def test_classic_identity_service_grant_and_helpers(monkeypatch):
    assignments = SimpleNamespace(create=MagicMock(), list_for_scope=lambda *_args, **_kwargs: [])
    monkeypatch.setitem(sys.modules, "azure.mgmt.authorization", SimpleNamespace(AuthorizationManagementClient=lambda *_: SimpleNamespace(role_assignments=assignments)))
    monkeypatch.setitem(sys.modules, "azure.mgmt.authorization.models", SimpleNamespace(RoleAssignmentCreateParameters=lambda **kwargs: kwargs))
    service = classic.AzureChaosIdentityService("sub", object())
    monkeypatch.setattr(service, "list_identities", lambda: [{"id": "/identity", "principal_id": "principal"}])
    service.grant_role("/identity", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app", "Website Contributor")
    assert assignments.create.call_args.args[2]["principal_type"] == "ServicePrincipal"
    assert classic._scopes("/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app")[-1] == "/subscriptions/sub"
    with pytest.raises(ValueError, match="resource group"):
        classic._scopes("/subscriptions/sub/providers/Microsoft.Web/sites/app")

    assignments.list_for_scope = lambda *_args, **_kwargs: [SimpleNamespace(role_definition_id="/roles/de139f84-1756-47ae-9be6-808fbbe84772")]
    assert service.has_role("principal", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app", "Website Contributor") is True


def test_classic_run_validates_parameters_and_reports_missing_sdk(monkeypatch):
    with pytest.raises(ValueError, match="action_parameters must be a mapping"):
        classic.run_service_direct_classic_experiment(
            "sub", "rg", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app",
            "urn:csci:microsoft:appService:stop/1.0", "Microsoft-AppService", "/identity", []
        )
    def missing_chaos_sdk(name, *args, **kwargs):
        if name == "azure.mgmt.chaos":
            error = ImportError("missing Azure Chaos SDK")
            error.name = name
            raise error
        return builtin_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", missing_chaos_sdk)
    with pytest.raises(RuntimeError, match="dependency is unavailable"):
        classic.run_service_direct_classic_experiment(
            "sub", "rg", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app",
            "urn:csci:microsoft:appService:stop/1.0", "Microsoft-AppService", "/identity"
        )


def test_classic_helpers_cover_nested_targets_and_invalid_capabilities():
    target = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/loadBalancers/lb/frontendIPConfigurations/frontend"
    assert classic._target_parts(target) == (
        "Microsoft.Network", "loadBalancers/frontendIPConfigurations", "lb/frontend"
    )
    assert classic._capability_name("urn:csci:microsoft:virtualMachine:shutdown/2.0") == "Shutdown-2.0"
    with pytest.raises(ValueError, match="must end"):
        classic._capability_name("not-a-capability")
    with pytest.raises(ValueError, match="identify an Azure resource"):
        classic._target_parts("/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites")


def test_identity_service_handles_multiple_identities_ready_role_and_role_matching(monkeypatch):
    service = classic.AzureChaosIdentityService("sub", object())
    identities = [{"id": "/one", "principal_id": "one"}, {"id": "/two", "principal_id": "two"}]
    monkeypatch.setattr(service, "list_identities", lambda: identities)
    with pytest.raises(RuntimeError, match="Multiple identities"):
        service.bootstrap("rg", "/target", "Virtual Machine Contributor")

    identity = {"id": "/identity", "principal_id": "principal"}
    monkeypatch.setattr(service, "list_identities", lambda: [identity])
    monkeypatch.setattr(service, "has_role", lambda *_: True)
    assert service.readiness("/identity", "/target", "Virtual Machine Contributor")["status"] == "ready"

    assignments = SimpleNamespace(
        list_for_scope=lambda *_args, **_kwargs: [
            SimpleNamespace(role_definition_id="/roleDefinitions/9980E02C-C2BE-4D73-94E8-173B1DC7C5B")
        ]
    )
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=lambda *_: SimpleNamespace(role_assignments=assignments)),
    )
    assert service.has_role("principal", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app", "Virtual Machine Contributor")


def test_identity_service_uses_azure_supported_principal_filter(monkeypatch):
    calls = []
    assignments = SimpleNamespace(
        list_for_scope=lambda scope, **kwargs: calls.append((scope, kwargs)) or [
            SimpleNamespace(
                principal_id="principal",
                role_definition_id="/roleDefinitions/9980e02c-c2be-4d73-94e8-173b1dc7c5b",
            )
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(
            AuthorizationManagementClient=lambda *_: SimpleNamespace(
                role_assignments=assignments
            )
        ),
    )
    target_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app"

    assert classic.AzureChaosIdentityService("sub", object()).has_role(
        "principal", target_id, "Virtual Machine Contributor"
    )
    assert calls == [(target_id, {"filter": "principalId eq 'principal'"})]


@pytest.mark.parametrize(
    ("required_role", "assigned_role"),
    [
        ("Virtual Machine Contributor", "Contributor"),
        ("Website Contributor", "Owner"),
        ("Cosmos DB Operator", "Contributor"),
        ("Key Vault Certificates Officer", "Key Vault Administrator"),
    ],
)
def test_identity_service_accepts_safe_broader_roles(
    monkeypatch, required_role, assigned_role
):
    assignments = SimpleNamespace(
        list_for_scope=lambda *_args, **_kwargs: [
            SimpleNamespace(
                principal_id="principal",
                role_definition_id=f"/roleDefinitions/{classic.ROLE_DEFINITIONS[assigned_role]}",
            )
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=lambda *_: SimpleNamespace(role_assignments=assignments)),
    )

    assert classic.AzureChaosIdentityService("sub", object()).has_role(
        "principal", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app", required_role
    )


@pytest.mark.parametrize("assigned_role", ["Contributor", "Owner"])
def test_identity_service_rejects_management_roles_for_key_vault_data_plane(
    monkeypatch, assigned_role
):
    assignments = SimpleNamespace(
        list_for_scope=lambda *_args, **_kwargs: [
            SimpleNamespace(
                principal_id="principal",
                role_definition_id=f"/roleDefinitions/{classic.ROLE_DEFINITIONS[assigned_role]}",
            )
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=lambda *_: SimpleNamespace(role_assignments=assignments)),
    )

    assert not classic.AzureChaosIdentityService("sub", object()).has_role(
        "principal", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/vault", "Key Vault Certificates Officer"
    )


def test_identity_service_delegates_and_grant_rejects_unresolved_identity(monkeypatch):
    service = classic.AzureChaosIdentityService("sub", object())
    backend = MagicMock()
    backend.list_identities.return_value = [{"id": "/identity"}]
    backend.create_identity.return_value = {"id": "/created"}
    module = SimpleNamespace(AzureRedisChaosIdentityService=MagicMock(return_value=backend))
    monkeypatch.setitem(
        sys.modules, "chaosforge.providers.azure.components.azure_redis.chaos_identity", module
    )
    assert service.list_identities() == [{"id": "/identity"}]
    assert service.create_identity("rg") == {"id": "/created"}
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=MagicMock()),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.authorization.models",
        SimpleNamespace(RoleAssignmentCreateParameters=MagicMock()),
    )
    monkeypatch.setattr(service, "list_identities", lambda: [])
    with pytest.raises(RuntimeError, match="could not be resolved"):
        service.grant_role("/identity", "/target", "Virtual Machine Contributor")


def test_identity_service_resolves_explicit_identity_resource_id(monkeypatch):
    service = classic.AzureChaosIdentityService("sub", object())
    identities = SimpleNamespace(
        get=lambda resource_group, name: SimpleNamespace(
            id=f"/subscriptions/sub/resourceGroups/{resource_group}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{name}",
            name=name,
            principal_id="principal",
        )
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.msi",
        SimpleNamespace(ManagedServiceIdentityClient=lambda *_: SimpleNamespace(user_assigned_identities=identities)),
    )

    assert service.get_identity(
        "/subscriptions/sub/resourcegroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaos"
    ) == {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaos",
        "name": "chaos",
        "resource_group": "rg",
        "principal_id": "principal",
    }
    with pytest.raises(ValueError, match="valid user-assigned identity"):
        service.get_identity("not-an-arm-id")


def test_wait_for_completion_handles_success_failure_and_timeout(monkeypatch):
    client = SimpleNamespace(experiments=MagicMock())
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.return_value = SimpleNamespace(status="success")
    classic._wait_for_completion(client, "rg", "experiment")

    client.experiments.get_execution.return_value = SimpleNamespace(status="Cancelled")
    client.experiments.execution_details.return_value = SimpleNamespace(
        properties=SimpleNamespace(failure_reason="Target permission is missing.")
    )
    with pytest.raises(RuntimeError, match="Target permission is missing"):
        classic._wait_for_completion(client, "rg", "experiment")

    monkeypatch.setattr(classic.time, "monotonic", lambda: 1)
    with pytest.raises(TimeoutError, match="after 0 seconds; last Azure status: no execution reported"):
        classic._wait_for_completion(client, "rg", "experiment", timeout_seconds=0)


def test_wait_for_completion_defaults_to_an_eight_minute_maximum(monkeypatch):
    client = SimpleNamespace(experiments=MagicMock())
    times = iter((0, 480))
    monkeypatch.setattr(classic.time, "monotonic", lambda: next(times))

    with pytest.raises(TimeoutError, match="after 480 seconds"):
        classic._wait_for_completion(client, "rg", "experiment")


def test_wait_for_completion_accepts_a_provider_completion_check(monkeypatch):
    client = SimpleNamespace(experiments=MagicMock())
    completion_check = MagicMock(return_value=True)
    monkeypatch.setattr(classic.time, "monotonic", lambda: 0)

    classic._wait_for_completion(client, "rg", "experiment", completion_check)

    completion_check.assert_called_once_with()
    client.experiments.list_all_executions.assert_not_called()


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (SimpleNamespace(properties=SimpleNamespace(failure_reason="failure reason")), "failure reason"),
        (
            SimpleNamespace(
                properties=SimpleNamespace(
                    details=[SimpleNamespace(properties=SimpleNamespace(error="action error"))]
                )
            ),
            "action error",
        ),
        (
            SimpleNamespace(
                properties=SimpleNamespace(
                    details=[SimpleNamespace(properties=SimpleNamespace(message="action message"))]
                )
            ),
            "action message",
        ),
        (
            SimpleNamespace(
                properties=SimpleNamespace(
                    run_information=SimpleNamespace(
                        steps=[
                            SimpleNamespace(
                                branches=[
                                    SimpleNamespace(
                                        actions=[
                                            SimpleNamespace(
                                                targets=[
                                                    SimpleNamespace(
                                                        error=SimpleNamespace(
                                                            code="Forbidden",
                                                            message="Certificate access is denied.",
                                                        )
                                                    )
                                                ]
                                            )
                                        ]
                                    )
                                ]
                            )
                        ]
                    )
                )
            ),
            "Forbidden: Certificate access is denied.",
        ),
        (
            SimpleNamespace(
                properties=SimpleNamespace(
                    run_information=SimpleNamespace(
                        steps=[
                            SimpleNamespace(
                                branches=[
                                    SimpleNamespace(
                                        actions=[
                                            SimpleNamespace(
                                                targets=[
                                                    SimpleNamespace(error=None),
                                                    SimpleNamespace(
                                                        error=SimpleNamespace(
                                                            code=None,
                                                            message="Certificate is missing.",
                                                        )
                                                    ),
                                                ]
                                            )
                                        ]
                                    )
                                ]
                            )
                        ]
                    )
                )
            ),
            "Certificate is missing.",
        ),
        (
            SimpleNamespace(
                properties=SimpleNamespace(
                    run_information=SimpleNamespace(
                        steps=[
                            SimpleNamespace(
                                branches=[
                                    SimpleNamespace(
                                        actions=[
                                            SimpleNamespace(
                                                targets=[
                                                    SimpleNamespace(
                                                        error=SimpleNamespace(
                                                            code="CertificateNotFound",
                                                            message=None,
                                                        )
                                                    )
                                                ]
                                            )
                                        ]
                                    )
                                ]
                            )
                        ]
                    )
                )
            ),
            "CertificateNotFound",
        ),
        (SimpleNamespace(error="top-level error"), "top-level error"),
        (SimpleNamespace(message="top-level message"), "top-level message"),
    ],
)
def test_classic_failure_detail_extracts_azure_diagnostics(details, expected):
    client = SimpleNamespace(
        experiments=SimpleNamespace(execution_details=lambda *_: details)
    )

    assert classic._execution_failure_detail(client, "rg", "experiment", "run") == expected


def test_classic_failure_detail_tolerates_unavailable_azure_diagnostics():
    client = SimpleNamespace(
        experiments=SimpleNamespace(
            execution_details=lambda *_: (_ for _ in ()).throw(RuntimeError("unavailable"))
        )
    )

    assert classic._execution_failure_detail(client, "rg", "experiment", "run") == ""


@pytest.mark.parametrize(
    ("instances", "expected"),
    [("[0]", '["0"]'), ('["1", "2"]', '["1", "2"]')],
)
def test_vmss_shutdown_normalizes_instance_ids_for_chaos_studio(instances, expected):
    assert classic_faults.action_parameters(
        "azure_vmss", "azure-vmss-shutdown", {"instances": instances}
    ) == {"abruptShutdown": False, "instances": expected}


@pytest.mark.parametrize("instances", ("[]", "[true]", "[\"node-a\"]", "not-json"))
def test_vmss_shutdown_rejects_invalid_instance_ids(instances):
    with pytest.raises(ValueError, match="Instance IDs"):
        classic_faults.action_parameters(
            "azure_vmss", "azure-vmss-shutdown", {"instances": instances}
        )


def test_has_role_returns_false_after_all_scopes_and_waits_for_execution(monkeypatch):
    assignments = SimpleNamespace(list_for_scope=lambda *_args, **_kwargs: [])
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.authorization",
        SimpleNamespace(AuthorizationManagementClient=lambda *_: SimpleNamespace(role_assignments=assignments)),
    )
    service = classic.AzureChaosIdentityService("sub", object())
    assert not service.has_role(
            "principal", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app", "Virtual Machine Contributor"
    )

    client = SimpleNamespace(experiments=MagicMock())
    client.experiments.list_all_executions.side_effect = [[], [SimpleNamespace(name="run")]]
    client.experiments.get_execution.return_value = SimpleNamespace(status="Succeeded")
    monotonic = iter([0, 0, 1])
    monkeypatch.setattr(classic.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(classic.time, "sleep", MagicMock())
    classic._wait_for_completion(client, "rg", "experiment", timeout_seconds=2)
