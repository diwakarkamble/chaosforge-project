import builtins
import sys
from types import SimpleNamespace

import pytest
from chaoslib.experiment import ensure_experiment_is_valid
from chaoslib.loader import load_experiment

from chaosforge.providers.azure.components.azure_event_hub.experiments.custom.actions import (
    public_access_actions,
    state_actions,
)


def test_change_and_restore_event_hub_state_preserves_each_entity_baseline(monkeypatch, tmp_path):
    entities = {
        "orders": SimpleNamespace(name="orders", status="Active"),
        "payments": SimpleNamespace(name="payments", status="SendDisabled"),
    }
    updates = []
    client = SimpleNamespace(
        event_hubs=SimpleNamespace(
            list_by_namespace=lambda *_: list(entities.values()),
            get=lambda *_args: entities[_args[-1]],
            create_or_update=lambda *_args: updates.append((_args[-2], _args[-1].status)),
        )
    )
    monkeypatch.setattr(state_actions, "_client", lambda _: client)
    monkeypatch.setattr(state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.EventHub/namespaces/ns"

    state_actions.change_event_hub_state("sub", "rg", resource_id, "Disabled", "*")
    assert updates == [("orders", "Disabled"), ("payments", "Disabled")]

    state_actions.restore_event_hub_state("sub", "rg", resource_id)
    assert updates[-2:] == [("orders", "Active"), ("payments", "SendDisabled")]
    assert not state_actions._path("sub", "rg", "ns").exists()


@pytest.mark.parametrize("value", ("", "*,orders"))
def test_event_hub_state_rejects_ambiguous_entity_selection(value):
    with pytest.raises(ValueError, match="event_hubs"):
        state_actions._names(value)


def test_event_hub_restore_handles_missing_and_mismatched_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.EventHub/namespaces/ns"

    assert state_actions.restore_event_hub_state("sub", "rg", resource_id) == "No Event Hub state was recorded."

    path = state_actions._path("sub", "rg", "ns")
    path.parent.mkdir(parents=True)
    path.write_text('{"resource_id":"/other","entities":{}}', encoding="utf-8")
    with pytest.raises(ValueError, match="another namespace"):
        state_actions.restore_event_hub_state("sub", "rg", resource_id)


def test_event_hub_state_rejects_empty_namespace_and_sdk_dependency(monkeypatch, tmp_path):
    client = SimpleNamespace(
        event_hubs=SimpleNamespace(list_by_namespace=lambda *_: [])
    )
    monkeypatch.setattr(state_actions, "_client", lambda _: client)
    monkeypatch.setattr(state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.EventHub/namespaces/ns"

    with pytest.raises(ValueError, match="no Event Hub entities"):
        state_actions.change_event_hub_state("sub", "rg", resource_id, "Disabled", "*")

    monkeypatch.setattr(state_actions, "_client", lambda _: (_ for _ in ()).throw(RuntimeError("sdk")))
    with pytest.raises(RuntimeError, match="sdk"):
        state_actions.change_event_hub_state("sub", "rg", resource_id, "Disabled", "orders")


def test_event_hub_client_constructs_sdk_client(monkeypatch):
    credential = object()
    client = object()
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: credential))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.eventhub",
        SimpleNamespace(EventHubManagementClient=lambda actual_credential, subscription: (client, actual_credential, subscription)),
    )

    assert state_actions._client("sub") == (client, credential, "sub")


def test_event_hub_client_reports_missing_sdk(monkeypatch):
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name == "azure.mgmt.eventhub":
            raise ImportError("missing SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)
    with pytest.raises(RuntimeError, match="SDK dependencies are unavailable"):
        state_actions._client("sub")


def test_event_hub_toolkit_definition_is_valid():
    definition = load_experiment(
        "chaosforge/providers/azure/components/azure_event_hub/experiments/custom/definitions/azure-event-hub-state.json"
    )

    ensure_experiment_is_valid(definition)


def test_event_hub_public_access_definition_includes_a_fault_hold():
    definition = load_experiment(
        "chaosforge/providers/azure/components/azure_event_hub/experiments/custom/definitions/azure-event-hub-public-access-disruption.json"
    )

    ensure_experiment_is_valid(definition)
    assert definition["configuration"]["duration_seconds"] == 300
    assert definition["method"][1]["name"] == "hold-public-access-disruption"


def test_event_hub_public_access_uses_namespace_update_and_restores_baseline(monkeypatch, tmp_path):
    namespace = SimpleNamespace(public_network_access="Enabled")
    updates = []
    client = SimpleNamespace(
        namespaces=SimpleNamespace(
            get=lambda *_: namespace,
            update=lambda *args: updates.append((args[1], args[2].public_network_access)) or "updated",
        )
    )
    monkeypatch.setattr(public_access_actions, "_client", lambda _: client)
    monkeypatch.setattr(public_access_actions, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.EventHub/namespaces/ns"

    assert public_access_actions.disable_public_access("sub", "rg", resource_id) == "updated"
    assert updates == [("ns", "Disabled")]
    assert public_access_actions.restore_public_access("sub", "rg", resource_id) == "updated"
    assert updates == [("ns", "Disabled"), ("ns", "Enabled")]
    assert not public_access_actions._path("sub", "rg", "ns").exists()
