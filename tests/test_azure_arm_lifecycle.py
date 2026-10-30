import builtins
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.lifecycle.checks.azure_arm_adapter import AzureARMResourceAdapter
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.resolver import CheckResolver


@pytest.mark.parametrize(
    ("service", "experiment_id", "recovery_supported"),
    [
        ("azure_postgres_flexible", "azure-postgres-flexible-toolkit-stop", False),
        ("azure_postgres_flexible", "azure-postgres-flexible-restart", False),
        ("azure_postgres_flexible", "azure-postgres-flexible-firewall-disruption", True),
        ("azure_app_service", "azure-app-service-toolkit-stop", False),
        ("azure_app_service", "azure-app-service-slot-swap", True),
        ("azure_functions", "azure-functions-stop-app-service", True),
        ("azure_functions", "azure-functions-slot-swap", True),
        ("azure_key_vault", "azure-key-vault-deny-access", True),
        ("azure_key_vault", "azure-key-vault-disable-certificate", False),
        ("azure_key_vault", "azure-key-vault-increment-certificate-version", False),
        ("azure_key_vault", "azure-key-vault-update-certificate-policy", False),
        ("azure_key_vault", "azure-key-vault-secret-disable", True),
        ("azure_cosmos_db", "azure-cosmos-db-failover", False),
        ("azure_cosmos_db", "azure-cosmos-db-public-access-disruption", True),
        ("azure_event_hub", "azure-event-hub-state", False),
        ("azure_event_hub", "azure-event-hub-public-access-disruption", True),
        ("azure_vm", "azure-vm-redeploy", True),
        ("azure_vm", "azure-vm-shutdown", True),
        ("azure_vm", "azure-vm-toolkit-reboot", False),
        ("azure_vm", "azure-vm-boot-diagnostics-toggle", True),
        ("azure_vmss", "azure-vmss-shutdown", True),
        ("azure_vmss", "azure-vmss-shutdown-2-0", True),
        ("azure_vmss", "azure-vmss-toolkit-reboot", False),
        ("azure_vmss", "azure-vmss-overprovision-toggle", True),
        ("azure_container_apps", "azure-container-app-revision-restart", False),
        ("azure_container_apps", "azure-container-app-traffic-shift", True),
        ("azure_container_apps", "azure-container-app-scale-zero", True),
    ],
)
def test_azure_arm_experiments_resolve_lifecycle_checks(
    service, experiment_id, recovery_supported
):
    check = CheckResolver().resolve(
        SimpleNamespace(id=experiment_id, service=service, variables={})
    )

    assert isinstance(check, CommonResourceCheck)
    assert isinstance(check.adapter, AzureARMResourceAdapter)
    assert check.recovery_supported is recovery_supported


def test_azure_arm_adapter_captures_generic_resource_status(monkeypatch):
    client = SimpleNamespace(
        providers=SimpleNamespace(
            get=MagicMock(
                return_value=SimpleNamespace(
                    resource_types=[
                        SimpleNamespace(
                            resource_type="virtualMachines",
                            api_versions=["2024-03-01", "2025-01-01-preview"],
                        )
                    ]
                )
            )
        ),
        resources=SimpleNamespace(
            get_by_id=MagicMock(
                return_value=SimpleNamespace(
                    name="vm", id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                    type="Microsoft.Compute/virtualMachines",
                    properties={"provisioningState": "Succeeded", "publicNetworkAccess": "Enabled"},
                )
            )
        )
    )
    import azure.mgmt.resource.resources

    monkeypatch.setattr(
        azure.mgmt.resource.resources, "ResourceManagementClient", lambda *_: client
    )

    snapshot = AzureARMResourceAdapter().capture(
        {"resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"}
    )

    assert snapshot["exists"] is True
    assert snapshot["identity"]["type"] == "Microsoft.Compute/virtualMachines"
    assert snapshot["state"]["provisioning_state"] == "Succeeded"
    assert snapshot["configuration"]["public_network_access"] == "Enabled"
    client.providers.get.assert_called_once_with("Microsoft.Compute")
    client.resources.get_by_id.assert_called_once_with(
        "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        api_version="2024-03-01",
    )


def test_azure_arm_adapter_returns_missing_snapshot_for_missing_resource(monkeypatch):
    import azure.mgmt.resource.resources
    from azure.core.exceptions import ResourceNotFoundError

    client = SimpleNamespace(
        providers=SimpleNamespace(
            get=MagicMock(
                return_value=SimpleNamespace(
                    resource_types=[
                        SimpleNamespace(
                            resource_type="virtualMachines",
                            api_versions=["2024-03-01"],
                        )
                    ]
                )
            )
        ),
        resources=SimpleNamespace(
            get_by_id=MagicMock(side_effect=ResourceNotFoundError(message="missing"))
        )
    )
    monkeypatch.setattr(
        azure.mgmt.resource.resources, "ResourceManagementClient", lambda *_: client
    )

    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/missing"
    assert AzureARMResourceAdapter().capture({"resource_id": resource_id}) == {
        "exists": False,
        "identity": {"id": resource_id},
    }


def test_azure_arm_adapter_handles_object_properties_and_target_subscription(monkeypatch):
    client = SimpleNamespace(
        providers=SimpleNamespace(
            get=MagicMock(
                return_value=SimpleNamespace(
                    resource_types=[
                        SimpleNamespace(
                            resource_type="widgets",
                            api_versions=["2025-02-01-preview", "2024-02-01-preview"],
                        )
                    ]
                )
            )
        ),
        resources=SimpleNamespace(
            get_by_id=MagicMock(
                return_value=SimpleNamespace(
                    properties=SimpleNamespace(
                        provisioning_state="Updating", public_network_access="Disabled"
                    )
                )
            )
        )
    )
    import azure.mgmt.resource.resources

    monkeypatch.setattr(
        azure.mgmt.resource.resources, "ResourceManagementClient", lambda *_: client
    )

    snapshot = AzureARMResourceAdapter().capture(
        {
            "resource_id": "/subscriptions/target-sub/resourceGroups/rg/providers/Example.Provider/widgets/custom-name",
            "subscription_id": "target-sub",
        }
    )

    assert snapshot["identity"] == {
        "name": "custom-name",
        "id": "/subscriptions/target-sub/resourceGroups/rg/providers/Example.Provider/widgets/custom-name",
        "type": None,
    }
    assert snapshot["state"]["provisioning_state"] == "Updating"
    assert snapshot["configuration"]["public_network_access"] == "Disabled"
    client.resources.get_by_id.assert_called_once_with(
        "/subscriptions/target-sub/resourceGroups/rg/providers/Example.Provider/widgets/custom-name",
        api_version="2025-02-01-preview",
    )


def test_azure_arm_adapter_reports_missing_sdk_dependencies(monkeypatch):
    original_import = builtins.__import__

    def missing_identity(name, *args, **kwargs):
        if name == "azure.identity":
            raise ImportError("missing Azure identity")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_identity)

    with pytest.raises(RuntimeError, match="SDK dependencies are unavailable"):
        AzureARMResourceAdapter().capture(
            {"resource_id": "/subscriptions/sub/resourceGroups/rg/providers/type/name"}
        )


@pytest.mark.parametrize("resource_id", ("", "/providers/Microsoft.Compute/virtualMachines/vm"))
def test_azure_arm_adapter_requires_a_subscription_in_the_resource_id(resource_id):
    with pytest.raises(ValueError, match="require subscription_id"):
        AzureARMResourceAdapter().capture({"resource_id": resource_id})


def test_azure_arm_adapter_requires_a_provider_qualified_resource_id():
    with pytest.raises(ValueError, match="provider-qualified"):
        AzureARMResourceAdapter._api_version(
            SimpleNamespace(), "/subscriptions/sub/resourceGroups/rg/resource/name"
        )


def test_azure_arm_adapter_reports_missing_provider_api_versions():
    client = SimpleNamespace(
        providers=SimpleNamespace(
            get=lambda _: SimpleNamespace(resource_types=[])
        )
    )

    with pytest.raises(RuntimeError, match="did not publish API versions"):
        AzureARMResourceAdapter._api_version(
            client,
            "/subscriptions/sub/resourceGroups/rg/providers/Example.Provider/widgets/name",
        )


def test_auto_recovery_requires_the_baseline_provisioning_state():
    check = CheckResolver().resolve(
        SimpleNamespace(
            id="azure-vm-shutdown", service="azure_vm", variables={}
        )
    )
    baseline = {"exists": True, "state": {"provisioning_state": "Succeeded"}}
    check.adapter.capture = lambda _: {
        "exists": True,
        "state": {"provisioning_state": "Updating"},
    }

    assert check.validate({}, baseline)["passed"] is False


def test_event_hub_public_access_recovery_uses_the_restored_access_setting():
    check = CheckResolver().resolve(
        SimpleNamespace(
            id="azure-event-hub-public-access-disruption",
            service="azure_event_hub",
            variables={},
        )
    )
    baseline = {
        "exists": True,
        "state": {"provisioning_state": "Succeeded"},
        "configuration": {"public_network_access": "Enabled"},
    }
    check.adapter.capture = lambda _: {
        "exists": True,
        "state": {"provisioning_state": "Updating"},
        "configuration": {"public_network_access": "Enabled"},
    }

    result = check.validate({}, baseline)

    assert result["passed"] is True
    assert result["checks"] == {
        "resource_exists": True,
        "public_access_restored": True,
    }


def test_azure_arm_preconditions_require_existing_completed_resource():
    check = CheckResolver().resolve(
        SimpleNamespace(id="azure-vm-shutdown", service="azure_vm", variables={})
    )

    exists = check.preconditions["Azure resource must exist"]
    complete = check.preconditions["Azure resource provisioning must be complete"]
    assert exists({"exists": True}) is True
    assert exists({"exists": False}) is False
    assert complete({"state": {"provisioning_state": "Succeeded"}}) is True
    assert complete({"state": {}}) is True
    assert complete({"state": {"provisioning_state": "Updating"}}) is False


def test_post_validation_does_not_reapply_preconditions():
    check = CommonResourceCheck(
        AzureARMResourceAdapter(),
        predicates={"resource_exists": lambda current, baseline: current["exists"]},
        preconditions={"must be ready": lambda snapshot: snapshot["ready"]},
    )
    check.adapter.capture = lambda _: {"exists": True, "ready": False}

    with pytest.raises(ValueError, match="must be ready"):
        check.capture({})

    assert check.validate({}, {"exists": True})["passed"] is True
