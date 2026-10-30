from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

from chaosforge.application.campaigns import manager
from chaosforge.application.services import campaign_service
from chaosforge.interfaces.web import app as web_app
from chaosforge.interfaces.web import execution as web_execution
from chaosforge.interfaces.web import log_manager as web_logs
from chaosforge.interfaces.web.execution import execution_session, get_executor
from chaosforge.interfaces.web.log_manager import LogManager, get_log_manager
from chaosforge.models import Campaign


def client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


def test_campaign_manager_keeps_aws_and_azure_campaigns_separate(monkeypatch):
    monkeypatch.setattr(manager, "history_store", SimpleNamespace(active_draft_id=lambda _: None))
    monkeypatch.setitem(manager.campaigns, "aws", Campaign(cloud_provider="aws"))
    monkeypatch.setitem(manager.campaigns, "azure", Campaign(cloud_provider="azure"))
    aws = SimpleNamespace(name="AWS fault")
    azure = SimpleNamespace(name="Azure fault")

    manager.add(aws, "aws")
    manager.add(azure, "azure")

    assert manager.get_campaign("aws").experiments == [aws]
    assert manager.get_campaign("azure").experiments == [azure]
    assert manager.get_campaign() is manager.campaigns["aws"]


def test_web_executors_and_logs_are_cloud_specific(monkeypatch):
    monkeypatch.setitem(web_logs.log_managers, "aws", LogManager())
    monkeypatch.setitem(web_logs.log_managers, "azure", LogManager())
    aws_executor = get_executor("aws")
    azure_executor = get_executor("azure")
    aws_logs = get_log_manager("aws")
    azure_logs = get_log_manager("azure")
    aws_logs.clear()
    azure_logs.clear()

    aws_executor.campaign = SimpleNamespace(name="AWS")
    azure_executor.campaign = SimpleNamespace(name="Azure")
    aws_logs.append("aws running")
    azure_logs.append("azure running")
    aws_logs.running = True
    azure_logs.finished = True

    assert aws_executor is not azure_executor
    assert aws_executor.campaign.name == "AWS"
    assert azure_executor.campaign.name == "Azure"
    assert aws_logs.get_logs() == ["aws running"]
    assert azure_logs.get_logs() == ["azure running"]
    assert aws_logs.running is True
    assert azure_logs.running is False
    assert azure_logs.finished is True


def test_execution_status_routes_select_the_requested_cloud(monkeypatch):
    web_app.app.config.update(TESTING=True)
    monkeypatch.setitem(web_logs.log_managers, "aws", LogManager())
    monkeypatch.setitem(web_logs.log_managers, "azure", LogManager())
    aws_logs = get_log_manager("aws")
    azure_logs = get_log_manager("azure")
    aws_logs.clear()
    azure_logs.clear()
    aws_logs.append("aws log")
    aws_logs.current = 1
    aws_logs.total = 2
    azure_logs.append("azure log")
    azure_logs.current = 2
    azure_logs.total = 3
    azure_logs.current_experiment = "Azure fault"
    azure_logs.running = True

    with web_app.app.test_client() as client:
        assert client.get("/execution/logs?cloud=aws").get_json() == ["aws log"]
        assert client.get("/execution/logs?cloud=azure").get_json() == ["azure log"]
        assert client.get("/progress?cloud=azure").get_json() == {
            "current": 2,
            "total": 3,
            "experiment": "Azure fault",
            "running": True,
            "finished": False,
        }


def test_execution_status_returns_run_specific_safe_target_details(monkeypatch):
    monkeypatch.setitem(
        web_execution._sessions,
        "aws",
        [{
            "id": "run-1",
            "status": "SUCCESS",
            "completed_at": "now",
            "progress": {"current": 1, "total": 1},
            "experiments": {
                "item": {
                    "service": "s3",
                    "experiment_id": "s3-versioning",
                    "target": {"variable": "bucket_name", "value": "chaosforge-e2e"},
                    "status": "SUCCESS",
                }
            },
        }],
    )
    web_app.app.config.update(TESTING=True)

    with web_app.app.test_client() as client:
        assert client.get("/api/execution/status?cloud=invalid&run=run-1").status_code == 400
        assert client.get("/api/execution/status?cloud=aws").status_code == 400
        assert client.get("/api/execution/status?cloud=aws&run=missing").status_code == 404
        response = client.get("/api/execution/status?cloud=aws&run=run-1")

    assert response.get_json() == {
        "run_id": "run-1",
        "status": "SUCCESS",
        "completed": True,
        "completed_at": "now",
        "progress": {"current": 1, "total": 1},
        "experiments": {
            "item": {
                "service": "s3",
                "experiment_id": "s3-versioning",
                "target": {"variable": "bucket_name", "value": "chaosforge-e2e"},
                "status": "SUCCESS",
            }
        },
    }


def test_campaign_service_delegates_explicit_cloud_operations(monkeypatch):
    campaign = SimpleNamespace(experiments=["azure experiment"])
    monkeypatch.setattr(campaign_service, "get", lambda index, cloud: (index, cloud))
    monkeypatch.setattr(campaign_service, "list_all", lambda cloud: [cloud])
    update = MagicMock()
    remove = MagicMock()
    clear = MagicMock()
    add = MagicMock()
    experiment = SimpleNamespace(name="Azure fault", service="aks", variables={})
    monkeypatch.setattr(campaign_service, "get_campaign", lambda cloud: campaign)
    monkeypatch.setattr(campaign_service, "create_experiment", lambda *_args, **_kwargs: experiment)
    monkeypatch.setattr(campaign_service, "add", add)
    monkeypatch.setattr(campaign_service, "update", update)
    monkeypatch.setattr(campaign_service, "remove", remove)
    monkeypatch.setattr(campaign_service, "clear", clear)

    assert campaign_service.get_experiment(2, "azure") == (2, "azure")
    assert campaign_service.get_experiments("azure") == ["azure"]
    assert campaign_service.add_experiment(
        {"service": "aks"}, {"id": "fault"}, {}, "azure"
    ) is experiment
    campaign_service.update_experiment(2, "replacement", "azure")
    campaign_service.remove_experiment(2, "azure")
    campaign_service.clear_current_campaign("azure")

    update.assert_called_once_with(2, "replacement", "azure")
    add.assert_called_once_with(experiment, "azure")
    remove.assert_called_once_with(2, "azure")
    clear.assert_called_once_with("azure")


def test_cloud_scoped_campaign_actions_and_yaml_replacement(monkeypatch):
    replacement = SimpleNamespace(name="Azure replacement", experiments=[])
    review = SimpleNamespace(valid=True, campaign=replacement, document={})
    preflight = SimpleNamespace(ready=True)
    replace = MagicMock()
    remove = MagicMock()
    clear = MagicMock()
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(web_app.campaign_preflight, "preflight", lambda *_args: preflight)
    monkeypatch.setattr(web_app, "replace_campaign", replace)
    monkeypatch.setattr(
        web_app,
        "create_campaign_draft",
        MagicMock(return_value=SimpleNamespace(
            campaign_id="campaign-new", created_at="created", updated_at="updated"
        )),
    )
    monkeypatch.setattr(web_app, "remove_experiment", remove)
    monkeypatch.setattr(web_app, "clear_current_campaign", clear)

    with web_app.app.test_client() as client:
        response = client.post(
            "/cloud/azure/campaign-yaml/review",
            data={"campaign_yaml": (BytesIO(b"campaign: azure"), "azure.yaml")},
        )
        assert response.status_code == 302
        assert client.get("/campaign/remove/1?cloud=azure").status_code == 302
        assert client.get("/campaign/clear?cloud=azure").status_code == 302

    replace.assert_called_once_with(replacement, "azure")
    assert replacement.campaign_id == "campaign-new"
    remove.assert_called_once_with(1, "azure")
    clear.assert_called_once_with("azure")


def test_log_manager_creates_an_azure_log_manager(monkeypatch):
    monkeypatch.delitem(web_logs.log_managers, "azure", raising=False)

    assert isinstance(get_log_manager("azure"), LogManager)


def test_cloud_landing_cart_uses_the_matching_campaign(monkeypatch):
    aws = SimpleNamespace(experiments=[SimpleNamespace(service="lambda")])
    azure = SimpleNamespace(experiments=[SimpleNamespace(service="azure_redis")])
    monkeypatch.setattr(web_app, "get_current_campaign", lambda cloud=None: azure if cloud == "azure" else aws)

    response = client().get("/cloud/azure")

    assert b"Current AZURE campaign with 1 experiments" in response.data


def test_completed_execution_session_preserves_cloud_scoped_logs(monkeypatch):
    experiment = SimpleNamespace(
        name="Redis reboot", service="azure_redis", id="azure-redis-reboot", variables={}
    )
    web_execution._sessions["azure"] = [
        {
            "id": "azure-run",
            "campaign_name": "Azure validation",
            "status": "FAILED",
            "started_at": "2026-09-30T00:00:00+00:00",
            "completed_at": "2026-09-30T00:01:00+00:00",
            "logs": ["Azure failure detail"],
                "progress": {
                "current": 1,
                "total": 1,
                "experiment": "Redis reboot",
                "running": False,
                    "finished": True,
                },
                "experiments": {
                    str(id(experiment)): {
                            "name": experiment.name,
                            "service": experiment.service,
                            "experiment_id": experiment.id,
                            "target": {},
                            "status": "FAILED",
                        "log_start": 0,
                    }
                },
            }
        ]
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "name": "Azure subscription"},
    )
    monkeypatch.setattr(
        web_app,
        "get_current_campaign",
        lambda *_: Campaign(cloud_provider="azure", experiments=[experiment]),
    )

    campaign = client().get("/campaign?cloud=azure")
    logs = client().get("/execution/logs?cloud=azure&run=azure-run")
    progress = client().get("/progress?cloud=azure&run=azure-run")

    assert b"View Execution" in campaign.data
    assert b"Redis reboot - FAILED" in campaign.data
    assert logs.get_json() == ["Azure failure detail"]
    assert progress.get_json()["finished"] is True
    assert execution_session("azure", "azure-run")["status"] == "FAILED"


def test_experiment_session_updates_the_matching_experiment_state(monkeypatch):
    experiment = SimpleNamespace(name="Redis reboot", service="azure_redis")
    monkeypatch.setitem(
        web_execution._sessions,
        "azure",
        [
            {
                "id": "azure-run",
                "experiments": {
                        str(id(experiment)): {
                            "name": experiment.name,
                            "service": experiment.service,
                            "experiment_id": None,
                            "target": {},
                            "status": "PENDING",
                        "log_start": None,
                    }
                },
            }
        ],
    )

    web_execution._update_experiment_session(
        "azure", "azure-run", experiment, status="RUNNING", log_start=4
    )

    assert execution_session("azure", "azure-run")["experiments"][str(id(experiment))] == {
        "name": "Redis reboot",
        "service": "azure_redis",
        "experiment_id": None,
        "target": {},
        "status": "RUNNING",
        "log_start": 4,
    }


def test_campaign_rows_link_to_the_run_that_executed_each_experiment(monkeypatch):
    experiment = SimpleNamespace(
        service="azure_redis", id="azure-redis-reboot", name="Redis reboot",
        status="Pending", variables={"resource_id": "/subscriptions/sub/redis"},
    )
    azure_campaign = SimpleNamespace(experiments=[experiment], cloud_provider="azure")
    web_execution._sessions["azure"] = [
        {
            "id": "azure-run",
            "campaign_name": "Default Campaign",
            "status": "SUCCESS",
            "started_at": "2026-09-30T00:00:00+00:00",
            "completed_at": "2026-09-30T00:01:00+00:00",
            "logs": ["Experiment 1/1: Redis reboot"],
            "progress": {},
            "experiments": {
                str(id(experiment)): {
                    "name": "Redis reboot",
                    "service": "azure_redis",
                    "experiment_id": "azure-redis-reboot",
                    "target": {"variable": "resource_id", "value": "/subscriptions/sub/redis"},
                    "status": "SUCCESS",
                    "log_start": 0,
                }
            },
        }
    ]
    monkeypatch.setattr(web_app, "get_current_campaign", lambda cloud=None: azure_campaign)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "name": "Azure subscription"},
    )

    response = client().get("/campaign?cloud=azure")

    assert b"View Results" in response.data
    assert b"run=azure-run" in response.data
    assert b"focus=0" in response.data
    assert b">SUCCESS</td>" in response.data


def test_transient_campaign_clear_boundary_excludes_in_memory_results(monkeypatch):
    experiment = SimpleNamespace(
        service="azure_redis", id="azure-redis-reboot", name="Redis reboot",
        status="Pending", variables={"resource_id": "/subscriptions/sub/redis"},
    )
    campaign = SimpleNamespace(
        experiments=[experiment], cloud_provider="azure", campaign_id=None,
        history_reset_at="2026-09-30T00:02:00+00:00",
    )
    web_execution._sessions["azure"] = [{
        "id": "azure-run",
        "campaign_name": "Default Campaign",
        "status": "SUCCESS",
        "started_at": "2026-09-30T00:00:00+00:00",
        "experiments": {},
    }]
    monkeypatch.setattr(web_app, "get_current_campaign", lambda cloud=None: campaign)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "name": "Azure subscription"},
    )

    response = client().get("/campaign?cloud=azure")

    assert b">Pending</td>" in response.data
    assert b"Latest AZURE execution:" not in response.data
