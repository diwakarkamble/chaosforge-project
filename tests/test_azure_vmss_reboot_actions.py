import builtins
import sys
from types import SimpleNamespace

import pytest

from chaosforge.providers.azure.components.azure_vmss.experiments.custom.actions import (
    reboot_actions,
)

RESOURCE_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/set"


def test_restart_vmss_instances_uses_selected_instance_ids(monkeypatch):
    calls = []
    client = SimpleNamespace(
        virtual_machine_scale_set_vms=SimpleNamespace(
            begin_restart=lambda *args: calls.append(args) or SimpleNamespace(result=lambda: None)
        )
    )
    monkeypatch.setattr(reboot_actions, "_client", lambda _: client)

    assert reboot_actions.restart_instances(
        "sub", "rg", RESOURCE_ID, [{"instanceId": "0"}, {"instanceId": "2"}]
    ) == {"instance_ids": ["0", "2"]}
    assert calls == [("rg", "set", "0"), ("rg", "set", "2")]


def test_restart_vmss_instances_selects_one_random_instance(monkeypatch):
    calls = []
    client = SimpleNamespace(
        virtual_machine_scale_set_vms=SimpleNamespace(
            list=lambda *_: [SimpleNamespace(instance_id="0"), SimpleNamespace(instance_id="1")],
            begin_restart=lambda *args: calls.append(args) or SimpleNamespace(result=lambda: None),
        )
    )
    monkeypatch.setattr(reboot_actions, "_client", lambda _: client)
    monkeypatch.setattr(reboot_actions.random, "choice", lambda values: values[1])

    assert reboot_actions.restart_instances("sub", "rg", RESOURCE_ID) == {"instance_ids": ["1"]}
    assert calls == [("rg", "set", "1")]


def test_restart_vmss_instances_rejects_empty_scale_sets_and_missing_inputs(monkeypatch):
    client = SimpleNamespace(
        virtual_machine_scale_set_vms=SimpleNamespace(list=lambda *_: [])
    )
    monkeypatch.setattr(reboot_actions, "_client", lambda _: client)

    with pytest.raises(ValueError, match="has no instances"):
        reboot_actions.restart_instances("sub", "rg", RESOURCE_ID)
    with pytest.raises(ValueError, match="subscription_id"):
        reboot_actions.restart_instances("", "rg", RESOURCE_ID)


def test_vmss_reboot_reports_missing_compute_sdk(monkeypatch):
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name == "azure.mgmt.compute":
            raise ImportError("missing SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)

    with pytest.raises(RuntimeError, match="Azure Compute SDK dependencies are unavailable"):
        reboot_actions._client("sub")


def test_vmss_reboot_constructs_compute_client(monkeypatch):
    credential = object()
    client = object()
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: credential))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.compute",
        SimpleNamespace(ComputeManagementClient=lambda actual_credential, subscription: (client, actual_credential, subscription)),
    )

    assert reboot_actions._client("sub") == (client, credential, "sub")
