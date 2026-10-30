import builtins
import sys
from types import SimpleNamespace

import pytest

from chaosforge.providers.azure.components.azure_vm.experiments.custom.actions import (
    reboot_actions,
)

RESOURCE_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"


def test_restart_virtual_machine_uses_the_selected_vm(monkeypatch):
    calls = []
    client = SimpleNamespace(
        virtual_machines=SimpleNamespace(
            begin_restart=lambda *args: calls.append(args) or SimpleNamespace(result=lambda: "restarted")
        )
    )
    monkeypatch.setattr(reboot_actions, "_client", lambda _: client)

    assert reboot_actions.restart_virtual_machine("sub", "rg", RESOURCE_ID) == "restarted"
    assert calls == [("rg", "vm")]


def test_restart_virtual_machine_requires_all_inputs():
    with pytest.raises(ValueError, match="subscription_id"):
        reboot_actions.restart_virtual_machine("", "rg", RESOURCE_ID)


def test_vm_reboot_reports_missing_compute_sdk(monkeypatch):
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name == "azure.mgmt.compute":
            raise ImportError("missing SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)

    with pytest.raises(RuntimeError, match="Azure Compute SDK dependencies are unavailable"):
        reboot_actions._client("sub")


def test_vm_reboot_constructs_compute_client(monkeypatch):
    credential = object()
    client = object()
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: credential))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.compute",
        SimpleNamespace(ComputeManagementClient=lambda actual_credential, subscription: (client, actual_credential, subscription)),
    )

    assert reboot_actions._client("sub") == (client, credential, "sub")
