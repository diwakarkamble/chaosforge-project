"""Isolated unit coverage for Azure SDK custom actions and their rollback state."""

import builtins
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.providers.azure import resource_id
from chaosforge.providers.azure.components.azure_app_service.experiments.custom.actions import (
    slot_actions as app_slots,
)
from chaosforge.providers.azure.components.azure_container_apps.experiments.custom.actions import (
    container_app_actions as container_apps,
)
from chaosforge.providers.azure.components.azure_cosmos_db.experiments.custom.actions import (
    public_access_actions as cosmos,
)
from chaosforge.providers.azure.components.azure_event_hub.experiments.custom.actions import (
    public_access_actions as event_hub,
)
from chaosforge.providers.azure.components.azure_functions.experiments.custom.actions import (
    slot_actions as function_slots,
)
from chaosforge.providers.azure.components.azure_key_vault.experiments.custom.actions import (
    secret_actions as key_vault,
)
from chaosforge.providers.azure.components.azure_postgres_flexible.experiments.custom.actions import (
    postgres_actions as postgres,
)
from chaosforge.providers.azure.components.azure_vm.experiments.custom.actions import (
    diagnostics_actions as vm,
)
from chaosforge.providers.azure.components.azure_vmss.experiments.custom.actions import (
    overprovision_actions as vmss,
)

RESOURCE_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Test/widgets/name"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(RESOURCE_ID, "name"), (" name/ ", "name"), (123, "123")],
)
def test_resource_name_returns_terminal_arm_segment(value, expected):
    assert resource_id.resource_name(value) == expected


@pytest.mark.parametrize("value", (None, "", " / "))
def test_resource_name_requires_a_value(value):
    with pytest.raises(ValueError, match="resource_id"):
        resource_id.resource_name(value)


@pytest.mark.parametrize("module", (cosmos, event_hub, vm, vmss))
def test_simple_toggle_actions_persist_restore_and_clean_up(module, monkeypatch, tmp_path):
    monkeypatch.setattr(module, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    calls = []
    if module is cosmos:
        operations = SimpleNamespace(
            get=lambda *_: SimpleNamespace(public_network_access="Enabled"),
            begin_update=lambda *args: calls.append(args) or SimpleNamespace(result=lambda: "restored"),
        )
        client = SimpleNamespace(database_accounts=operations)
        disable, restore = module.disable_public_access, module.restore_public_access
        expected_disabled = {"properties": {"publicNetworkAccess": "Disabled"}}
    elif module is event_hub:
        operations = SimpleNamespace(
            get=lambda *_: SimpleNamespace(public_network_access="Enabled"),
            update=lambda *args: calls.append(args) or "restored",
        )
        client = SimpleNamespace(namespaces=operations)
        disable, restore = module.disable_public_access, module.restore_public_access
        expected_disabled = "Disabled"
    elif module is vm:
        boot = SimpleNamespace(enabled=True, storage_uri="https://storage")
        operations = SimpleNamespace(
            get=lambda *_: SimpleNamespace(diagnostics_profile=SimpleNamespace(boot_diagnostics=boot)),
            begin_update=lambda *args: calls.append(args) or SimpleNamespace(result=lambda: "restored"),
        )
        client = SimpleNamespace(virtual_machines=operations)
        disable, restore = module.disable_boot_diagnostics, module.restore_boot_diagnostics
        expected_disabled = {
            "properties": {"diagnosticsProfile": {"bootDiagnostics": {"enabled": False}}}
        }
    else:
        operations = SimpleNamespace(
            get=lambda *_: SimpleNamespace(overprovision=True),
            begin_update=lambda *args: calls.append(args) or SimpleNamespace(result=lambda: "restored"),
        )
        client = SimpleNamespace(virtual_machine_scale_sets=operations)
        disable, restore = module.disable_overprovision, module.restore_overprovision
        expected_disabled = {"properties": {"overprovision": False}}
    monkeypatch.setattr(module, "_client", lambda _: client)

    assert disable("sub", "rg", RESOURCE_ID) == "restored"
    path = module._path("sub", "rg", "name")
    assert path.is_file()
    if module is event_hub:
        assert calls[-1][-1].public_network_access == expected_disabled
    else:
        assert calls[-1][-1] == expected_disabled
    assert restore("sub", "rg", RESOURCE_ID) == "restored"
    if module is vm:
        assert calls[-1][-1] == {
            "properties": {
                "diagnosticsProfile": {
                    "bootDiagnostics": {"enabled": True, "storageUri": "https://storage"}
                }
            }
        }
    assert not path.exists()
    assert "No " in restore("sub", "rg", RESOURCE_ID)


@pytest.mark.parametrize("module", (cosmos, event_hub, vm, vmss, container_apps, postgres, app_slots))
def test_stateful_actions_require_all_inputs(module):
    with pytest.raises(ValueError):
        module._require("sub", "", "resource")


def test_app_service_swap_restores_saved_state_and_function_apps_reexport_it(monkeypatch, tmp_path):
    monkeypatch.setattr(app_slots, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    swaps = MagicMock(return_value=SimpleNamespace(result=lambda: "swapped"))
    monkeypatch.setattr(app_slots, "_client", lambda _: SimpleNamespace(web_apps=SimpleNamespace(begin_swap_slot=swaps)))

    assert function_slots.swap_slots("sub", "rg", RESOURCE_ID, "blue", "green") == "swapped"
    path = app_slots._state_path("sub", "rg", "name")
    assert function_slots.restore_slot_swap("sub", "rg", RESOURCE_ID) == "swapped"
    assert swaps.call_args_list[-1].args == (
        "rg",
        "name",
        "green",
        {"targetSlot": "blue", "preserveVnet": False},
    )
    assert not path.exists()
    assert app_slots.restore_slot_swap("sub", "rg", RESOURCE_ID) == "No slot-swap state was recorded."


def test_container_app_actions_restart_traffic_and_scale_roll_back(monkeypatch, tmp_path):
    monkeypatch.setattr(container_apps, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    ingress = SimpleNamespace(
        traffic=[
            SimpleNamespace(
                revision_name="old", weight=100, label="stable", latest_revision=True
            )
        ]
    )
    app = SimpleNamespace(configuration=SimpleNamespace(ingress=ingress))
    revisions = SimpleNamespace(
        restart_revision=MagicMock(return_value="restarted"),
        get_revision=MagicMock(return_value=SimpleNamespace(active=True)),
        deactivate_revision=MagicMock(return_value="deactivated"),
        activate_revision=MagicMock(return_value="activated"),
    )
    apps = SimpleNamespace(
        get=MagicMock(return_value=app),
        begin_create_or_update=MagicMock(return_value=SimpleNamespace(result=lambda: "traffic")),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.appcontainers.models",
        SimpleNamespace(TrafficWeight=lambda **kwargs: {
            "revisionName": kwargs["revision_name"],
            "weight": kwargs["weight"],
            "latestRevision": kwargs["latest_revision"],
        }),
    )
    monkeypatch.setattr(container_apps, "_client", lambda _: SimpleNamespace(container_apps=apps, container_apps_revisions=revisions))

    assert container_apps.restart_revision("sub", "rg", RESOURCE_ID, "rev") == "restarted"
    assert container_apps.shift_traffic("sub", "rg", RESOURCE_ID, "new", "25") == "traffic"
    traffic_path = container_apps._state_path("sub", "rg", "name", "traffic")
    assert ingress.traffic == [
        {
            "revisionName": "new",
            "weight": 25,
            "latestRevision": False,
        }
    ]
    assert container_apps.restore_traffic("sub", "rg", RESOURCE_ID) == "traffic"
    assert ingress.traffic == [
        {"revisionName": "old", "weight": 100, "label": "stable", "latestRevision": True}
    ]
    assert not traffic_path.exists()
    assert container_apps.restore_traffic("sub", "rg", RESOURCE_ID) == "No traffic state was recorded."
    assert container_apps.scale_revision_to_zero("sub", "rg", RESOURCE_ID, "rev") == "deactivated"
    scale_path = container_apps._state_path("sub", "rg", "name", "rev")
    assert container_apps.restore_revision_scale("sub", "rg", RESOURCE_ID, "rev") == "activated"
    assert not scale_path.exists()
    assert container_apps.restore_revision_scale("sub", "rg", RESOURCE_ID, "rev") == "No revision-scale state was recorded."


def test_postgres_restart_and_firewall_rollback(monkeypatch, tmp_path):
    monkeypatch.setattr(postgres, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    rules = SimpleNamespace(
        get=lambda *_: SimpleNamespace(start_ip_address="10.0.0.1", end_ip_address="10.0.0.2"),
        begin_delete=lambda *_: SimpleNamespace(result=lambda: "deleted"),
        begin_create_or_update=MagicMock(return_value=SimpleNamespace(result=lambda: "created")),
    )
    monkeypatch.setattr(postgres, "_client", lambda _: SimpleNamespace(
        servers=SimpleNamespace(begin_restart=lambda *_: SimpleNamespace(result=lambda: "restarted")),
        firewall_rules=rules,
    ))

    assert postgres.restart_server("sub", "rg", RESOURCE_ID) == "restarted"
    assert postgres.remove_firewall_rule("sub", "rg", RESOURCE_ID, "office") == "deleted"
    path = postgres._state_path("sub", "rg", "name", "office")
    assert postgres.restore_firewall_rule("sub", "rg", RESOURCE_ID, "office") == "created"
    assert rules.begin_create_or_update.call_args.args == (
        "rg",
        "name",
        "office",
        {
            "properties": {
                "startIpAddress": "10.0.0.1",
                "endIpAddress": "10.0.0.2",
            }
        },
    )
    assert not path.exists()
    assert postgres.restore_firewall_rule("sub", "rg", RESOURCE_ID, "office") == "No firewall-rule state was recorded."


def test_key_vault_secret_rollback_and_missing_state(monkeypatch, tmp_path):
    monkeypatch.setattr(key_vault, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    update = MagicMock(return_value="updated")
    secret = SimpleNamespace(properties=SimpleNamespace(enabled=False, version="v1"))
    monkeypatch.setattr(key_vault, "_client", lambda _: SimpleNamespace(get_secret=lambda _: secret, update_secret_properties=update))

    assert key_vault.disable_secret(RESOURCE_ID, "api") == "updated"
    path = key_vault._state_path("https://name.vault.azure.net", "api")
    assert key_vault.restore_secret(RESOURCE_ID, "api") == "updated"
    assert update.call_args_list[-1].kwargs == {"enabled": False}
    assert not path.exists()
    assert key_vault.restore_secret(RESOURCE_ID, "api") == "No secret state was recorded."
    with pytest.raises(ValueError):
        key_vault.disable_secret("", "api")


@pytest.mark.parametrize(
    ("module", "dependency"),
    [
        (app_slots, "azure.mgmt.web"),
        (container_apps, "azure.mgmt.appcontainers"),
        (cosmos, "azure.mgmt.cosmosdb"),
        (event_hub, "azure.mgmt.eventhub"),
        (key_vault, "azure.keyvault.secrets"),
        (postgres, "azure.mgmt.rdbms.postgresql_flexibleservers"),
        (vm, "azure.mgmt.compute"),
        (vmss, "azure.mgmt.compute"),
    ],
)
def test_sdk_clients_explain_missing_dependencies(module, dependency, monkeypatch):
    original_import = builtins.__import__

    if module is key_vault:
        monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(SSLContext=MagicMock()))

    def missing_sdk(name, *args, **kwargs):
        if name == dependency:
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)
    message = "dependency is unavailable" if module is key_vault else "SDK dependencies"
    with pytest.raises(RuntimeError, match=message):
        module._client("sub" if module is not key_vault else "https://vault.vault.azure.net")


@pytest.mark.parametrize(
    ("module", "dependency", "client_name", "client_function"),
    [
        (app_slots, "azure.mgmt.web", "WebSiteManagementClient", "_client"),
        (container_apps, "azure.mgmt.appcontainers", "ContainerAppsAPIClient", "_client"),
        (cosmos, "azure.mgmt.cosmosdb", "CosmosDBManagementClient", "_client"),
        (event_hub, "azure.mgmt.eventhub", "EventHubManagementClient", "_client"),
        (key_vault, "azure.keyvault.secrets", "SecretClient", "_client"),
        (postgres, "azure.mgmt.rdbms.postgresql_flexibleservers", "PostgreSQLManagementClient", "_client"),
        (vm, "azure.mgmt.compute", "ComputeManagementClient", "_client"),
        (vmss, "azure.mgmt.compute", "ComputeManagementClient", "_client"),
    ],
)
def test_sdk_clients_construct_with_default_credentials(
    module, dependency, client_name, client_function, monkeypatch
):
    credential = object()
    client = object()
    constructor = MagicMock(return_value=client)
    monkeypatch.setitem(
        sys.modules,
        "azure.identity",
        SimpleNamespace(DefaultAzureCredential=MagicMock(return_value=credential)),
    )
    monkeypatch.setitem(sys.modules, dependency, SimpleNamespace(**{client_name: constructor}))
    if module is key_vault:
        monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(SSLContext=MagicMock()))

    value = "https://vault.vault.azure.net" if module is key_vault else "sub"
    assert getattr(module, client_function)(value) is client
    if module is key_vault:
        constructor.assert_called_once()
        assert constructor.call_args.kwargs["vault_url"] == value
        assert constructor.call_args.kwargs["credential"] is credential
        assert constructor.call_args.kwargs["transport"] is not None
    else:
        constructor.assert_called_once_with(credential, value)
