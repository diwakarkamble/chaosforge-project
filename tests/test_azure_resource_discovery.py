import subprocess
import sys
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from chaosforge.common.azure_cli import azure_cli_command
from chaosforge.providers.azure.discovery import AzureResourceDiscovery, resolve_subscription_id

SUBSCRIPTION_ID = "12345678-1234-1234-1234-123456789abc"


def _completed(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_azure_discovery_requires_subscription_id():
    with pytest.raises(ValueError, match="subscription ID"):
        AzureResourceDiscovery("")


@pytest.mark.parametrize("value", ["", "  "])
def test_azure_discovery_requires_nonblank_subscription_id(value):
    with pytest.raises(ValueError, match="subscription ID"):
        AzureResourceDiscovery(value)


def test_vmss_instance_discovery_uses_sdk_instance_ids(monkeypatch):
    compute = SimpleNamespace(
        virtual_machine_scale_set_vms=SimpleNamespace(
            list=lambda *_: [SimpleNamespace(instance_id="0"), SimpleNamespace(instance_id="1")]
        )
    )
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.compute",
        SimpleNamespace(ComputeManagementClient=lambda *_: compute),
    )

    assert AzureResourceDiscovery(SUBSCRIPTION_ID).list_virtual_machine_scale_set_instances(
        "rg", "scale-set"
    ) == [
        {"id": "0", "name": "Instance 0"},
        {"id": "1", "name": "Instance 1"},
    ]


@pytest.mark.parametrize("resource_group, scale_set_name", [("", "scale-set"), ("rg", "")])
def test_vmss_instance_discovery_requires_a_resource_group_and_scale_set(
    resource_group, scale_set_name
):
    with pytest.raises(ValueError, match="resource group and virtual machine scale set"):
        AzureResourceDiscovery(SUBSCRIPTION_ID).list_virtual_machine_scale_set_instances(
            resource_group, scale_set_name
        )


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (_completed(stdout="[0, 1]"), [{"id": "0", "name": "Instance 0"}, {"id": "1", "name": "Instance 1"}]),
        (_completed(returncode=1, stderr="denied"), "denied"),
        (_completed(stdout="not-json"), "invalid virtual machine scale set instance list"),
        (_completed(stdout="{}"), "invalid virtual machine scale set instance list"),
    ],
)
def test_vmss_instance_discovery_falls_back_to_cli_and_reports_errors(
    monkeypatch, completed, expected
):
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.compute",
        SimpleNamespace(ComputeManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))),
    )
    with patch("chaosforge.providers.azure.discovery.subprocess.run", return_value=completed) as run:
        if isinstance(expected, str):
            with pytest.raises(RuntimeError, match=expected):
                AzureResourceDiscovery("sub").list_virtual_machine_scale_set_instances("rg", "scale-set")
        else:
            assert AzureResourceDiscovery("sub").list_virtual_machine_scale_set_instances(
                "rg", "scale-set"
            ) == expected
            assert run.call_args.args[0] == azure_cli_command(
                "vmss", "list-instances", "--resource-group", "rg", "--name", "scale-set",
                "--subscription", "sub", "--query", "[].instanceId", "--output", "json",
            )


def test_vmss_instance_discovery_reports_when_cli_is_unavailable(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.compute",
        SimpleNamespace(ComputeManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))),
    )
    with patch("chaosforge.providers.azure.discovery.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Azure SDK or Azure CLI"):
            AzureResourceDiscovery("sub").list_virtual_machine_scale_set_instances("rg", "scale-set")


def test_resolve_subscription_id_returns_valid_input_without_cli():
    with patch("chaosforge.providers.azure.discovery.subprocess.run") as run:
        result = resolve_subscription_id(f"  {SUBSCRIPTION_ID.upper()}  ")

    assert result == SUBSCRIPTION_ID.upper()
    run.assert_not_called()


def test_resolve_subscription_id_returns_valid_account_id_without_cli():
    with patch("chaosforge.providers.azure.discovery.subprocess.run") as run:
        result = resolve_subscription_id("friendly-name", account={"id": f" {SUBSCRIPTION_ID} "})

    assert result == SUBSCRIPTION_ID
    run.assert_not_called()


def test_resolve_subscription_id_uses_windows_azure_cli_entry_point(monkeypatch):
    completed = CompletedProcess(
        args=[], returncode=0, stdout=f'{{"id": "{SUBSCRIPTION_ID}"}}', stderr=""
    )
    monkeypatch.setattr("chaosforge.common.azure_cli.os.name", "nt")
    with patch("chaosforge.providers.azure.discovery.subprocess.run", return_value=completed) as run:
        assert resolve_subscription_id() == SUBSCRIPTION_ID

    assert run.call_args.args[0][0] == "az.cmd"


def test_azure_cli_command_uses_windows_entry_point(monkeypatch):
    monkeypatch.setattr("chaosforge.common.azure_cli.os.name", "nt")

    assert azure_cli_command("account", "show") == ["az.cmd", "account", "show"]


def test_resolve_subscription_id_uses_cli_for_subscription_name():
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        return_value=_completed(stdout=f'{{"id": "{SUBSCRIPTION_ID}"}}'),
    ) as run:
        result = resolve_subscription_id("friendly-name", account={"id": "not-a-uuid"})

    assert result == SUBSCRIPTION_ID
    run.assert_called_once_with(
        azure_cli_command("account", "show", "--subscription", "friendly-name", "--output", "json"),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def test_resolve_subscription_id_uses_active_account_when_value_is_blank():
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        return_value=_completed(stdout=f'{{"id": "{SUBSCRIPTION_ID}"}}'),
    ) as run:
        result = resolve_subscription_id()

    assert result == SUBSCRIPTION_ID
    assert run.call_args.args[0] == azure_cli_command("account", "show", "--output", "json")


def test_resolve_subscription_id_reports_missing_azure_cli():
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        with pytest.raises(RuntimeError, match=r"Azure CLI \('az'\) is required"):
            resolve_subscription_id()


def test_resolve_subscription_id_reports_cli_execution_error():
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        side_effect=subprocess.TimeoutExpired("az", 15),
    ):
        with pytest.raises(RuntimeError, match="Could not resolve Azure subscription"):
            resolve_subscription_id()


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (_completed(returncode=1, stderr="not authorized"), "not authorized"),
        (_completed(returncode=1), "active subscription"),
    ],
)
def test_resolve_subscription_id_reports_cli_failure(completed, message):
    with patch("chaosforge.providers.azure.discovery.subprocess.run", return_value=completed):
        with pytest.raises(RuntimeError, match=message):
            resolve_subscription_id()


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        "[]",
        "{}",
        '{"id": "not-a-uuid"}',
    ],
)
def test_resolve_subscription_id_rejects_invalid_cli_account_response(stdout):
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        return_value=_completed(stdout=stdout),
    ):
        with pytest.raises(RuntimeError, match="did not contain a valid subscription ID"):
            resolve_subscription_id()


def test_azure_discovery_lists_resource_groups_and_redis_caches(monkeypatch):
    resource_client = SimpleNamespace(
        resource_groups=SimpleNamespace(
            list=lambda: [SimpleNamespace(name="rg-a"), SimpleNamespace(name="")]
        )
    )
    redis_client = SimpleNamespace(
        redis=SimpleNamespace(
            list_by_resource_group=lambda group: [SimpleNamespace(name="cache-a"), SimpleNamespace(name="")]
        )
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.identity",
        SimpleNamespace(DefaultAzureCredential=lambda: "credential"),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.resource",
        SimpleNamespace(ResourceManagementClient=lambda *_: resource_client),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.redis",
        SimpleNamespace(RedisManagementClient=lambda *_: redis_client),
    )

    discovery = AzureResourceDiscovery("sub")
    assert discovery.list_resource_groups() == [{"id": "rg-a", "name": "rg-a"}]
    assert discovery.list_redis_caches("rg-a") == [{"id": "cache-a", "name": "cache-a"}]


def test_azure_discovery_requires_resource_group():
    with pytest.raises(ValueError, match="resource group"):
        AzureResourceDiscovery("sub").list_redis_caches("")


def test_aks_cluster_names_require_group_and_parse_cli_result():
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        return_value=_completed(stdout='["aks-a"]'),
    ) as run:
        discovery = AzureResourceDiscovery("sub")
        assert discovery.list_aks_cluster_names("") == []
        assert discovery.list_aks_cluster_names("rg-a") == ["aks-a"]

    assert run.call_args.args[0] == azure_cli_command(
        "aks", "list", "--resource-group", "rg-a", "--subscription", "sub",
        "--query", "[].name", "--output", "json",
    )


def test_azure_discovery_falls_back_to_azure_cli_for_resource_groups(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "azure.identity",
        SimpleNamespace(DefaultAzureCredential=lambda: "credential"),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.resource",
        SimpleNamespace(ResourceManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))),
    )
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        return_value=_completed(stdout='["rg-a", ""]'),
    ) as run:
        result = AzureResourceDiscovery("sub").list_resource_groups()

    assert result == [{"id": "rg-a", "name": "rg-a"}]
    assert run.call_args.args[0] == azure_cli_command(
        "group", "list", "--subscription", "sub", "--query", "[].name", "--output", "json"
    )


def test_azure_resource_group_cli_fallback_reports_unavailable_cli(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.resource",
        SimpleNamespace(ResourceManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))),
    )
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        with pytest.raises(RuntimeError, match="Azure SDK or Azure CLI"):
            AzureResourceDiscovery("sub").list_resource_groups()


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (_completed(returncode=1, stderr="access denied"), "access denied"),
        (_completed(stdout="not-json"), "invalid resource group list"),
        (_completed(stdout="{}"), "invalid resource group list"),
    ],
)
def test_azure_resource_group_cli_fallback_reports_invalid_results(monkeypatch, completed, message):
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.resource",
        SimpleNamespace(ResourceManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))),
    )
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        return_value=completed,
    ):
        with pytest.raises(RuntimeError, match=message):
            AzureResourceDiscovery("sub").list_resource_groups()


def test_component_discovery_uses_sdk_and_returns_arm_ids(monkeypatch):
    compute_client = SimpleNamespace(
        virtual_machines=SimpleNamespace(
            list=lambda group: [
                SimpleNamespace(name="vm-b", id="/subscriptions/sub/resourceGroups/rg-a/providers/Microsoft.Compute/virtualMachines/vm-b"),
                SimpleNamespace(name="vm-a", id="/subscriptions/sub/resourceGroups/rg-a/providers/Microsoft.Compute/virtualMachines/vm-a"),
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: "credential"))
    monkeypatch.setitem(
        sys.modules, "azure.mgmt.compute", SimpleNamespace(ComputeManagementClient=lambda *_: compute_client)
    )

    assert AzureResourceDiscovery("sub").list_virtual_machines("rg-a") == [
        {"id": "/subscriptions/sub/resourceGroups/rg-a/providers/Microsoft.Compute/virtualMachines/vm-a", "name": "vm-a"},
        {"id": "/subscriptions/sub/resourceGroups/rg-a/providers/Microsoft.Compute/virtualMachines/vm-b", "name": "vm-b"},
    ]


def test_component_discovery_falls_back_to_cli_and_filters_function_apps(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.mgmt.web", SimpleNamespace(
        WebSiteManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))
    ))
    with patch(
        "chaosforge.providers.azure.discovery.subprocess.run",
        return_value=_completed(stdout='[{"id":"/web","name":"web","kind":"app"},{"id":"/func","name":"func","kind":"functionapp,linux"}]'),
    ) as run:
        discovery = AzureResourceDiscovery("sub")
        assert discovery.list_web_apps("rg-a") == [{"id": "/web", "name": "web"}]
        assert discovery.list_function_apps("rg-a") == [{"id": "/func", "name": "func"}]

    assert run.call_args.args[0] == azure_cli_command(
        "webapp", "list", "--resource-group", "rg-a", "--subscription", "sub", "--output", "json"
    )


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (_completed(returncode=1, stderr="denied"), "denied"),
        (_completed(stdout="not-json"), "invalid virtual machines list"),
        (_completed(stdout="{}"), "invalid virtual machines list"),
    ],
)
def test_component_discovery_cli_fallback_errors(monkeypatch, completed, message):
    monkeypatch.setitem(sys.modules, "azure.mgmt.compute", SimpleNamespace(ComputeManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))))
    with patch("chaosforge.providers.azure.discovery.subprocess.run", return_value=completed):
        with pytest.raises(RuntimeError, match=message):
            AzureResourceDiscovery("sub").list_virtual_machines("rg")


def test_component_discovery_cli_fallback_handles_missing_cli(monkeypatch):
    monkeypatch.setitem(sys.modules, "azure.mgmt.compute", SimpleNamespace(ComputeManagementClient=lambda *_: (_ for _ in ()).throw(RuntimeError("sdk"))))
    with patch("chaosforge.providers.azure.discovery.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Azure SDK or Azure CLI"):
            AzureResourceDiscovery("sub").list_virtual_machines("rg")


@pytest.mark.parametrize(
    "method",
    [
        "list_virtual_machine_scale_sets",
        "list_web_apps",
        "list_function_apps",
        "list_key_vaults",
        "list_cosmos_db_accounts",
        "list_event_hub_namespaces",
        "list_postgresql_flexible_servers",
        "list_container_apps",
    ],
)
def test_component_discovery_requires_resource_group(method):
    with pytest.raises(ValueError, match="resource group"):
        getattr(AzureResourceDiscovery("sub"), method)("")
