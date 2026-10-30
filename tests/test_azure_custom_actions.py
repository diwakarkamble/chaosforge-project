import builtins
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from chaoslib.experiment import ensure_experiment_is_valid

from chaosforge.application.campaigns.factory import create_experiment
from chaosforge.providers.azure.components.azure_cosmos_db.experiments.custom.actions import (
    public_access_actions as cosmos,
)
from chaosforge.providers.azure.components.azure_key_vault.experiments.custom.actions import (
    secret_actions,
)
from chaosforge.providers.azure.components.azure_vmss.experiments.custom.actions import (
    overprovision_actions,
)


def test_cosmos_public_access_restores_saved_value(monkeypatch, tmp_path):
    monkeypatch.setattr(cosmos, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    updates = []
    client = SimpleNamespace(database_accounts=SimpleNamespace(
        get=lambda *_: SimpleNamespace(public_network_access="Enabled"),
        begin_update=lambda *args: updates.append(args) or SimpleNamespace(result=lambda: "updated"),
    ))
    monkeypatch.setattr(cosmos, "_client", lambda _: client)
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/account"
    assert cosmos.disable_public_access("sub", "rg", resource_id) == "updated"
    assert cosmos.restore_public_access("sub", "rg", resource_id) == "updated"
    assert updates == [
        ("rg", "account", {"properties": {"publicNetworkAccess": "Disabled"}}),
        ("rg", "account", {"properties": {"publicNetworkAccess": "Enabled"}}),
    ]
    assert not cosmos._path("sub", "rg", "account").exists()


def test_secret_disable_restores_original_enabled_value(monkeypatch, tmp_path):
    monkeypatch.setattr(secret_actions, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    calls = []
    vault_urls = []
    secret = SimpleNamespace(properties=SimpleNamespace(enabled=True, version="v1"))
    client = SimpleNamespace(get_secret=lambda _: secret, update_secret_properties=lambda *args, **kwargs: calls.append((args, kwargs)) or "updated")
    monkeypatch.setattr(secret_actions, "_client", lambda vault_url: vault_urls.append(vault_url) or client)
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/vault"
    secret_actions.disable_secret(resource_id, "secret")
    assert secret_actions.restore_secret(resource_id, "secret") == "updated"
    assert calls[-1] == (("secret", "v1"), {"enabled": True})
    assert vault_urls == ["https://vault.vault.azure.net", "https://vault.vault.azure.net"]


def test_secret_rollback_does_not_read_the_disabled_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(secret_actions, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    update = MagicMock(return_value="updated")
    client = SimpleNamespace(
        get_secret=lambda _: (_ for _ in ()).throw(AssertionError("disabled secret must not be read")),
        update_secret_properties=update,
    )
    monkeypatch.setattr(secret_actions, "_client", lambda _: client)
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/vault"
    path = secret_actions._state_path("https://vault.vault.azure.net", "secret")
    path.write_text('{"enabled":true,"version":"v1"}', encoding="utf-8")

    assert secret_actions.restore_secret(resource_id, "secret") == "updated"
    update.assert_called_once_with("secret", "v1", enabled=True)


def test_key_vault_client_uses_an_explicit_enterprise_ca_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "enterprise-ca.pem"
    bundle.write_text("certificate", encoding="utf-8")
    credential = object()
    transport = object()
    client = object()
    constructor = MagicMock(return_value=client)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: credential))
    monkeypatch.setitem(
        sys.modules,
        "azure.core.pipeline.transport",
        SimpleNamespace(RequestsTransport=lambda **kwargs: transport),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.keyvault.secrets",
        SimpleNamespace(SecretClient=constructor),
    )
    monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(SSLContext=MagicMock()))

    assert secret_actions._client("https://vault.vault.azure.net") is client
    constructor.assert_called_once_with(
        vault_url="https://vault.vault.azure.net", credential=credential, transport=transport
    )


def test_key_vault_client_uses_the_system_trust_store_when_no_bundle_is_configured(monkeypatch):
    credential = object()
    context = object()
    session = SimpleNamespace(mount=MagicMock())
    transport = object()
    client = object()
    constructor = MagicMock(return_value=client)

    class Adapter:
        def proxy_manager_for(self, proxy, **kwargs):
            return proxy, kwargs
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: credential))
    monkeypatch.setitem(
        sys.modules,
        "azure.core.pipeline.transport",
        SimpleNamespace(RequestsTransport=lambda **kwargs: transport),
    )
    monkeypatch.setitem(sys.modules, "azure.keyvault.secrets", SimpleNamespace(SecretClient=constructor))
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(Session=lambda: session))
    monkeypatch.setitem(sys.modules, "requests.adapters", SimpleNamespace(HTTPAdapter=Adapter))
    monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(SSLContext=lambda _: context))

    assert secret_actions._client("https://vault.vault.azure.net") is client
    session.mount.assert_called_once()
    adapter = session.mount.call_args.args[1]
    assert adapter.proxy_manager_for("https://proxy.example") == (
        "https://proxy.example",
        {"ssl_context": context},
    )


def test_key_vault_client_rejects_a_missing_enterprise_ca_bundle(monkeypatch):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/missing/enterprise-ca.pem")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    with pytest.raises(RuntimeError, match="CA bundle was not found"):
        secret_actions._client("https://vault.vault.azure.net")


def test_key_vault_client_identifies_a_missing_sdk_dependency(monkeypatch):
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name == "azure.keyvault.secrets":
            error = ImportError("missing SDK")
            error.name = name
            raise error
        return original_import(name, *args, **kwargs)

    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setitem(sys.modules, "truststore", SimpleNamespace(SSLContext=MagicMock()))
    monkeypatch.setattr(builtins, "__import__", missing_sdk)

    with pytest.raises(RuntimeError, match="azure.keyvault.secrets"):
        secret_actions._client("https://vault.vault.azure.net")


def test_vmss_overprovision_restores_saved_value(monkeypatch, tmp_path):
    monkeypatch.setattr(overprovision_actions, "repository_paths", lambda: SimpleNamespace(runtime=tmp_path))
    calls = []
    client = SimpleNamespace(virtual_machine_scale_sets=SimpleNamespace(
        get=lambda *_: SimpleNamespace(overprovision=True),
        begin_update=lambda *args: calls.append(args) or SimpleNamespace(result=lambda: "updated"),
    ))
    monkeypatch.setattr(overprovision_actions, "_client", lambda _: client)
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/set"
    overprovision_actions.disable_overprovision("sub", "rg", resource_id)
    assert overprovision_actions.restore_overprovision("sub", "rg", resource_id) == "updated"
    assert calls[-1][-1] == {"properties": {"overprovision": True}}


def test_vmss_reboot_keeps_the_selected_resource_without_a_resource_graph_filter():
    metadata = {
        "id": "azure-vmss-toolkit-reboot",
        "name": "Reboot",
        "engine": "Azure SDK",
        "json": "azure-vm-reboot.json",
        "inputs": [{"name": "resource_id", "type": "azure_component_resource"}],
    }
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/vmss"

    experiment = create_experiment("azure_vmss", metadata, {"resource_id": resource_id})

    assert experiment.variables == {
        "resource_id": resource_id,
        "experiment_id": "azure-vmss-toolkit-reboot",
    }


def test_vmss_toolkit_reboot_converts_selected_instance_ids_to_toolkit_criteria():
    metadata = {
        "id": "azure-vmss-toolkit-reboot",
        "name": "Reboot",
        "engine": "Chaos Toolkit",
        "json": "azure-vmss-reboot.json",
        "inputs": [
            {"name": "resource_id", "type": "azure_component_resource"},
            {"name": "instance_criteria", "type": "azure_vmss_instances"},
        ],
    }
    experiment = create_experiment(
        "azure_vmss",
        metadata,
        {"resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/vmss", "instance_criteria": '["0", "2"]'},
    )

    assert experiment.variables["instance_criteria"] == [
        {"instanceId": "0"},
        {"instanceId": "2"},
    ]


def test_vmss_sdk_reboot_definition_accepts_optional_instance_criteria():
    definition = json.loads(
        (Path(__file__).parents[1] / "chaosforge/providers/azure/components/azure_vmss/experiments/custom/definitions/azure-vmss-reboot.json").read_text(
            encoding="utf-8"
        )
    )

    arguments = definition["method"][0]["provider"]["arguments"]
    assert arguments["instance_criteria"] == "${instance_criteria}"
    assert arguments["subscription_id"] == "${subscription_id}"


def test_vmss_shutdown_uses_the_instance_checkbox_picker():
    metadata = json.loads(
        (Path(__file__).parents[1] / "chaosforge/providers/azure/components/azure_vmss/experiments/metadata.json").read_text(
            encoding="utf-8"
        )
    )
    experiment = next(item for item in metadata["experiments"] if item["id"] == "azure-vmss-shutdown")

    assert next(field for field in experiment["inputs"] if field["name"] == "instances")["type"] == "azure_vmss_instances"


@pytest.mark.parametrize("component, experiment_id", [
    ("azure_postgres_flexible", "azure-postgres-flexible-restart"),
    ("azure_postgres_flexible", "azure-postgres-flexible-firewall-disruption"),
    ("azure_container_apps", "azure-container-app-revision-restart"),
    ("azure_container_apps", "azure-container-app-traffic-shift"),
    ("azure_container_apps", "azure-container-app-scale-zero"),
    ("azure_app_service", "azure-app-service-slot-swap"),
    ("azure_functions", "azure-functions-slot-swap"),
    ("azure_key_vault", "azure-key-vault-secret-disable"),
    ("azure_cosmos_db", "azure-cosmos-db-public-access-disruption"),
    ("azure_event_hub", "azure-event-hub-public-access-disruption"),
    ("azure_vm", "azure-vm-boot-diagnostics-toggle"),
    ("azure_vmss", "azure-vmss-overprovision-toggle"),
])
def test_custom_experiment_metadata_resolves_to_definition(component, experiment_id):
    root = Path(__file__).parents[1] / "chaosforge/providers/azure/components" / component / "experiments"
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    experiment = next(item for item in metadata["experiments"] if item["id"] == experiment_id)
    definition = json.loads((root / experiment["json"]).read_text(encoding="utf-8"))
    assert experiment["engine"] == "Azure SDK"
    assert definition["method"]
    ensure_experiment_is_valid(definition)
    if "restart" not in experiment_id:
        assert definition["rollbacks"]
    selector = next(item for item in experiment["inputs"] if item["name"] == "resource_id")
    assert selector["type"] == "azure_component_resource"
    assert "resource_id" in definition["configuration"]
    for action in definition["method"] + definition.get("rollbacks", []):
        arguments = action["provider"]["arguments"]
        if "resource_id" in arguments:
            assert arguments["resource_id"] == "${resource_id}"


def test_azure_component_experiment_names_are_unique():
    root = Path(__file__).parents[1] / "chaosforge/providers/azure/components"

    for metadata_path in root.glob("*/experiments/metadata.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        names = [experiment["name"] for experiment in metadata["experiments"]]

        assert len(names) == len(set(names)), metadata_path


def test_app_service_catalog_exposes_only_the_state_preserving_stop_experiment():
    metadata_path = (
        Path(__file__).parents[1]
        / "chaosforge/providers/azure/components/azure_app_service/experiments/metadata.json"
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    stops = [experiment for experiment in metadata["experiments"] if experiment["name"] == "Stop App Service"]

    assert [experiment["id"] for experiment in stops] == ["azure-app-service-toolkit-stop"]
    assert stops[0]["engine"] == "Azure SDK"


@pytest.mark.parametrize(
    ("component", "experiment_id"),
    [
        ("azure_redis", "azure-redis-access-disruption"),
        ("azure_cosmos_db", "azure-cosmos-db-public-access-disruption"),
        ("azure_event_hub", "azure-event-hub-public-access-disruption"),
        ("azure_key_vault", "azure-key-vault-secret-disable"),
        ("azure_vm", "azure-vm-boot-diagnostics-toggle"),
        ("azure_vmss", "azure-vmss-overprovision-toggle"),
        ("azure_app_service", "azure-app-service-slot-swap"),
        ("azure_functions", "azure-functions-slot-swap"),
        ("azure_container_apps", "azure-container-app-traffic-shift"),
        ("azure_container_apps", "azure-container-app-scale-zero"),
        ("azure_postgres_flexible", "azure-postgres-flexible-firewall-disruption"),
    ],
)
def test_reversible_azure_sdk_disruptions_hold_before_rollback(component, experiment_id):
    root = Path(__file__).parents[1] / "chaosforge/providers/azure/components" / component / "experiments"
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    experiment = next(item for item in metadata["experiments"] if item["id"] == experiment_id)
    definition = json.loads((root / experiment["json"]).read_text(encoding="utf-8"))

    assert any(field["name"] == "duration_seconds" for field in experiment["inputs"])
    assert definition["configuration"]["duration_seconds"] == 300
    assert any(action["provider"]["func"] == "wait_for_duration" for action in definition["method"])
