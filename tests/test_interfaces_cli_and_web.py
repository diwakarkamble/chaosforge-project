import sys
from copy import deepcopy
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# The CLI imports AWS discovery, which imports the optional Kubernetes client.
# These interface tests mock all discovery paths and only need its exception type.
if "kubernetes" not in sys.modules:
    kubernetes = ModuleType("kubernetes")
    kubernetes_client = ModuleType("kubernetes.client")
    kubernetes_config = ModuleType("kubernetes.config")
    kubernetes_rest = ModuleType("kubernetes.client.rest")
    kubernetes_config_exception = ModuleType("kubernetes.config.config_exception")
    kubernetes_rest.ApiException = type("ApiException", (Exception,), {})
    kubernetes_config_exception.ConfigException = type(
        "ConfigException", (Exception,), {}
    )
    kubernetes.client = kubernetes_client
    kubernetes.config = kubernetes_config
    kubernetes_client.rest = kubernetes_rest
    kubernetes_config.config_exception = kubernetes_config_exception
    sys.modules.update(
        {
            "kubernetes": kubernetes,
            "kubernetes.client": kubernetes_client,
            "kubernetes.config": kubernetes_config,
            "kubernetes.client.rest": kubernetes_rest,
            "kubernetes.config.config_exception": kubernetes_config_exception,
        }
    )

from chaosforge.catalog import ExperimentCatalog
from chaosforge.common.paths import ChaosForgePaths
from chaosforge.interfaces.cli import main as cli_main
from chaosforge.interfaces.web import __main__ as web_main
from chaosforge.interfaces.web import app as web_app
from chaosforge.interfaces.web import execution as web_execution
from chaosforge.interfaces.web.execution import ExecutionAlreadyRunning, WebExecution
from chaosforge.interfaces.web.log_manager import LogManager
from chaosforge.models import Campaign, Experiment
from chaosforge.storage.campaign_history import CampaignHistoryStore


def test_cli_help_displays_parser(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["chaosforge", "--help"])

    with pytest.raises(SystemExit) as exit_result:
        cli_main.main()

    assert exit_result.value.code == 0
    assert "usage: chaosforge" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("command", "handler"),
    [
        ("validate", "validate_yaml_campaign"),
        ("plan", "plan_yaml_campaign"),
        ("run", "execute_yaml_campaign"),
    ],
)
def test_cli_command_dispatches_yaml_file(monkeypatch, command, handler):
    execute = MagicMock(return_value=7)
    monkeypatch.setattr(cli_main, handler, execute)
    monkeypatch.setattr(sys, "argv", ["chaosforge", command, "campaign.yaml"])

    with pytest.raises(SystemExit) as exit_result:
        cli_main.main()

    assert exit_result.value.code == 7
    execute.assert_called_once_with("campaign.yaml")


def test_cli_yaml_and_interactive_dispatch(monkeypatch):
    execute = MagicMock()
    interactive = MagicMock()
    monkeypatch.setattr(cli_main, "execute_yaml_campaign", execute)
    monkeypatch.setattr(cli_main, "interactive_main", interactive)

    monkeypatch.setattr(sys, "argv", ["chaosforge", "--yaml", "campaign.yaml"])
    cli_main.main()
    execute.assert_called_once_with("campaign.yaml")
    interactive.assert_not_called()

    monkeypatch.setattr(sys, "argv", ["chaosforge"])
    cli_main.main()
    interactive.assert_called_once_with()


def test_cli_run_accepts_explicit_chaos_mesh_version_policy(monkeypatch):
    execute = MagicMock(return_value=0)
    monkeypatch.setattr(cli_main, "execute_yaml_campaign", execute)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chaosforge", "run", "campaign.yaml",
            "--chaos-mesh-version-policy", "upgrade",
        ],
    )

    with pytest.raises(SystemExit) as result:
        cli_main.main()

    assert result.value.code == 0
    execute.assert_called_once_with(
        "campaign.yaml", chaos_mesh_version_policy="upgrade"
    )


def test_cli_main_handles_keyboard_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["chaosforge"])
    monkeypatch.setattr(cli_main, "interactive_main", MagicMock(side_effect=KeyboardInterrupt))

    cli_main.main()

    assert "Shutdown requested" in capsys.readouterr().out


def test_log_manager_converts_lines_returns_snapshot_and_clears():
    manager = LogManager()
    manager.append(42)
    logs = manager.get_logs()
    logs.append("local change")
    manager.running = True
    manager.finished = True
    manager.current = 2
    manager.total = 3
    manager.current_experiment = "lambda timeout"

    assert manager.get_logs() == ["42"]

    manager.clear()

    assert manager.get_logs() == []
    assert (manager.running, manager.finished, manager.current, manager.total) == (
        False,
        False,
        0,
        0,
    )
    assert manager.current_experiment == ""


def test_web_execution_updates_matching_session(monkeypatch):
    session = {"id": "session-1", "status": "RUNNING"}
    monkeypatch.setitem(web_execution._sessions, "aws", [session])

    web_execution._update_session("aws", "session-1", status="SUCCESS")

    assert session["status"] == "SUCCESS"


def test_cli_version_uses_the_canonical_version(monkeypatch, capsys):
    monkeypatch.setattr(cli_main, "chaosforge_version", lambda: "9.9.9")
    monkeypatch.setattr(sys, "argv", ["chaosforge", "--version"])

    with pytest.raises(SystemExit) as result:
        cli_main.main()

    assert result.value.code == 0
    assert capsys.readouterr().out == "chaosforge 9.9.9\n"


def test_experiment_target_includes_ec2_instance_ids():
    experiment = Experiment(
        "ec2-incremental-instance-stop",
        "ec2",
        "Incremental Instance Stop",
        "file",
        {"instance_ids": "i-123"},
    )

    assert web_execution.experiment_target(experiment) == {
        "variable": "instance_ids",
        "value": "i-123",
    }


def test_experiment_target_includes_ec2_instance_id():
    experiment = Experiment(
        "ec2-ebs-volume-detach",
        "ec2",
        "EBS Volume Detachment",
        "file",
        {"instance_id": "i-123"},
    )

    assert web_execution.experiment_target(experiment) == {
        "variable": "instance_id",
        "value": "i-123",
    }


def test_experiment_target_includes_sns_topic_arn():
    experiment = Experiment(
        "sns-topic-policy",
        "sns",
        "Disable Topic Policy",
        "file",
        {"topic_arn": "arn:aws:sns:eu-central-1:123456789012:topic"},
    )

    assert web_execution.experiment_target(experiment) == {
        "variable": "topic_arn",
        "value": "arn:aws:sns:eu-central-1:123456789012:topic",
    }


def test_experiment_target_includes_the_full_aks_pod_target():
    experiment = Experiment(
        "aks-pod-kill", "aks", "Pod Kill", "file",
        {"aks_context": "cluster", "namespace": "apps", "target_mode": "pod", "pod": "api-1"},
    )

    assert web_execution.experiment_target(experiment) == {
        "variable": "aks_target",
        "value": "aks_context=cluster|namespace=apps|target_mode=pod|pod=api-1",
    }


def test_experiment_target_includes_ecs_cluster():
    experiment = Experiment(
        "ecs-force-deployment",
        "ecs",
        "Force New Deployment",
        "file",
        {"ecs_cluster": "chaos-simulator-cluster", "ecs_service": "simulator"},
    )

    assert web_execution.experiment_target(experiment) == {
        "variable": "ecs_cluster",
        "value": "chaos-simulator-cluster",
    }


@pytest.mark.parametrize(
    ("experiment_id", "service", "variables", "expected"),
    [
        (
            "vpc-security-group",
            "vpc",
            {"security_group_id": "sg-123", "selected_rule": "0"},
            {"variable": "security_group_id", "value": "sg-123"},
        ),
        (
            "apigateway-stage-throttling",
            "apigateway",
            {"rest_api_id": "api-123", "stage_name": "test"},
            {"variable": "rest_api_id", "value": "api-123"},
        ),
    ],
)
def test_experiment_target_uses_catalog_root_resource(experiment_id, service, variables, expected):
    experiment = Experiment(experiment_id, service, "Experiment", "file", variables)

    assert web_execution.experiment_target(experiment) == expected


def test_experiment_target_projects_every_catalog_root_resource_field():
    catalog = ExperimentCatalog()
    resource_types = {"aws_resource", "azure_component_resource", "aws_fis_template"}

    for service in catalog.list_services():
        for metadata in catalog.load_service(service).get("experiments", []):
            root = next(
                (
                    field
                    for field in metadata.get("inputs", [])
                    if not field.get("parent") and field.get("type") in resource_types
                ),
                None,
            )
            if root is None:
                continue
            experiment = Experiment(
                metadata["id"], service, metadata["name"], metadata.get("json", ""),
                {root["name"]: "target"},
            )

            assert web_execution.experiment_target(experiment) == {
                "variable": root["name"],
                "value": "target",
            }


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("replication_group_id", "chaosforge-e2e-redis"),
        ("cache_cluster_id", "chaosforge-e2e-redis-001"),
        ("serverless_cache_name", "chaosforge-e2e-serverless"),
    ],
)
def test_experiment_target_includes_elasticache_targets(variable, value):
    experiment = Experiment("elasticache", "elasticache", "ElastiCache", "file", {variable: value})

    assert web_execution.experiment_target(experiment) == {
        "variable": variable,
        "value": value,
    }


def test_web_execution_starts_only_once(monkeypatch, tmp_path):
    execution = WebExecution(history=CampaignHistoryStore(ChaosForgePaths(tmp_path)))
    campaign = Campaign(experiments=[Experiment("id", "lambda", "Lambda", "file", {})])
    fake_logs = MagicMock(running=False)
    thread = MagicMock()
    thread_class = MagicMock(return_value=thread)
    monkeypatch.setattr("chaosforge.interfaces.web.execution.log_manager", fake_logs)
    monkeypatch.setattr("chaosforge.interfaces.web.execution.Thread", thread_class)

    run_id = execution.start(campaign)

    fake_logs.clear.assert_called_once_with()
    assert fake_logs.running is True
    accepted_campaign = thread_class.call_args.kwargs["args"][0]
    assert accepted_campaign is not campaign
    assert accepted_campaign.experiments[0].id == "id"
    thread_class.assert_called_once_with(
        target=execution.execute, args=(accepted_campaign, run_id, None), daemon=False
    )
    thread.start.assert_called_once_with()

    with pytest.raises(ExecutionAlreadyRunning) as conflict:
        execution.start(Campaign(name="Second"))
    assert conflict.value.run_id == run_id
    assert thread.start.call_count == 1


def test_web_execution_worker_keeps_accepted_campaign_binding(monkeypatch):
    history = MagicMock()
    history.start_execution.return_value = "run-a"
    execution = WebExecution(history=history)
    campaign_a = Campaign(
        name="A", experiments=[Experiment("a", "lambda", "A", "file", {})]
    )
    campaign_b = Campaign(
        name="B", experiments=[Experiment("b", "lambda", "B", "file", {})]
    )
    thread = MagicMock()
    thread_class = MagicMock(return_value=thread)
    monkeypatch.setattr(web_execution, "Thread", thread_class)

    execution.start(campaign_a)
    worker_campaign, run_id, on_experiment_complete = thread_class.call_args.kwargs["args"]
    assert on_experiment_complete is None
    with pytest.raises(ExecutionAlreadyRunning):
        execution.start(campaign_b)
    with patch(
        "chaosforge.interfaces.web.runner.WebExperimentRunner.execute_campaign",
        return_value=SimpleNamespace(status="SUCCESS"),
    ) as run_campaign:
        execution.execute(worker_campaign, run_id)

    run_campaign.assert_called_once_with(worker_campaign)
    history.finish_execution.assert_called_once()
    assert history.finish_execution.call_args.args[:2] == ("run-a", worker_campaign)


@pytest.mark.parametrize(
    ("cloud", "service", "experiment_id", "variables"),
    [
        (
            "aws",
            "chaos_mesh",
            "chaos-mesh-pod-failure",
            {"eks_cluster": "cluster", "namespace": "apps", "deployment": "api"},
        ),
        (
            "azure",
            "azure_vm",
            "azure-vm-boot-diagnostics-toggle",
            {"resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"},
        ),
    ],
)
def test_web_execution_propagates_terminal_status_to_the_active_campaign(
    monkeypatch, cloud, service, experiment_id, variables
):
    active_experiment = Experiment(
        experiment_id,
        service,
        "Experiment",
        "",
        variables,
        engine="Chaos Mesh" if cloud == "aws" else "Azure SDK",
    )
    active_campaign = Campaign(experiments=[active_experiment], cloud_provider=cloud)
    copied_experiment = deepcopy(active_experiment)
    copied_experiment.status = "SUCCESS"
    copied_experiment.warnings = [{"label": "Recovered", "detail": "Pod replacement is ready."}]
    copied_experiment.error_message = ""
    executor = MagicMock()
    executor.start.return_value = "run-a"
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)
    updated = MagicMock()
    monkeypatch.setattr(web_app, "update_experiment", updated)

    run_id, conflict = web_app._start_web_execution(
        Campaign(experiments=[copied_experiment], cloud_provider=cloud), active_campaign
    )

    assert (run_id, conflict) == ("run-a", None)
    callback = executor.start.call_args.kwargs["on_experiment_complete"]
    callback(copied_experiment)

    assert active_experiment.status == "SUCCESS"
    assert active_experiment.warnings == copied_experiment.warnings
    updated.assert_called_once_with(0, active_experiment, cloud)


def test_web_execution_outcome_sync_ignores_missing_or_nonmatching_active_experiments(monkeypatch):
    copied_experiment = Experiment("id", "lambda", "Lambda", "", {"lambda_name": "function"})
    copied_experiment.status = "SUCCESS"
    executor = MagicMock()
    executor.start.return_value = "run-a"
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)
    updated = MagicMock()
    monkeypatch.setattr(web_app, "update_experiment", updated)

    web_app._start_web_execution(Campaign(experiments=[copied_experiment]), None)
    executor.start.call_args.kwargs["on_experiment_complete"](copied_experiment)

    nonmatching = Experiment("id", "lambda", "Lambda", "", {"lambda_name": "other-function"})
    active_campaign = Campaign(experiments=[nonmatching])
    web_app._start_web_execution(Campaign(experiments=[copied_experiment]), active_campaign)
    executor.start.call_args.kwargs["on_experiment_complete"](copied_experiment)

    updated.assert_not_called()


def test_web_execution_rejects_missing_campaign():
    with pytest.raises(ValueError, match="No campaign selected"):
        WebExecution(history=MagicMock()).start()


def test_web_execution_releases_admission_when_thread_start_fails(monkeypatch):
    history = MagicMock()
    history.start_execution.return_value = "run-1"
    execution = WebExecution(history=history)
    thread = MagicMock()
    thread.start.side_effect = RuntimeError("thread unavailable")
    monkeypatch.setattr(web_execution, "Thread", MagicMock(return_value=thread))

    with pytest.raises(RuntimeError, match="thread unavailable"):
        execution.start(Campaign(name="Campaign"))

    assert execution.run_id is None
    assert execution.campaign is None
    history.finish_execution.assert_called_once()
    assert history.finish_execution.call_args.args[2] == "FAILED"


def test_web_execution_releases_admission_when_history_start_fails():
    history = MagicMock()
    history.start_execution.side_effect = OSError("storage unavailable")
    execution = WebExecution(history=history)

    with pytest.raises(OSError, match="storage unavailable"):
        execution.start(Campaign(name="Campaign"))

    assert execution.run_id is None
    assert execution.campaign is None
    assert execution.thread is None
    assert execution.logs.running is False
    history.finish_execution.assert_not_called()


def test_web_execution_releases_admission_when_startup_history_cleanup_fails(
    monkeypatch,
):
    history = MagicMock()
    history.start_execution.return_value = "run-1"
    history.finish_execution.side_effect = OSError("cleanup unavailable")
    execution = WebExecution(history=history)
    thread = MagicMock()
    thread.start.side_effect = RuntimeError("thread unavailable")
    monkeypatch.setattr(web_execution, "Thread", MagicMock(return_value=thread))

    with pytest.raises(OSError, match="cleanup unavailable"):
        execution.start(Campaign(name="Campaign"))

    assert execution.run_id is None
    assert execution.campaign is None
    assert execution.thread is None


def test_web_execution_records_success_and_expected_failure(monkeypatch, tmp_path):
    execution = WebExecution(history=CampaignHistoryStore(ChaosForgePaths(tmp_path)))
    execution.campaign = object()
    fake_logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.execution.log_manager", fake_logs)

    with patch(
        "chaosforge.interfaces.web.runner.WebExperimentRunner.execute_campaign"
        , return_value=SimpleNamespace(status="SUCCESS")
    ) as run_campaign:
        execution.execute()

    run_campaign.assert_called_once_with(execution.campaign)
    assert "Campaign Completed: SUCCESS" in [call.args[0] for call in fake_logs.append.call_args_list]
    assert fake_logs.running is False
    assert fake_logs.finished is True

    fake_logs.reset_mock()
    execution.campaign = object()
    with patch(
        "chaosforge.interfaces.web.runner.WebExperimentRunner.execute_campaign",
        side_effect=RuntimeError("runner failed"),
    ):
        execution.execute()

    assert "Campaign Failed" in [call.args[0] for call in fake_logs.append.call_args_list]
    assert "runner failed" in [call.args[0] for call in fake_logs.append.call_args_list]


def test_web_execution_waits_for_active_rollback(monkeypatch, tmp_path):
    execution = WebExecution(history=CampaignHistoryStore(ChaosForgePaths(tmp_path)))
    worker = MagicMock()
    worker.is_alive.return_value = True
    execution.thread = worker
    logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.execution.log_manager", logs)

    execution.wait_for_completion()

    logs.append.assert_called_once_with(
        "Shutdown requested; waiting for active experiment rollback."
    )
    worker.join.assert_called_once_with()

def test_web_execution_streams_lifecycle_and_mission_summary(monkeypatch, tmp_path):
    execution = WebExecution(history=CampaignHistoryStore(ChaosForgePaths(tmp_path)))
    execution.campaign = object()
    fake_logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.execution.log_manager", fake_logs)

    def execute_campaign(_campaign):
        print("Lifecycle Validation\nPRE-CHECK\nResult      : PASSED")
        print("Mission Summary\nOverall Result : SUCCESS")
        return SimpleNamespace(status="SUCCESS")

    with patch(
        "chaosforge.interfaces.web.runner.WebExperimentRunner.execute_campaign",
        side_effect=execute_campaign,
    ):
        execution.execute()

    lines = [call.args[0] for call in fake_logs.append.call_args_list]
    assert "Lifecycle Validation" in lines
    assert "PRE-CHECK" in lines
    assert "Mission Summary" in lines
    assert "Campaign Completed: SUCCESS" in lines


def test_web_log_stream_keeps_character_output_on_one_line(monkeypatch):
    from chaosforge.interfaces.web.execution import _WebLogStream

    fake_logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.execution.log_manager", fake_logs)
    stream = _WebLogStream()

    for character in "[INFO] Validating\n":
        stream.write(character)
        stream.flush()
    stream.write("partial")
    stream.finish()

    assert [call.args[0] for call in fake_logs.append.call_args_list] == [
        "[INFO] Validating",
        "partial",
    ]


@pytest.fixture
def client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


def test_web_public_routes_and_execution_status(client, monkeypatch):
    monkeypatch.setattr(web_app, "load_metadata", lambda service: None)
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: SimpleNamespace(name="Current"))
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    logs = SimpleNamespace(
        get_logs=lambda: ["first line"],
        lines=["first line", "second line"],
        current=1,
        total=2,
        current_experiment="lambda timeout",
        running=False,
        finished=False,
    )
    monkeypatch.setattr(web_app, "get_log_manager", lambda cloud=None: logs)

    assert client.get("/").status_code == 200
    assert client.get("/cloud/aws").status_code == 200
    assert client.get("/cloud/azure").status_code == 200
    assert client.get("/cloud/unknown").status_code == 404
    assert client.get("/service/lambda").status_code == 200
    assert client.get("/experiment/lambda/timeout").status_code == 404
    assert client.get("/campaign").status_code == 200
    assert client.get("/execution").status_code == 200
    assert client.get("/execution/logs").get_json() == ["first line"]
    assert client.get("/progress").get_json() == {
        "current": 1,
        "total": 2,
        "experiment": "lambda timeout",
        "running": False,
        "finished": False,
    }
    logs = client.get("/download_logs")
    assert logs.data == b"first line\nsecond line"
    assert logs.headers["Content-Disposition"] == "attachment; filename=campaign.log"


def test_web_api_routes_and_campaign_actions(client, monkeypatch):
    selector = MagicMock()
    selector.get_resources.return_value = [{"id": "resource"}]
    selector.select_child_resources.return_value = [{"id": "child"}]
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))
    catalog = MagicMock()
    catalog.get_experiments.return_value = [{"id": "experiment"}]
    catalog.get_experiment.return_value = {"parameters": [{"name": "duration"}]}
    monkeypatch.setattr(web_app, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {"summary": "test"})
    monkeypatch.setattr(web_app, "remove_experiment", MagicMock())
    monkeypatch.setattr(web_app, "clear_current_campaign", MagicMock())

    assert client.get("/api/fis/experiments/ec2").get_json() == [{"id": "experiment"}]
    assert client.get("/api/fis/resources/ec2/eu-central-1").get_json() == [{"id": "resource"}]
    assert client.get("/api/fis/parameters/ec2/stop").get_json() == [{"name": "duration"}]
    assert client.get("/api/fis/descriptions/ec2/stop").get_json() == {"summary": "test"}
    assert client.get("/api/resources/ec2/eu-central-1").get_json() == [{"id": "resource"}]
    assert client.get("/api/resources/eks-namespace/cluster::default/eks-pod/eu-central-1").get_json() == [{"id": "child"}]
    selector.select_child_resources.assert_called_with(
        "eks-namespace", ("cluster", "default"), "eks-pod"
    )

    assert client.get("/campaign/remove/0").status_code == 302
    assert client.get("/campaign/clear").status_code == 302
    web_app.remove_experiment.assert_called_once_with(0)
    web_app.clear_current_campaign.assert_called_once_with()


def test_web_eks_container_resource_route_uses_selected_target(client, monkeypatch):
    selector = MagicMock()
    selector.select_child_resources.return_value = [{"name": "app"}]
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))

    response = client.get(
        "/api/resources/eks-namespace/cluster::apps/eks-container/eu-central-1?pod=api-1"
    )

    assert response.get_json() == [{"name": "app"}]
    selector.select_child_resources.assert_called_once_with(
        "eks-namespace", ("cluster", "apps", {"pod": "api-1", "deployment": ""}), "eks-container"
    )


def test_aks_cluster_api_requires_resource_group_and_filters_contexts(client, monkeypatch):
    aks = MagicMock()
    aks.list_contexts.return_value = ["aks-prod", "aks-other"]
    groups = MagicMock()
    groups.list_aks_cluster_names.return_value = ["aks-prod"]
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=aks))
    monkeypatch.setattr(web_app, "AzureResourceDiscovery", MagicMock(return_value=groups))

    assert client.post("/api/azure/aks/resources/azure_aks_cluster", json={}).get_json() == []
    response = client.post(
        "/api/azure/aks/resources/azure_aks_cluster",
        json={"subscription_id": "sub", "resource_group": "rg"},
    )

    assert response.get_json() == [{"id": "aks-prod", "name": "aks-prod"}]
    groups.list_aks_cluster_names.assert_called_once_with("rg")


def test_web_experiment_edit_replaces_existing_campaign_item(client, monkeypatch):
    metadata = {
        "service": "lambda",
        "experiments": [{
            "id": "timeout",
            "name": "Timeout",
            "json": "lambda-timeout-chaos.json",
            "inputs": [{"name": "lambda_name", "required": True, "type": "text"}],
        }],
    }
    stored = SimpleNamespace(
        service="lambda",
        id="timeout",
        variables={"lambda_name": "old-function"},
    )
    updated = SimpleNamespace(id="timeout", variables={"lambda_name": "new-function"})
    monkeypatch.setattr(web_app, "load_metadata", lambda _service: metadata)
    monkeypatch.setattr(web_app, "_web_experiment_metadata", lambda value, _service: value)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: {})
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(web_app, "get_experiment", lambda index: stored if index == 0 else None)
    create = MagicMock(return_value=updated)
    replace = MagicMock()
    monkeypatch.setattr(web_app, "create_experiment", create)
    monkeypatch.setattr(web_app, "update_experiment", replace)
    monkeypatch.setattr(web_app, "add_experiment", MagicMock())

    response = client.post(
        "/experiment/lambda/timeout?edit_index=0",
        data={"lambda_name": "new-function"},
    )

    assert response.status_code == 302
    create.assert_called_once()
    replace.assert_called_once_with(0, updated)
    web_app.add_experiment.assert_not_called()


def test_web_report_download_handles_missing_and_existing_report(client, monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "REPORTS_DIR", tmp_path)
    assert client.get("/report/download").status_code == 404

    report = tmp_path / "campaign.txt"
    report.write_text("report contents", encoding="utf-8")
    response = client.get("/report/download")

    assert response.status_code == 200
    assert response.data == b"report contents"
    assert "campaign.txt" in response.headers["Content-Disposition"]


def test_web_downloads_report_generated_by_report_service(client, monkeypatch, tmp_path):
    from chaosforge.reporting import report_generator

    monkeypatch.setattr(report_generator, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(web_app, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(report_generator, "show_report_summary", MagicMock())
    campaign = SimpleNamespace(
        name="Campaign",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        duration=0.0,
        experiments=[
            SimpleNamespace(
                service="lambda",
                name="Timeout",
                status="SUCCESS",
                error_message="",
            )
        ],
    )

    report_generator.generate_report(campaign)
    response = client.get("/report/download")

    assert response.status_code == 200
    assert b"CHAOSFORGE EXECUTION REPORT" in response.data


def test_web_module_entrypoint_uses_baseline_server_configuration(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(web_main.app, "run", run)
    monkeypatch.setattr(web_main.signal, "getsignal", lambda _signal: "previous")
    signal_set = MagicMock()
    monkeypatch.setattr(web_main.signal, "signal", signal_set)
    wait_for_completion = MagicMock()
    monkeypatch.setattr(web_main.executor, "wait_for_completion", wait_for_completion)

    web_main.main()

    run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False)
    wait_for_completion.assert_called_once_with()


def test_web_module_entrypoint_waits_for_cleanup_after_interrupt(monkeypatch):
    run = MagicMock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(web_main.app, "run", run)
    monkeypatch.setattr(web_main.signal, "getsignal", lambda _signal: "previous")
    signal_set = MagicMock()
    monkeypatch.setattr(web_main.signal, "signal", signal_set)
    wait_for_completion = MagicMock()
    monkeypatch.setattr(web_main.executor, "wait_for_completion", wait_for_completion)

    web_main.main()

    wait_for_completion.assert_called_once_with()


def test_web_module_entrypoint_waits_for_cloud_scoped_executors(monkeypatch):
    run = MagicMock()
    aws = web_main.executor
    azure = SimpleNamespace(wait_for_completion=MagicMock())
    monkeypatch.setattr(web_main.app, "run", run)
    monkeypatch.setattr(web_main.signal, "getsignal", lambda _signal: "previous")
    monkeypatch.setattr(web_main.signal, "signal", MagicMock())
    monkeypatch.setattr(aws, "wait_for_completion", MagicMock())
    monkeypatch.setattr(web_main, "executors", {"aws": aws, "azure": azure})

    web_main.main()

    aws.wait_for_completion.assert_called_once_with()
    azure.wait_for_completion.assert_called_once_with()


def test_web_sigterm_handler_raises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        web_main._request_graceful_shutdown(None, None)
