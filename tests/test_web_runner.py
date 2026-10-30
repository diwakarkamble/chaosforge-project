from types import SimpleNamespace
from unittest.mock import MagicMock

from chaosforge.interfaces.web.execution import WebExecution
from chaosforge.interfaces.web.runner import WebExperimentRunner


def _experiment(status="Pending"):
    return SimpleNamespace(
        id="lambda-timeout",
        name="Lambda Timeout",
        service="lambda",
        variables={"aws_region": "eu-central-1"},
        status=status,
        error_message="",
    )


def test_execute_delegates_to_shared_lifecycle_service(monkeypatch):
    experiment = _experiment()
    service = MagicMock()
    expected = object()
    service.execute_experiment.return_value = expected
    runner = WebExperimentRunner(lifecycle_service=service)
    logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.runner.log_manager", logs)

    assert runner.execute(experiment) is expected
    service.execute_experiment.assert_called_once_with(experiment)
    logs.append.assert_called_with("Experiment Completed Successfully")


def test_execute_logs_shared_lifecycle_failure(monkeypatch):
    experiment = _experiment(status="FAILED")
    experiment.error_message = "provider failed"
    service = MagicMock()
    runner = WebExperimentRunner(lifecycle_service=service)
    logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.runner.log_manager", logs)

    runner.execute(experiment)

    assert "Experiment Failed" in [call.args[0] for call in logs.append.call_args_list]
    assert "Error: provider failed" in [call.args[0] for call in logs.append.call_args_list]


def test_execute_logs_warning_details_without_marking_experiment_failed(monkeypatch):
    experiment = _experiment(status="SUCCESS_WITH_WARNINGS")
    experiment.warnings = [
        {
            "label": "Probe Failures Stopped (post)",
            "detail": "Recent Unhealthy probe events remain.",
        }
    ]
    logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.runner.log_manager", logs)

    WebExperimentRunner(lifecycle_service=MagicMock()).execute(experiment)

    lines = [call.args[0] for call in logs.append.call_args_list]
    assert "Experiment Completed With Warnings" in lines
    assert "Warning: Probe Failures Stopped (post): Recent Unhealthy probe events remain." in lines


def test_web_execution_after_experiment_tolerates_missing_or_failed_outcome_sync(monkeypatch):
    execution = WebExecution()
    logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.execution.log_manager", logs)
    monkeypatch.setattr(
        "chaosforge.interfaces.web.execution._update_experiment_session", MagicMock()
    )
    experiment = _experiment(status="SUCCESS")

    execution._after_experiment("run-a", experiment, None)
    execution._after_experiment(
        "run-a",
        experiment,
        MagicMock(side_effect=RuntimeError("draft storage unavailable")),
    )

    assert any(
        "Could not update the active campaign outcome: draft storage unavailable" in call.args[0]
        for call in logs.append.call_args_list
    )


def test_web_execute_delegates_aks_without_provider_specific_override(monkeypatch):
    experiment = SimpleNamespace(
        id="aks-pod-kill",
        name="Pod Kill",
        service="aks",
        variables={"aks_context": "cluster", "namespace": "apps"},
        status="Pending",
        error_message="",
    )
    service = MagicMock()
    service.execute_experiment.return_value = object()
    logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.runner.log_manager", logs)

    WebExperimentRunner(lifecycle_service=service).execute(experiment)

    service.execute_experiment.assert_called_once_with(experiment)


def test_execute_campaign_uses_shared_callbacks_and_report(monkeypatch):
    experiments = [_experiment(), _experiment()]
    campaign = SimpleNamespace(experiments=experiments)
    aggregate = SimpleNamespace(status="SUCCESS", executed=experiments, failed=[])
    service = MagicMock()
    before_experiment = MagicMock()
    after_experiment = MagicMock()

    def execute_campaign(campaign_arg, **kwargs):
        for index, experiment in enumerate(campaign_arg.experiments, start=1):
            kwargs["before_experiment"](index, 2, experiment)
            experiment.status = "SUCCESS"
            kwargs["after_experiment"](index, 2, experiment, object())
        return aggregate

    service.execute_campaign.side_effect = execute_campaign
    runner = WebExperimentRunner(
        lifecycle_service=service,
        before_experiment=before_experiment,
        after_experiment=after_experiment,
    )
    logs = MagicMock()
    report = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.runner.log_manager", logs)
    monkeypatch.setattr("chaosforge.interfaces.web.runner.generate_report", report)

    result = runner.execute_campaign(campaign)

    assert result is aggregate
    assert logs.current == 2
    assert logs.current_experiment == "Campaign SUCCESS"
    report.assert_called_once_with(campaign, show_summary=False)
    assert before_experiment.call_args_list == [
        ((1, experiments[0]),),
        ((2, experiments[1]),),
    ]
    assert after_experiment.call_args_list == [
        ((1, experiments[0]),),
        ((2, experiments[1]),),
    ]
    assert "Mission Summary" in [call.args[0] for call in logs.append.call_args_list]


def test_execute_campaign_logs_the_specific_failed_action_error(monkeypatch):
    experiment = _experiment(status="FAILED")
    experiment.error_message = "Capture and Remove Rule: ValueError: Selected security group rule is unavailable."
    campaign = SimpleNamespace(experiments=[experiment])
    aggregate = SimpleNamespace(status="FAILED", executed=[experiment], failed=[experiment])
    service = MagicMock()

    def execute_campaign(campaign_arg, **kwargs):
        kwargs["before_experiment"](1, 1, experiment)
        kwargs["after_experiment"](1, 1, experiment, object())
        return aggregate

    service.execute_campaign.side_effect = execute_campaign
    logs = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.web.runner.log_manager", logs)
    monkeypatch.setattr("chaosforge.interfaces.web.runner.generate_report", MagicMock())

    WebExperimentRunner(lifecycle_service=service).execute_campaign(campaign)

    lines = [call.args[0] for call in logs.append.call_args_list]
    assert "Result: FAILED" in lines
    assert f"Error: {experiment.error_message}" in lines


def test_execute_campaign_propagates_report_failure(monkeypatch):
    service = MagicMock()
    service.execute_campaign.return_value = SimpleNamespace(
        status="SUCCESS", executed=[], failed=[]
    )
    runner = WebExperimentRunner(lifecycle_service=service)
    monkeypatch.setattr(
        "chaosforge.interfaces.web.runner.generate_report",
        MagicMock(side_effect=OSError("report failed")),
    )

    try:
        runner.execute_campaign(SimpleNamespace(experiments=[]))
    except OSError as exc:
        assert str(exc) == "report failed"
    else:
        raise AssertionError("Expected report generation error")
