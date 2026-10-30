from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli.interactive import azure_component_menu as menu
from chaosforge.providers.azure.components import registry


def test_select_rejects_invalid_input(monkeypatch):
    monkeypatch.setattr(menu, "prompt", MagicMock(return_value="bad"))
    monkeypatch.setattr(menu, "menu", MagicMock())
    report = MagicMock()
    monkeypatch.setattr(menu, "error", report)
    assert menu._select([{"id": "id", "name": "name"}], "Target") is None
    report.assert_called_once_with("Invalid Target selection.")


def test_context_requires_login_and_discovers_target(monkeypatch):
    monkeypatch.setattr(menu, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": False})
    monkeypatch.setattr(menu, "error", MagicMock())
    assert menu._context("azure_vm") is None
    discovery = MagicMock()
    discovery.list_resource_groups.return_value = [{"id": "rg", "name": "rg"}]
    monkeypatch.setattr(menu, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"})
    monkeypatch.setattr(menu, "AzureResourceDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(menu, "list_component_resources", lambda *_: [{"id": "/vm", "name": "vm"}])
    monkeypatch.setattr(menu, "_select", MagicMock(side_effect=["rg", "/vm"]))
    assert menu._context("azure_vm") == ("sub", "rg", "/vm")

    monkeypatch.setattr(menu, "_select", MagicMock(side_effect=[None]))
    assert menu._context("azure_vm") is None
    monkeypatch.setattr(menu, "_select", MagicMock(side_effect=["rg", None]))
    assert menu._context("azure_vm") is None
    monkeypatch.setattr(menu, "_select", MagicMock(return_value="rg"))
    monkeypatch.setattr(menu, "list_component_resources", MagicMock(side_effect=RuntimeError("no access")))
    assert menu._context("azure_vm") is None


def test_identity_setup_and_menu_build(monkeypatch):
    identity_service = MagicMock()
    identity_service.list_identities.return_value = []
    identity_service.bootstrap.return_value = {"status": "ready", "identity": {"id": "/identity"}}
    monkeypatch.setattr(menu, "AzureChaosIdentityService", MagicMock(return_value=identity_service))
    monkeypatch.setattr(menu, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(menu, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))
    monkeypatch.setattr(menu, "prompt", MagicMock(return_value="y"))
    assert menu._identity("azure_vm", "azure-vm-redeploy", "sub", "rg", "/vm") == "/identity"

    metadata = {"id": "azure-vm-redeploy", "name": "Redeploy", "inputs": []}
    monkeypatch.setattr(menu, "get_experiments", lambda _: [metadata])
    monkeypatch.setattr(menu, "present_experiment", lambda *_: {"name": "Redeploy"})
    monkeypatch.setattr(menu, "rich_engine_label", lambda _: "")
    monkeypatch.setattr(menu, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(menu, "_context", lambda _: ("sub", "rg", "/vm"))
    monkeypatch.setattr(menu, "_identity", lambda *_: "/identity")
    build = MagicMock(return_value=SimpleNamespace(name="Redeploy"))
    monkeypatch.setattr(menu, "build_experiment", build)
    monkeypatch.setattr(menu, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(menu, "menu", MagicMock())
    monkeypatch.setattr(menu, "section", MagicMock())
    monkeypatch.setattr(menu, "console", MagicMock())
    menu.azure_component_experiment_menu("azure_vm")
    assert build.call_args.args[2]["resource_id"] == "/vm"

    monkeypatch.setattr(menu, "_context", lambda _: None)
    monkeypatch.setattr(menu, "prompt", MagicMock(side_effect=["1", "0"]))
    menu.azure_component_experiment_menu("azure_vm")


def test_component_menu_navigation(monkeypatch):
    monkeypatch.setattr(menu, "get_experiments", lambda _: [])
    monkeypatch.setattr(menu, "menu", MagicMock())
    monkeypatch.setattr(menu, "section", MagicMock())
    monkeypatch.setattr(menu, "prompt", MagicMock(return_value="m"))
    with pytest.raises(menu.BackToMainMenu):
        menu.azure_component_experiment_menu("azure_vm")


def test_context_and_identity_report_discovery_and_readiness_failures(monkeypatch):
    menu.context.azure_subscription = None
    monkeypatch.setattr(menu, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(menu, "error", report := MagicMock())
    assert menu._context("azure_vm") is None
    report.assert_called_once_with("Log in to Azure before selecting an Azure target.")

    monkeypatch.setattr(menu, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"})
    monkeypatch.setattr(menu, "AzureResourceDiscovery", MagicMock())
    monkeypatch.setattr(menu, "_select", MagicMock(side_effect=RuntimeError("denied")))
    assert menu._context("azure_vm") is None
    assert "Could not discover Azure resources: denied" in report.call_args.args[0]

    identity_service = MagicMock()
    identity_service.list_identities.return_value = [{"id": "/identity", "name": "identity"}]
    identity_service.readiness.return_value = {"status": "missing_role", "message": "grant access"}
    monkeypatch.setattr(menu, "AzureChaosIdentityService", MagicMock(return_value=identity_service))
    monkeypatch.setattr(menu, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(menu, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))
    monkeypatch.setattr(menu, "info", report)
    assert menu._identity("azure_vm", "fault", "sub", "rg", "/vm") == "/identity"
    assert "grant access" in report.call_args.args[0]


def test_identity_declines_setup_and_menu_recovers_from_invalid_choice(monkeypatch):
    identity_service = MagicMock()
    identity_service.list_identities.return_value = []
    monkeypatch.setattr(menu, "AzureChaosIdentityService", MagicMock(return_value=identity_service))
    monkeypatch.setattr(menu, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(menu, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))
    monkeypatch.setattr(menu, "prompt", MagicMock(return_value="n"))
    assert menu._identity("azure_vm", "fault", "sub", "rg", "/vm") is None

    monkeypatch.setattr(menu, "get_experiments", lambda _: [])
    monkeypatch.setattr(menu, "menu", MagicMock())
    monkeypatch.setattr(menu, "section", MagicMock())
    monkeypatch.setattr(menu, "error", report := MagicMock())
    monkeypatch.setattr(menu, "prompt", MagicMock(side_effect=["bad", "0"]))
    menu.azure_component_experiment_menu("azure_vm")
    report.assert_called_once_with("Invalid Selection")


def test_component_menu_recovers_from_missing_identity_and_collects_metadata_fields(monkeypatch):
    metadata = {
        "id": "azure-vm-shutdown",
        "name": "Shutdown",
        "inputs": [{"name": "duration", "label": "Duration", "default": "PT5M"}],
    }
    monkeypatch.setattr(menu, "get_experiments", lambda _: [metadata])
    monkeypatch.setattr(menu, "present_experiment", lambda *_: {"name": "Shutdown"})
    monkeypatch.setattr(menu, "rich_engine_label", lambda _: "")
    monkeypatch.setattr(menu, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(menu, "_context", lambda _: ("sub", "rg", "/vm"))
    monkeypatch.setattr(menu, "menu", MagicMock())
    monkeypatch.setattr(menu, "section", MagicMock())
    monkeypatch.setattr(menu, "console", MagicMock())
    monkeypatch.setattr(menu, "_identity", MagicMock(side_effect=[None, "/identity"]))
    build = MagicMock(return_value=SimpleNamespace(name="Shutdown"))
    monkeypatch.setattr(menu, "build_experiment", build)
    monkeypatch.setattr(menu, "prompt", MagicMock(side_effect=["1", "1", ""]))
    menu.azure_component_experiment_menu("azure_vm")
    assert build.call_args.args[2]["duration"] == "PT5M"
    menu.console.print.assert_any_call("[bold cyan]Duration[/bold cyan]")
    menu.console.print.assert_any_call("[bright_black]Default : PT5M[/bright_black]")


def test_component_menu_routes_vm_reboot_sdk_entry_without_chaos_identity(monkeypatch):
    metadata = {"id": "azure-vm-toolkit-reboot", "name": "Reboot", "engine": "Azure SDK", "inputs": []}
    monkeypatch.setattr(menu, "get_experiments", lambda _: [metadata])
    monkeypatch.setattr(menu, "present_experiment", lambda *_: {"name": "Reboot"})
    monkeypatch.setattr(menu, "rich_engine_label", lambda _: "")
    monkeypatch.setattr(menu, "menu", MagicMock())
    monkeypatch.setattr(menu, "section", MagicMock())
    monkeypatch.setattr(menu, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(menu, "_context", lambda _: ("sub", "rg", "/vm"))
    identity = MagicMock()
    monkeypatch.setattr(menu, "_identity", identity)
    build = MagicMock(return_value=SimpleNamespace(name="Reboot"))
    monkeypatch.setattr(menu, "build_experiment", build)
    monkeypatch.setattr(menu, "console", MagicMock())
    monkeypatch.setattr(menu, "prompt", MagicMock(return_value="1"))
    menu.azure_component_experiment_menu("azure_vm")
    identity.assert_not_called()
    assert build.call_args.args[2] == {
        "subscription_id": "sub", "resource_group": "rg", "resource_id": "/vm"
    }


def test_component_menu_builds_sdk_experiment_without_chaos_identity(monkeypatch):
    metadata = {
        "id": "azure-redis-flush",
        "name": "Flush Cache",
        "engine": "Azure SDK",
        "inputs": [
            {"name": "resource_id", "label": "Redis Cache", "type": "azure_component_resource"},
            {"name": "confirm", "label": "Confirm", "default": "yes"},
        ],
    }
    monkeypatch.setattr(menu, "get_experiments", lambda _: [metadata])
    monkeypatch.setattr(menu, "present_experiment", lambda *_: {"name": "Flush Cache"})
    monkeypatch.setattr(menu, "rich_engine_label", lambda _: "")
    monkeypatch.setattr(menu, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(menu, "_context", lambda _: ("sub", "rg", "/redis"))
    identity = MagicMock()
    monkeypatch.setattr(menu, "_identity", identity)
    monkeypatch.setattr(menu, "menu", MagicMock())
    monkeypatch.setattr(menu, "section", MagicMock())
    monkeypatch.setattr(menu, "console", MagicMock())
    build = MagicMock(return_value=SimpleNamespace(name="Flush Cache"))
    monkeypatch.setattr(menu, "build_experiment", build)
    monkeypatch.setattr(menu, "prompt", MagicMock(side_effect=["1", ""]))

    menu.azure_component_experiment_menu("azure_redis")

    identity.assert_not_called()
    assert build.call_args.args[2] == {
        "subscription_id": "sub", "resource_group": "rg", "resource_id": "/redis", "confirm": "yes",
    }


def test_component_menu_skips_prepopulated_inputs_after_identity_retry(monkeypatch):
    metadata = {
        "id": "azure-vm-shutdown",
        "name": "Shutdown",
        "inputs": [
            {"name": "resource_id", "label": "Virtual Machine"},
            {"name": "chaos_identity_id", "label": "Azure Chaos Identity"},
            {"name": "duration", "label": "Duration", "default": "PT5M"},
        ],
    }
    monkeypatch.setattr(menu, "get_experiments", lambda _: [metadata])
    monkeypatch.setattr(menu, "present_experiment", lambda *_: {"name": "Shutdown"})
    monkeypatch.setattr(menu, "rich_engine_label", lambda _: "")
    monkeypatch.setattr(menu, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(menu, "_context", lambda _: ("sub", "rg", "/vm"))
    monkeypatch.setattr(menu, "_identity", MagicMock(side_effect=[None, "/identity"]))
    monkeypatch.setattr(menu, "menu", MagicMock())
    monkeypatch.setattr(menu, "section", MagicMock())
    monkeypatch.setattr(menu, "console", MagicMock())
    build = MagicMock(return_value=SimpleNamespace(name="Shutdown"))
    monkeypatch.setattr(menu, "build_experiment", build)
    prompts = MagicMock(side_effect=["1", "1", "PT1M"])
    monkeypatch.setattr(menu, "prompt", prompts)

    menu.azure_component_experiment_menu("azure_vm")

    assert build.call_args.args[2] == {
        "subscription_id": "sub",
        "resource_group": "rg",
        "resource_id": "/vm",
        "chaos_identity_id": "/identity",
        "duration": "PT1M",
    }
    assert prompts.call_count == 3


def test_identity_handles_discovery_bootstrap_and_ready_identity_paths(monkeypatch):
    menu.context.azure_subscription = None
    report = MagicMock()
    identity_service = MagicMock()
    monkeypatch.setattr(menu, "AzureChaosIdentityService", MagicMock(return_value=identity_service))
    monkeypatch.setattr(menu, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(menu, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))
    monkeypatch.setattr(menu, "error", report)
    monkeypatch.setattr(menu, "info", report)
    identity_service.list_identities.side_effect = RuntimeError("denied")
    assert menu._identity("azure_vm", "fault", "sub", "rg", "/vm") is None
    report.assert_called_with("Could not discover chaosforge-managed-identity: denied")

    identity_service.list_identities.side_effect = None
    identity_service.list_identities.return_value = []
    identity_service.bootstrap.side_effect = RuntimeError("bootstrap denied")
    monkeypatch.setattr(menu, "prompt", MagicMock(return_value="y"))
    assert menu._identity("azure_vm", "fault", "sub", "rg", "/vm") is None
    report.assert_called_with("bootstrap denied")

    identity_service.bootstrap.side_effect = None
    identity_service.bootstrap.return_value = {"status": "blocked", "message": "not ready"}
    assert menu._identity("azure_vm", "fault", "sub", "rg", "/vm") is None
    report.assert_called_with("not ready")

    identity_service.list_identities.return_value = [{"id": "/identity", "name": "identity"}]
    identity_service.readiness.return_value = {"status": "missing_role", "message": "grant role"}
    assert menu._identity("azure_vm", "fault", "sub", "rg", "/vm") == "/identity"
    assert "grant role" in report.call_args.args[0]

    identity_service.readiness.return_value = {"status": "ready"}
    assert menu._identity("azure_vm", "fault", "sub", "rg", "/vm") == "/identity"
    assert menu.context.azure_subscription is None


def test_component_registry_dispatches_and_rejects_unknown_service():
    discovery = MagicMock()
    discovery.list_virtual_machines.return_value = [{"id": "/vm", "name": "vm"}]
    assert registry.list_component_resources(discovery, "azure_vm", "rg") == [{"id": "/vm", "name": "vm"}]
    discovery.list_virtual_machines.assert_called_once_with("rg")
    with pytest.raises(ValueError, match="Unsupported Azure component"):
        registry.list_component_resources(discovery, "unknown", "rg")
