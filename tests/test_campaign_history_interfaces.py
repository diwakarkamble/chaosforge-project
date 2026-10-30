from unittest.mock import MagicMock

import pytest

from chaosforge.application.campaigns import manager
from chaosforge.application.services import campaign_service
from chaosforge.interfaces.cli import main as cli
from chaosforge.interfaces.web import app as web_app
from chaosforge.models import Campaign, Experiment


def test_manager_draft_operations_persist_mutations(monkeypatch):
    store = MagicMock()
    source = Campaign(name="Draft", cloud_provider="azure", campaign_id="campaign-1")
    store.create_draft.return_value = source
    store.load_draft.return_value = source
    monkeypatch.setattr(manager, "history_store", store)
    manager.campaigns["azure"] = Campaign(cloud_provider="azure")
    assert manager.create_draft("Draft", "azure").campaign_id == "campaign-1"
    manager.add(Experiment("id", "azure_redis", "Redis", "file", {}), "azure")
    manager.update(0, Experiment("id2", "azure_redis", "Redis 2", "file", {}), "azure")
    manager.remove(0, "azure")
    manager.clear("azure")
    assert manager.get_campaign("azure").history_reset_at is not None
    manager.open_draft("campaign-1", "azure")
    manager.list_drafts("azure")
    manager.delete_draft("campaign-1", "azure")
    assert store.save_draft.call_count >= 3
    store.load_draft.assert_called_once_with("azure", "campaign-1")
    manager.campaigns.pop("azure", None)
    assert manager.get_campaign("azure").cloud_provider == "azure"


def test_manager_recovers_missing_active_draft_and_resets_deleted_workspace(monkeypatch):
    store = MagicMock()
    store.active_draft_id.return_value = "missing"
    store.load_draft.side_effect = FileNotFoundError()
    monkeypatch.setattr(manager, "history_store", store)
    manager.campaigns.pop("azure", None)

    active = manager.get_campaign("azure")
    assert active.cloud_provider == "azure"
    store.clear_active_draft.assert_called_once_with("azure")

    active.campaign_id = "campaign-1"
    active.experiments = ["experiment"]
    manager.delete_draft("campaign-1", "azure")
    assert active.campaign_id is None
    assert active.experiments == []


def test_manager_replace_initializes_missing_cloud_workspace(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(manager, "history_store", store)
    manager.campaigns.pop("azure", None)

    result = manager.replace_campaign(Campaign(name="Azure", cloud_provider="azure", campaign_id="campaign-1"))

    assert result.name == "Azure"
    assert result is manager.campaigns["azure"]


def test_manager_replace_with_unsaved_campaign_does_not_overwrite_active_draft(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(manager, "history_store", store)
    manager.campaigns["azure"] = Campaign(
        name="Persisted", cloud_provider="azure", campaign_id="campaign-1",
        created_at="created", updated_at="updated",
    )

    result = manager.replace_campaign(Campaign(name="Replacement", cloud_provider="azure"))

    assert result.campaign_id is None
    assert result.created_at is None
    assert result.updated_at is None
    store.save_draft.assert_not_called()
    store.clear_active_draft.assert_called_once_with("azure")


def test_campaign_service_draft_facades(monkeypatch):
    create = MagicMock()
    open_ = MagicMock()
    listed = MagicMock(return_value=[])
    delete = MagicMock()
    monkeypatch.setattr(campaign_service, "create_draft", create)
    monkeypatch.setattr(campaign_service, "open_draft", open_)
    monkeypatch.setattr(campaign_service, "list_drafts", listed)
    monkeypatch.setattr(campaign_service, "delete_draft", delete)
    campaign_service.create_campaign_draft("Name", "aws")
    campaign_service.open_campaign_draft("id", "aws")
    assert campaign_service.list_campaign_drafts("aws") == []
    campaign_service.delete_campaign_draft("id", "aws")
    create.assert_called_once_with("Name", "aws")
    open_.assert_called_once_with("id", "aws")
    delete.assert_called_once_with("id", "aws")


@pytest.fixture
def client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


def test_web_campaign_library_create_open_delete_and_error(client, monkeypatch):
    draft = Campaign(name="Draft", cloud_provider="aws", campaign_id="campaign-1")
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "list_campaign_drafts", lambda _: [{"id": "campaign-1", "name": "Draft", "created_at": "now", "updated_at": "now", "experiments": 0}])
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda _: [{"campaign_name": "Draft", "created_at": "now", "source": "web", "status": "SUCCESS", "started_at": "now"}])
    monkeypatch.setattr(web_app, "create_campaign_draft", MagicMock(return_value=draft))
    assert client.get("/campaigns?cloud=aws").status_code == 200
    assert client.post("/campaigns?cloud=aws", data={"campaign_name": "Draft"}).status_code == 302
    opened = MagicMock()
    monkeypatch.setattr(web_app, "open_campaign_draft", opened)
    assert client.get("/campaigns/aws/campaign-1/open").status_code == 302
    monkeypatch.setattr(web_app, "delete_campaign_draft", MagicMock())
    assert client.post("/campaigns/aws/campaign-1/delete").status_code == 302
    monkeypatch.setattr(web_app, "create_campaign_draft", MagicMock(side_effect=ValueError("duplicate")))
    assert client.post("/campaigns?cloud=aws", data={"campaign_name": "Draft"}).status_code == 400
    monkeypatch.setattr(web_app, "open_campaign_draft", MagicMock(side_effect=FileNotFoundError()))
    assert client.get("/campaigns/aws/missing/open").status_code == 404
    monkeypatch.setattr(web_app, "delete_campaign_draft", MagicMock(side_effect=ValueError()))
    assert client.post("/campaigns/aws/missing/delete").status_code == 404


def test_campaign_page_uses_persisted_runs_for_the_open_draft(client, monkeypatch):
    experiment = Experiment(
        "s3-versioning", "s3", "S3 Versioning", "file", {"bucket_name": "e2e-bucket"}
    )
    campaign = Campaign(
        name="Draft", cloud_provider="aws", campaign_id="campaign-1", experiments=[experiment]
    )
    run = {
        "id": "execution-1",
        "campaign_id": "campaign-1",
        "campaign_name": "Draft",
        "status": "SUCCESS",
        "experiments": [{
            "id": "s3-versioning",
            "service": "s3",
            "status": "SUCCESS",
            "variables": {"bucket_name": "e2e-bucket"},
        }],
    }
    monkeypatch.setattr(web_app, "_current_campaign", lambda *_: campaign)
    monkeypatch.setattr(web_app, "_selected_experiments", lambda *_: campaign.experiments)
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda cloud, campaign_id=None: [run])

    response = client.get("/campaign?cloud=aws")

    assert response.status_code == 200
    assert b"execution-1" in response.data
    assert b"View Results" in response.data


def test_campaign_page_does_not_reuse_results_from_before_campaign_clear(client, monkeypatch):
    experiment = Experiment(
        "s3-versioning", "s3", "S3 Versioning", "file", {"bucket_name": "e2e-bucket"}
    )
    campaign = Campaign(
        name="Draft",
        cloud_provider="aws",
        campaign_id="campaign-1",
        history_reset_at="2026-10-29T12:00:00+00:00",
        experiments=[experiment],
    )
    old_run = {
        "id": "execution-old",
        "campaign_id": "campaign-1",
        "campaign_name": "Draft",
        "status": "SUCCESS",
        "started_at": "2026-10-29T11:00:00+00:00",
        "experiments": [{
            "id": "s3-versioning",
            "service": "s3",
            "status": "SUCCESS",
            "variables": {"bucket_name": "e2e-bucket"},
        }],
    }
    monkeypatch.setattr(web_app, "_current_campaign", lambda *_: campaign)
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda *_: [old_run])

    response = client.get("/campaign?cloud=aws")

    assert response.status_code == 200
    assert b">Pending</td>" in response.data
    assert b"View Results" not in response.data
    assert b"Latest AWS execution:" not in response.data


def test_campaign_page_labels_latest_execution_with_the_executed_experiment(client, monkeypatch):
    campaign = Campaign(name="Pod Kill", cloud_provider="azure", campaign_id="campaign-1")
    run = {
        "id": "execution-1",
        "campaign_id": "campaign-1",
        "campaign_name": "Pod Kill",
        "status": "SUCCESS",
        "experiments": [{"id": "aks-node-cpu-stress", "service": "aks", "name": "Node CPU Exhaustion"}],
    }
    monkeypatch.setattr(web_app, "_current_campaign", lambda *_: campaign)
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda *_: [run])

    response = client.get("/campaign?cloud=azure")

    assert b"Latest AZURE execution:" in response.data
    assert b"Node CPU Exhaustion - SUCCESS" in response.data
    assert b"Pod Kill - SUCCESS" not in response.data


def test_aks_results_do_not_match_a_different_pod_target(client, monkeypatch):
    experiment = Experiment(
        "aks-pod-kill", "aks", "Pod Kill", "file",
        {"aks_context": "cluster", "namespace": "apps", "target_mode": "pod", "pod": "api-2"},
    )
    campaign = Campaign(
        name="AKS", cloud_provider="azure", campaign_id="campaign-1", experiments=[experiment]
    )
    run = {
        "id": "execution-1",
        "campaign_id": "campaign-1",
        "status": "SUCCESS",
        "experiments": [{
            "id": "aks-pod-kill",
            "service": "aks",
            "status": "SUCCESS",
            "variables": {
                "aks_context": "cluster",
                "namespace": "apps",
                "target_mode": "pod",
                "pod": "api-1",
            },
        }],
    }
    monkeypatch.setattr(web_app, "_current_campaign", lambda *_: campaign)
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda *_: [run])

    response = client.get("/campaign?cloud=azure")

    assert b"View Results" not in response.data


def test_permission_review_retains_sns_topic_target(client, monkeypatch):
    campaign = Campaign(
        name="SNS",
        cloud_provider="aws",
        experiments=[
            Experiment(
                "sns-topic-policy",
                "sns",
                "Disable Topic Policy",
                "sns-topic-policy-chaos.json",
                {"topic_arn": "arn:aws:sns:eu-central-1:123456789012:topic"},
            )
        ],
    )
    monkeypatch.setattr(web_app, "_current_campaign", lambda *_: campaign)
    monkeypatch.setattr(web_app, "_selected_experiments", lambda *_: campaign.experiments)

    response = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": [0]})

    assert response.status_code == 200
    assert response.get_json()["experiments"][0]["target"] == {
        "variable": "topic_arn",
        "value": "arn:aws:sns:eu-central-1:123456789012:topic",
    }


def test_permission_review_retains_ecs_cluster_target(client, monkeypatch):
    campaign = Campaign(
        name="ECS",
        cloud_provider="aws",
        experiments=[
            Experiment(
                "ecs-force-deployment",
                "ecs",
                "Force New Deployment",
                "ecs-force-deployment-chaos.json",
                {"ecs_cluster": "chaos-simulator-cluster", "ecs_service": "simulator"},
            )
        ],
    )
    monkeypatch.setattr(web_app, "_current_campaign", lambda *_: campaign)
    monkeypatch.setattr(web_app, "_selected_experiments", lambda *_: campaign.experiments)

    response = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": [0]})

    assert response.status_code == 200
    assert response.get_json()["experiments"][0]["target"] == {
        "variable": "ecs_cluster",
        "value": "chaos-simulator-cluster",
    }


def test_execution_history_links_to_each_run_logs(client, monkeypatch):
    run = {
        "id": "execution-1",
        "campaign_name": "Draft",
        "created_at": "now",
        "source": "web",
        "status": "SUCCESS",
        "started_at": "now",
    }
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "list_campaign_drafts", lambda _: [])
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda _: [run])

    response = client.get("/campaigns?cloud=aws")

    assert b"View Logs" in response.data
    assert b"/execution?cloud=aws&amp;run=execution-1" in response.data


def test_historical_execution_uses_its_durable_log_and_report_record(client, monkeypatch, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "campaign-report-20261021-120000.txt"
    report.write_text("execution report", encoding="utf-8")
    record = {
        "id": "execution-1",
        "cloud": "aws",
        "campaign_name": "Draft",
        "status": "SUCCESS",
        "completed_at": "now",
        "logs": ["historical log"],
        "report_path": str(report),
        "experiments": [{"id": "s3-versioning"}],
    }
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "execution_session", lambda *_: None)
    monkeypatch.setattr(web_app.campaign_history, "load_execution", lambda _: record)
    monkeypatch.setattr(web_app, "REPORTS_DIR", reports)

    execution = client.get("/execution?cloud=aws&run=execution-1")
    logs = client.get("/execution/logs?cloud=aws&run=execution-1")
    progress = client.get("/progress?cloud=aws&run=execution-1")
    status = client.get("/api/execution/status?cloud=aws&run=execution-1")
    downloaded_logs = client.get("/download_logs?cloud=aws&run=execution-1")
    downloaded_report = client.get("/report/download?cloud=aws&run=execution-1")

    assert execution.status_code == 200
    assert logs.get_json() == ["historical log"]
    assert progress.get_json() == {
        "current": 1,
        "total": 1,
        "experiment": "",
        "running": False,
        "finished": True,
    }
    assert status.get_json()["status"] == "SUCCESS"
    assert downloaded_logs.data == b"historical log"
    assert downloaded_report.data == b"execution report"


def test_execution_record_rejects_invalid_or_cross_cloud_runs(client, monkeypatch):
    monkeypatch.setattr(web_app.campaign_history, "load_execution", lambda _: {"cloud": "azure"})

    with web_app.app.test_request_context("/"):
        assert web_app._execution_record("aws", "") is None
        assert web_app._execution_record("aws", "execution-1") is None
    monkeypatch.setattr(web_app.campaign_history, "load_execution", MagicMock(side_effect=FileNotFoundError()))
    with web_app.app.test_request_context("/"):
        assert web_app._execution_record("aws", "missing") is None

    response = client.get("/api/execution/status?cloud=aws&run=execution-1")

    assert response.status_code == 404


def test_download_logs_uses_the_matching_in_memory_run(client, monkeypatch):
    monkeypatch.setattr(web_app, "_execution_record", lambda *_: None)
    monkeypatch.setattr(
        web_app,
        "execution_session",
        lambda *_: {"completed_at": "now", "logs": ["active run log"]},
    )

    response = client.get("/download_logs?cloud=aws&run=execution-1")

    assert response.data == b"active run log"


def test_live_execution_uses_live_logs_even_when_its_durable_record_exists(client, monkeypatch):
    session = {"id": "execution-1", "completed_at": None, "logs": []}
    record = {
        "id": "execution-1",
        "cloud": "aws",
        "completed_at": None,
        "logs": [],
        "experiments": [],
    }
    logs = MagicMock()
    logs.get_logs.return_value = ["live lifecycle output"]
    logs.current = 1
    logs.total = 2
    logs.current_experiment = "Backup Retention"
    logs.running = True
    logs.finished = False
    monkeypatch.setattr(web_app, "execution_session", lambda *_: session)
    monkeypatch.setattr(web_app.campaign_history, "load_execution", lambda _: record)
    monkeypatch.setattr(web_app, "get_log_manager", lambda *_: logs)

    response = client.get("/execution/logs?cloud=aws&run=execution-1")
    progress = client.get("/progress?cloud=aws&run=execution-1")
    downloaded = client.get("/download_logs?cloud=aws&run=execution-1")

    assert response.get_json() == ["live lifecycle output"]
    assert progress.get_json()["experiment"] == "Backup Retention"
    assert downloaded.data == b"live lifecycle output"


def test_report_download_rejects_execution_record_paths_outside_reports_directory(
    client, monkeypatch, tmp_path
):
    reports = tmp_path / "reports"
    reports.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("sensitive", encoding="utf-8")
    monkeypatch.setattr(web_app, "REPORTS_DIR", reports)
    monkeypatch.setattr(
        web_app,
        "_execution_record",
        lambda *_: {"report_path": str(secret)},
    )

    response = client.get("/report/download?cloud=aws&run=execution-1")

    assert response.status_code == 404


def test_report_download_rejects_symlinked_fallback_report(client, monkeypatch, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("sensitive", encoding="utf-8")
    (reports / "report.txt").symlink_to(secret)
    monkeypatch.setattr(web_app, "REPORTS_DIR", reports)
    monkeypatch.setattr(web_app, "_execution_record", lambda *_: None)

    response = client.get("/report/download")

    assert response.status_code == 404


def test_report_download_rejects_non_text_execution_report(client, monkeypatch, tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "campaign-report-20261021-120000.pdf"
    report.write_text("not a text report", encoding="utf-8")
    monkeypatch.setattr(web_app, "REPORTS_DIR", reports)
    monkeypatch.setattr(
        web_app,
        "_execution_record",
        lambda *_: {"report_path": str(report)},
    )

    response = client.get("/report/download?cloud=aws&run=execution-1")

    assert response.status_code == 404


def test_approved_report_path_rejects_empty_value():
    assert web_app._approved_report_path("") is None


def test_campaign_library_ignores_return_target_for_redirects(client, monkeypatch):
    draft = Campaign(name="Draft", cloud_provider="aws", campaign_id="campaign-1")
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "load_metadata", lambda service: {"experiments": [{"id": "timeout"}]} if service == "lambda" else None)
    monkeypatch.setattr(web_app, "open_campaign_draft", MagicMock())
    monkeypatch.setattr(web_app, "create_campaign_draft", MagicMock(return_value=draft))
    monkeypatch.setattr(web_app, "list_campaign_drafts", lambda _: [{"id": "campaign-1", "name": "Draft", "created_at": "now", "updated_at": "now", "experiments": 0}])
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda _: [])

    library = client.get("/campaigns?cloud=aws&return_service=lambda&return_experiment=timeout")
    opened = client.get("/campaigns/aws/campaign-1/open")

    assert b"Back to Experiment" not in library.data
    assert opened.headers["Location"] == "/campaign?cloud=aws"


def test_campaign_open_ignores_request_derived_return_destination(client, monkeypatch):
    monkeypatch.setattr(web_app, "open_campaign_draft", MagicMock())

    response = client.get(
        "/campaigns/aws/campaign-1/open?return_service=//attacker.invalid"
        "&return_experiment=https://attacker.invalid"
    )

    assert response.headers["Location"] == "/campaign?cloud=aws"
    assert "attacker.invalid" not in response.headers["Location"]


def test_campaign_creation_redirects_to_fixed_campaign_route(client, monkeypatch):
    draft = Campaign(name="Draft", cloud_provider="aws", campaign_id="campaign-1")
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "load_metadata", lambda service: {"experiments": [{"id": "timeout"}]} if service == "lambda" else None)
    monkeypatch.setattr(web_app, "create_campaign_draft", MagicMock(return_value=draft))
    monkeypatch.setattr(web_app, "open_campaign_draft", MagicMock())
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda _: [])

    created = client.post(
        "/campaigns?cloud=aws&return_service=lambda&return_experiment=timeout",
        data={"campaign_name": "Draft"},
    )

    assert created.headers["Location"] == "/campaign?cloud=aws"


def test_empty_campaign_page_redirects_to_library_and_library_has_back_link(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: Campaign(cloud_provider="azure"))
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "list_campaign_drafts", lambda _: [])
    monkeypatch.setattr(web_app.campaign_history, "list_executions", lambda _: [])

    campaign = client.get("/campaign?cloud=azure")
    library = client.get("/campaigns?cloud=azure&return_cloud=azure")

    assert campaign.headers["Location"] == "/campaigns?cloud=azure"
    assert b"Back to AZURE Components" in library.data
    assert b'<div class="page-cart-row">' in library.data


def test_campaign_pages_redirect_when_the_selected_cloud_is_not_authenticated(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": False})

    assert (
        client.get("/campaign?cloud=aws").headers["Location"]
        == "/cloud/aws?notice=campaign-auth-required"
    )
    assert client.get("/campaigns?cloud=aws").headers["Location"] == "/cloud/aws"


def test_cloud_redirects_are_fixed_internal_locations():
    with web_app.app.test_request_context("/"):
        assert web_app._cloud_services_redirect("azure").headers["Location"] == "/cloud/azure"
        assert web_app._cloud_services_redirect("https://attacker.invalid").headers["Location"] == "/cloud/aws"
        assert web_app._aws_execution_redirect("//attacker.invalid").headers["Location"] == "/execution?cloud=aws"


def test_provider_page_shows_campaign_gate_without_an_active_draft(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: Campaign(cloud_provider="aws"))
    monkeypatch.setattr(web_app, "list_campaign_drafts", lambda _: [])

    response = client.get("/cloud/aws")

    assert b"Choose an AWS campaign" in response.data


def test_campaign_library_rejects_invalid_return_targets(client, monkeypatch):
    monkeypatch.setattr(web_app, "load_metadata", lambda _: None)

    with web_app.app.test_request_context("/campaigns"):
        assert web_app._campaign_return_target("aws") is None
    with web_app.app.test_request_context("/campaigns?return_service=lambda&return_experiment=timeout"):
        assert web_app._campaign_return_target("aws") is None
    monkeypatch.setattr(web_app, "load_metadata", lambda _: {"experiments": []})
    with web_app.app.test_request_context("/campaigns?return_service=lambda&return_experiment=timeout"):
        assert web_app._campaign_return_target("aws") is None
    monkeypatch.setattr(web_app, "load_metadata", lambda _: {"experiments": [{"id": "timeout"}]})
    with web_app.app.test_request_context("/campaigns?return_service=lambda&return_experiment=timeout&return_edit_index=2"):
        assert web_app._campaign_return_target("aws")["return_edit_index"] == 2


def test_campaign_library_redirects_only_to_allowlisted_routes(client, monkeypatch):
    monkeypatch.setattr(web_app, "delete_campaign_draft", MagicMock())

    response = client.post("/campaigns/attacker.invalid/draft/delete")

    assert response.headers["Location"] == "/campaigns?cloud=aws"

    with web_app.app.test_request_context("/"):
        assert web_app._aws_campaign_library_redirect().headers["Location"] == "/campaigns?cloud=aws"
        assert web_app._azure_campaign_library_redirect().headers["Location"] == "/campaigns?cloud=azure"

    monkeypatch.setattr(web_app, "open_campaign_draft", MagicMock())
    response = client.get("/campaigns/aws/draft/open?return_cloud=aws")

    assert response.headers["Location"] == "/campaign?cloud=aws"


def test_cli_history_and_library_choices(monkeypatch):
    monkeypatch.setattr(cli, "clear_screen", MagicMock())
    monkeypatch.setattr(cli, "print_banner", MagicMock())
    monkeypatch.setattr(cli, "title", MagicMock())
    monkeypatch.setattr(cli, "menu", MagicMock())
    monkeypatch.setattr(cli, "pause", MagicMock())
    monkeypatch.setattr(cli, "info", MagicMock())
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="0"))
    monkeypatch.setattr(cli, "get_cloud_identity", MagicMock(return_value={"authenticated": True}))
    cli.context.cloud = "aws"
    monkeypatch.setattr(cli.campaign_history, "list_executions", MagicMock(return_value=[]))
    cli.campaign_history_view()
    monkeypatch.setattr(cli, "list_campaign_drafts", MagicMock(return_value=[]))
    cli.campaign_library()


def test_cli_history_and_library_details_and_errors(monkeypatch):
    for name in ("clear_screen", "print_banner", "title", "menu", "pause", "success", "error"):
        monkeypatch.setattr(cli, name, MagicMock())
    cli.context.cloud = "aws"
    monkeypatch.setattr(cli, "get_cloud_identity", MagicMock(return_value={"authenticated": True}))
    record = {
        "campaign_name": "Draft", "status": "SUCCESS", "source": "web", "created_at": "created",
        "started_at": "started", "completed_at": "completed", "report_path": "report.txt", "logs": ["log"],
    }
    monkeypatch.setattr(cli.campaign_history, "list_executions", MagicMock(return_value=[record]))
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(cli, "console", MagicMock())
    cli.campaign_history_view()
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="bad"))
    cli.campaign_history_view()
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="0"))
    cli.campaign_history_view()
    drafts = [{"id": "campaign-1", "name": "Draft", "experiments": 1, "created_at": "created"}]
    monkeypatch.setattr(cli, "list_campaign_drafts", MagicMock(return_value=drafts))
    monkeypatch.setattr(cli, "open_campaign_draft", MagicMock())
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="2"))
    cli.campaign_library()


def test_cli_import_duplicate_draft_and_main_menu_history_dispatch(monkeypatch):
    monkeypatch.setattr(cli, "error", MagicMock())
    monkeypatch.setattr(cli, "pause", MagicMock())
    cli.context.cloud = "aws"
    review = type("Review", (), {"campaign": Campaign(name="Duplicate"), "valid": True, "errors": (), "document": {}})()
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="campaign.yaml"))
    monkeypatch.setattr(cli.os.path, "isfile", lambda _: True)
    monkeypatch.setattr(cli.Path, "read_bytes", lambda _: b"yaml")
    monkeypatch.setattr(cli.campaign_yaml_service, "inspect_bytes", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(cli.campaign_preflight, "preflight", lambda *_: type("Ready", (), {"ready": True})())
    monkeypatch.setattr(cli, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(cli, "create_campaign_draft", MagicMock(side_effect=ValueError("duplicate")))
    cli.import_yaml_campaign()
    cli.error.assert_called_once_with("duplicate")
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["1", "New Draft"]))
    monkeypatch.setattr(cli, "create_campaign_draft", MagicMock())
    cli.campaign_library()
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["1", "New Draft", "0"]))
    monkeypatch.setattr(cli, "create_campaign_draft", MagicMock(side_effect=ValueError("duplicate")))
    cli.campaign_library()
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["3", "0"]))
    cli.campaign_library()
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["2", "0"]))
    monkeypatch.setattr(cli, "open_campaign_draft", MagicMock(side_effect=FileNotFoundError()))
    cli.campaign_library()


def test_cli_campaign_library_deletes_a_draft(monkeypatch):
    for name in ("clear_screen", "print_banner", "title", "menu", "pause", "success"):
        monkeypatch.setattr(cli, name, MagicMock())
    cli.context.cloud = "aws"
    monkeypatch.setattr(cli, "get_cloud_identity", MagicMock(return_value={"authenticated": True}))
    draft = {"id": "campaign-1", "name": "Draft", "experiments": 1, "created_at": "created"}
    monkeypatch.setattr(cli, "list_campaign_drafts", MagicMock(return_value=[draft]))
    deleted = MagicMock()
    monkeypatch.setattr(cli, "delete_campaign_draft", deleted)
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["d", "1", "y", "0"]))

    assert cli.campaign_library() is False

    deleted.assert_called_once_with("campaign-1", "aws")
