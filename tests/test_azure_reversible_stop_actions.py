import builtins
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from chaosforge.providers.azure.components.azure_app_service.experiments.custom.actions import (
    app_state_actions,
)
from chaosforge.providers.azure.components.azure_postgres_flexible.experiments.custom.actions import (
    server_state_actions,
)


def test_app_service_stop_restores_only_a_running_baseline(monkeypatch, tmp_path):
    calls = []
    client = SimpleNamespace(
        web_apps=SimpleNamespace(
            get=lambda *_: SimpleNamespace(state="Running"),
            stop=lambda *args: calls.append(("stop", args)),
            start=lambda *args: calls.append(("start", args)),
        )
    )
    monkeypatch.setattr(app_state_actions, "_client", lambda _: client)
    monkeypatch.setattr(app_state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app"

    app_state_actions.stop_app_service("sub", "rg", resource_id)
    app_state_actions.restore_app_service("sub", "rg", resource_id)

    assert [call[0] for call in calls] == ["stop", "start"]


def test_postgres_stop_leaves_an_initially_stopped_server_stopped(monkeypatch, tmp_path):
    calls = []
    client = SimpleNamespace(
        servers=SimpleNamespace(
            get=lambda *_: SimpleNamespace(state="Stopped"),
            begin_stop=lambda *args: calls.append(("stop", args)),
            begin_start=lambda *args: calls.append(("start", args)),
        )
    )
    monkeypatch.setattr(server_state_actions, "_client", lambda _: client)
    monkeypatch.setattr(server_state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/server"

    server_state_actions.stop_server("sub", "rg", resource_id)
    server_state_actions.restore_server("sub", "rg", resource_id)

    assert calls == []


def test_app_service_restore_rejects_another_target_and_sdk_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(app_state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app"
    path = app_state_actions._path("sub", "rg", "app")
    path.parent.mkdir(parents=True)
    path.write_text('{"resource_id":"/other","was_running":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="another target"):
        app_state_actions.restore_app_service("sub", "rg", resource_id)

    monkeypatch.setattr(app_state_actions, "_client", lambda _: (_ for _ in ()).throw(RuntimeError("sdk")))
    with pytest.raises(RuntimeError, match="sdk"):
        app_state_actions.stop_app_service("sub", "rg", resource_id)

    monkeypatch.setattr(app_state_actions, "_client", lambda _: (_ for _ in ()).throw(RuntimeError("sdk")))
    with pytest.raises(RuntimeError, match="sdk"):
        app_state_actions._client("sub")


def test_postgres_running_server_stops_and_restores_and_rejects_other_target(monkeypatch, tmp_path):
    calls = []
    client = SimpleNamespace(
        servers=SimpleNamespace(
            get=lambda *_: SimpleNamespace(state="Ready"),
            begin_stop=lambda *args: calls.append(("stop", args)) or SimpleNamespace(result=lambda: None),
            begin_start=lambda *args: calls.append(("start", args)) or SimpleNamespace(result=lambda: None),
        )
    )
    monkeypatch.setattr(server_state_actions, "_client", lambda _: client)
    monkeypatch.setattr(server_state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/server"

    server_state_actions.stop_server("sub", "rg", resource_id)
    server_state_actions.restore_server("sub", "rg", resource_id)
    assert [call[0] for call in calls] == ["stop", "start"]

    path = server_state_actions._path("sub", "rg", "server")
    path.write_text('{"resource_id":"/other","was_running":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="another target"):
        server_state_actions.restore_server("sub", "rg", resource_id)

    monkeypatch.setattr(server_state_actions, "_client", lambda _: (_ for _ in ()).throw(RuntimeError("sdk")))
    with pytest.raises(RuntimeError, match="sdk"):
        server_state_actions.stop_server("sub", "rg", resource_id)


def test_reversible_stop_action_clients_construct_sdk_clients(monkeypatch):
    credential = object()
    app_client = object()
    postgres_client = object()
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: credential))
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.web",
        SimpleNamespace(WebSiteManagementClient=lambda actual_credential, subscription: (app_client, actual_credential, subscription)),
    )
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.rdbms.postgresql_flexibleservers",
        SimpleNamespace(PostgreSQLManagementClient=lambda actual_credential, subscription: (postgres_client, actual_credential, subscription)),
    )

    assert app_state_actions._client("sub") == (app_client, credential, "sub")
    assert server_state_actions._client("sub") == (postgres_client, credential, "sub")


@pytest.mark.parametrize(
    ("module", "missing"),
    [
        (app_state_actions, "azure.mgmt.web"),
        (server_state_actions, "azure.mgmt.rdbms.postgresql_flexibleservers"),
    ],
)
def test_reversible_stop_actions_report_missing_sdk(monkeypatch, module, missing):
    original_import = builtins.__import__

    def missing_sdk(name, *args, **kwargs):
        if name == missing:
            raise ImportError("missing SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_sdk)
    with pytest.raises(RuntimeError, match="SDK dependencies are unavailable"):
        module._client("sub")


def test_reversible_stop_actions_handle_missing_rollback_state(monkeypatch, tmp_path):
    monkeypatch.setattr(app_state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    monkeypatch.setattr(server_state_actions, "repository_paths", lambda: SimpleNamespace(rollback=tmp_path))
    app = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/app"
    server = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/server"

    assert app_state_actions.restore_app_service("sub", "rg", app) == "No App Service state was recorded."
    assert server_state_actions.restore_server("sub", "rg", server) == "No PostgreSQL server state was recorded."


def test_postgres_stop_definition_uses_the_supported_servers_operation_group():
    definition_path = (
        Path(__file__).parents[1]
        / "chaosforge/providers/azure/components/azure_postgres_flexible/experiments"
        / "custom/definitions/azure-postgres-flexible-stop.json"
    )
    definition = json.loads(definition_path.read_text(encoding="utf-8"))

    assert definition["method"][0]["provider"]["func"] == "stop_server"
    assert "flexible_servers" not in Path(server_state_actions.__file__).read_text(
        encoding="utf-8"
    )
