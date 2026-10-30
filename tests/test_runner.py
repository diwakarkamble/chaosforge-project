import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from chaoslib.exceptions import InvalidExperiment
from chaoslib.experiment import run_experiment as library_run_experiment
from chaoslib.types import Strategy

from chaosforge.engines.chaos_toolkit.runner import (
    ExperimentRunner,
    _attempt_direct_recovery,
    _fis_action_parameters,
    _journal_failure_detail,
    _journal_has_failed_action,
    _journal_rollback_completed,
    _run_library_experiment,
)
from chaosforge.models.execution import ExecutionState


def _experiment(**overrides):
    values = {
        "id": "test-id",
        "service": "lambda",
        "name": "Memory",
        "engine": "Chaos Toolkit",
        "json_file": "memory.json",
        "variables": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fis_action_parameter_payload_supports_every_catalog_parameter():
    from chaosforge.providers.aws.fis.catalog import FISCatalog

    for service in FISCatalog().get_services():
        for experiment in service["experiments"]:
            expected = {
                parameter["name"]: f"value-{index}"
                for index, parameter in enumerate(experiment.get("parameters", []))
            }
            assert _fis_action_parameters({
                "service_id": service["id"], "experiment_id": experiment["id"], **expected
            }) == expected


def test_execute_uses_library_loader_validator_runner_and_journal(monkeypatch):
    definition = {"title": "Memory", "description": "Test", "method": []}
    journal = {
        "status": "completed",
        "steady_states": {"before": {"steady_state_met": True}},
        "run": [{"status": "succeeded"}],
        "rollbacks": [],
    }
    load = MagicMock(return_value=definition)
    validate = MagicMock()
    run = MagicMock(return_value=journal)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", load)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", validate)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", run)
    experiment = _experiment(variables={"memory": "1024"})

    context = ExperimentRunner().execute(experiment)

    load.assert_called_once_with("memory.json")
    validate.assert_called_once_with(definition)
    run.assert_called_once_with(definition, experiment_vars=({"memory": "1024"}, None))
    assert context.state == ExecutionState.FAULT_INJECTION_SUCCEEDED
    assert experiment.status == "SUCCESS"
    assert "Chaos Toolkit library" in experiment.cli_output


def test_execute_converts_local_iso_duration_before_running_toolkit(monkeypatch):
    run = MagicMock(return_value={"status": "completed", "steady_states": {"before": {"steady_state_met": True}}, "run": [], "rollbacks": []})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", run)
    experiment = _experiment(variables={"wait_seconds": "PT5M", "duration": "PT1M"})

    ExperimentRunner().execute(experiment)

    assert run.call_args.kwargs["experiment_vars"][0] == {"wait_seconds": 300, "duration": "PT1M"}
    assert experiment.variables == {"wait_seconds": "PT5M", "duration": "PT1M"}


def test_execute_converts_aks_iso_duration_to_seconds(monkeypatch):
    run = MagicMock(return_value={"status": "completed", "steady_states": {"before": {"steady_state_met": True}}, "run": [], "rollbacks": []})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", run)

    ExperimentRunner().execute(_experiment(service="aks", variables={"duration": "PT2M"}))

    assert run.call_args.kwargs["experiment_vars"][0]["duration"] == 120


def test_execute_preserves_campaign_variables_when_toolkit_consumes_run_configuration(monkeypatch):
    original_variables = {
        "bucket_name": "demo-bucket",
        "aws_region": "eu-west-1",
        "policy_template": "readonly",
        "wait_seconds": 1,
    }

    def run(_definition, *, experiment_vars):
        variables, _secrets = experiment_vars
        variables.clear()
        return {
            "status": "completed",
            "steady_states": {"before": {"steady_state_met": True}},
            "run": [{"status": "succeeded"}],
            "rollbacks": [],
        }

    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", run)
    experiment = _experiment(service="s3", variables=dict(original_variables))

    ExperimentRunner().execute(experiment)
    ExperimentRunner().execute(experiment)

    assert experiment.status == "SUCCESS"
    assert experiment.variables == original_variables


@pytest.mark.parametrize(
    ("journal", "expected"),
    [
        ({"status": "completed", "run": [{"status": "failed"}], "rollbacks": []}, "Chaos Toolkit completed"),
        ({"status": "aborted", "run": [], "rollbacks": []}, "Chaos Toolkit execution failed"),
    ],
)
def test_execute_maps_library_journal_failures(monkeypatch, journal, expected):
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", lambda *_args, **_kwargs: journal)
    experiment = _experiment()

    context = ExperimentRunner().execute(experiment)

    assert context.state == ExecutionState.FAULT_INJECTION_FAILED
    assert expected in experiment.error_message


def test_execute_treats_post_check_only_rollback_failure_as_success(monkeypatch):
    journal = {
        "status": "completed",
        "steady_states": {"before": {"steady_state_met": True}, "after": {"steady_state_met": True}},
        "run": [{"status": "succeeded", "activity": {"name": "inject"}}],
        "rollbacks": [{
            "status": "failed", "activity": {"name": "cleanup"},
            "exception": ["RuntimeError: Post-experiment checks failed: ['health']"],
        }],
    }
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", lambda *_args, **_kwargs: journal)
    experiment = _experiment()

    ExperimentRunner().execute(experiment)

    assert experiment.status == "SUCCESS"


def test_execute_fails_when_rollback_journal_reports_a_genuine_failure(monkeypatch):
    journal = {
        "status": "completed",
        "steady_states": {"before": {"steady_state_met": True}},
        "run": [{"status": "succeeded", "activity": {"name": "inject"}}],
        "rollbacks": [{"status": "failed", "activity": {"name": "cleanup"}}],
    }
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", lambda *_args, **_kwargs: journal)
    experiment = _experiment()

    ExperimentRunner().execute(experiment)

    assert "Rollback step(s) failed: cleanup" in experiment.error_message


def test_execute_handles_library_validation_error(monkeypatch):
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr(
        "chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid",
        MagicMock(side_effect=InvalidExperiment("invalid definition")),
    )
    experiment = _experiment()

    context = ExperimentRunner().execute(experiment)

    assert context.state == ExecutionState.FAULT_INJECTION_FAILED
    assert experiment.error_message == "invalid definition"


def test_execute_preserves_fis_variables_for_the_library(monkeypatch):
    run = MagicMock(return_value={"status": "completed", "run": [], "rollbacks": []})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", run)
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner._fis_action_parameters", lambda _: {"count": 2})
    experiment = _experiment(engine="AWS FIS", service="fis", variables={})

    ExperimentRunner().execute(experiment)

    variables, secrets = run.call_args.kwargs["experiment_vars"]
    assert variables["fis_action_parameters_json"] == '{"count":2}'
    assert "recovery_file" in variables
    assert secrets is None


def test_vpc_security_group_definition_runs_with_library_configuration_variables(monkeypatch, tmp_path):
    from chaosforge.catalog import ExperimentCatalog
    from chaosforge.providers.aws.components.vpc.experiments.toolkit.actions import (
        vpc_security_group_actions,
    )

    client = MagicMock()
    rule = {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "10.0.0.0/8"}]}
    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [rule]}]
    }
    monkeypatch.setattr(vpc_security_group_actions, "get_client", lambda _: client)
    monkeypatch.setattr(vpc_security_group_actions, "STATE_FILE", str(tmp_path / "security-group.json"))
    monkeypatch.setattr("builtins.input", lambda _: "1")
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.run_experiment", library_run_experiment)
    definition = ExperimentCatalog().definition_path("vpc", "vpc-security-group-chaos.json")
    experiment = _experiment(
        service="vpc",
        json_file=str(definition),
        variables={"security_group_id": "sg-test", "aws_region": "eu-west-1", "selected_rule": "0", "wait_seconds": "0"},
    )

    context = ExperimentRunner().execute(experiment)

    assert context.state == ExecutionState.FAULT_INJECTION_SUCCEEDED
    client.revoke_security_group_ingress.assert_called_once_with(GroupId="sg-test", IpPermissions=[rule])
    client.authorize_security_group_ingress.assert_called_once_with(GroupId="sg-test", IpPermissions=[rule])


def test_toolkit_experiment_factory_supplies_legacy_region_alias():
    from chaosforge.application.campaigns.factory import create_experiment

    metadata = {"id": "capacity", "name": "Capacity", "json": "dynamodb-capacity-chaos.json"}
    experiment = create_experiment(
        "dynamodb", metadata, {"aws_region": "eu-west-1"}
    )

    assert experiment.variables["aws_region"] == "eu-west-1"
    assert experiment.variables["region"] == "eu-west-1"


def test_library_runner_skips_signal_registration_in_worker_threads(monkeypatch):
    runner = MagicMock()
    runner.strategy = Strategy.DEFAULT
    runner.schedule = MagicMock()
    runner.config = {"configured": True}
    runner.secrets = {}
    runner.settings = {}
    runner.event_registry = MagicMock()
    runner._run.return_value = {"status": "completed"}
    runner_context = MagicMock()
    runner_context.__enter__.return_value = runner
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.Runner", MagicMock(return_value=runner_context))
    monkeypatch.setattr(
        "chaosforge.engines.chaos_toolkit.runner.run_experiment",
        MagicMock(side_effect=AssertionError("signal-enabled API must not run in a worker thread")),
    )
    result = []

    thread = threading.Thread(
        target=lambda: result.append(_run_library_experiment({"method": []}, {"key": "value"})),
    )
    thread.start()
    thread.join()

    assert result == [{"status": "completed"}]
    runner.configure.assert_called_once_with({"method": []}, None, ({"key": "value"}, None))
    runner._run.assert_called_once()


def test_every_toolkit_catalog_family_uses_the_thread_safe_runner_path(monkeypatch):
    from chaosforge.application.campaigns.factory import create_experiment
    from chaosforge.application.discovery import discover_services
    from chaosforge.application.metadata import get_experiments

    journal = {
        "status": "completed",
        "steady_states": {"before": {"steady_state_met": True}},
        "run": [{"status": "succeeded"}],
        "rollbacks": [],
    }
    services = [service for service in discover_services("aws") if service != "kinesis"] + ["aks"]
    for service in services:
        metadata = get_experiments(service)[0]
        variables = {
            field["name"]: field.get("default", "value")
            for field in metadata.get("inputs", [])
        }
        if service == "aks":
            variables.update({"aks_context": "ctx", "namespace": "default", "deployment": "app"})
        experiment = create_experiment(service, metadata, variables)
        runner = MagicMock()
        runner.strategy = Strategy.DEFAULT
        runner.schedule = MagicMock()
        runner.config = {}
        runner.secrets = {}
        runner.settings = {}
        runner.event_registry = MagicMock()
        runner._run.return_value = journal
        runner_context = MagicMock()
        runner_context.__enter__.return_value = runner
        monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
        monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
        monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.Runner", MagicMock(return_value=runner_context))
        monkeypatch.setattr(
            "chaosforge.engines.chaos_toolkit.runner.run_experiment",
            MagicMock(side_effect=AssertionError("worker thread must not register signal handlers")),
        )
        results = []

        thread = threading.Thread(target=lambda: results.append(ExperimentRunner().execute(experiment)))
        thread.start()
        thread.join()

        assert results[0].state == ExecutionState.FAULT_INJECTION_SUCCEEDED
        expected_variables = dict(experiment.variables)
        for name in ("wait_seconds", "duration_seconds", "fault_duration_seconds"):
            if name in expected_variables and isinstance(expected_variables[name], str):
                from chaosforge.application.duration import duration_seconds

                expected_variables[name] = duration_seconds(expected_variables[name])
        if service == "aks" and isinstance(expected_variables.get("duration"), str):
            from chaosforge.application.duration import duration_seconds

            expected_variables["duration"] = duration_seconds(
                expected_variables["duration"]
            )
        runner.configure.assert_called_once_with({}, None, (expected_variables, None))


def test_aws_toolkit_definitions_require_only_catalog_or_standardized_values():
    from chaosforge.application.discovery import discover_services
    from chaosforge.application.metadata import get_experiments
    from chaosforge.catalog import ExperimentCatalog

    catalog = ExperimentCatalog()
    standardized = {"aws_region", "region", "device_name", "rule_index"}
    unresolved = []
    for service in discover_services("aws"):
        if service == "kinesis":
            continue
        for metadata in get_experiments(service):
            definition = json.loads(
                catalog.definition_path(service, metadata["json"]).read_text(encoding="utf-8")
            )
            inputs = {field["name"] for field in metadata.get("inputs", [])}
            missing = {
                name
                for name, default in definition.get("configuration", {}).items()
                if default is None and name not in inputs and name not in standardized
            }
            if missing:
                unresolved.append((service, metadata["id"], missing))

    assert unresolved == []


def test_aws_web_resource_fields_do_not_submit_raw_objects():
    from chaosforge.application.discovery import discover_services
    from chaosforge.application.metadata import get_experiments

    object_return_fields = {"rule", "route"}
    violations = []
    for service in discover_services("aws"):
        if service == "kinesis":
            continue
        for metadata in get_experiments(service):
            for field in metadata.get("inputs", []):
                if field.get("type") == "aws_resource" and field.get("return") in object_return_fields:
                    violations.append((service, metadata["id"], field["name"], field["return"]))

    assert violations == []


def test_execute_handles_interrupted_library_journal(monkeypatch):
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr(
        "chaosforge.engines.chaos_toolkit.runner.run_experiment",
        lambda *_args, **_kwargs: {"status": "interrupted", "interrupted": True, "rollbacks": [{"status": "succeeded"}]},
    )
    experiment = _experiment(service="aks", engine="Azure Chaos Studio")

    context = ExperimentRunner().execute(experiment)

    assert context.state == ExecutionState.ABORTED_BY_USER
    assert context.recovery["passed"] is True


def test_execute_handles_direct_library_keyboard_interrupt(monkeypatch):
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.load_experiment", lambda _: {})
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner.ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr(
        "chaosforge.engines.chaos_toolkit.runner.run_experiment",
        MagicMock(side_effect=KeyboardInterrupt),
    )
    monkeypatch.setattr("chaosforge.engines.chaos_toolkit.runner._attempt_direct_recovery", lambda *_: True)
    experiment = _experiment(engine="AWS FIS", service="fis")

    context = ExperimentRunner().execute(experiment)

    assert context.state == ExecutionState.ABORTED_BY_USER
    assert "recovery succeeded" in experiment.error_message


def test_journal_helpers_and_direct_recovery():
    assert _journal_rollback_completed({"rollbacks": [{"status": "succeeded"}]}) is True
    assert _journal_rollback_completed({"rollbacks": [{"status": "failed"}]}) is False
    assert _journal_has_failed_action({
        "run": [{"status": "failed"}],
        "rollbacks": [{"status": "succeeded"}],
    }) is True
    assert _journal_failure_detail({
        "run": [{
            "status": "failed",
            "activity": {"name": "remove-rule"},
            "exception": ["Traceback\n", "ValueError: Selected security group rule is unavailable.\n"],
        }],
        "rollbacks": [],
    }) == "remove-rule: ValueError: Selected security group rule is unavailable."

    experiment = _experiment(engine="AWS FIS", variables={"region": "eu-west-1"})
    with patch("chaosforge.providers.aws.fis.actions.recover_interrupted_experiment", return_value={"success": True, "messages": ["recovered"]}):
        assert _attempt_direct_recovery(experiment, []) is True


def test_journal_helpers_ignore_successful_activities():
    journal = {
        "run": [{"status": "succeeded"}],
        "rollbacks": [{"status": "succeeded"}],
    }

    assert _journal_has_failed_action(journal) is False
    assert _journal_failure_detail(journal) == ""


def test_legacy_output_failure_parser_remains_conservative():
    assert ExperimentRunner._contains_failed_action(
        "ordinary output\n=> failed: real action error"
    ) is True
    assert ExperimentRunner._contains_failed_action(
        "=> failed: Post-experiment checks failed: ['diagnostic']"
    ) is False


@patch("chaosforge.engines.chaos_toolkit.runner.show_campaign_complete")
@patch("chaosforge.engines.chaos_toolkit.runner.show_experiment")
@patch("chaosforge.engines.chaos_toolkit.runner.show_campaign_start")
@patch.object(ExperimentRunner, "execute")
def test_execute_campaign_honors_continue_on_failure(mock_execute, _start, _show, _complete):
    first = SimpleNamespace(status="FAILED")
    second = SimpleNamespace(status="Pending")
    campaign = SimpleNamespace(experiments=[first, second], continue_on_failure=False)

    ExperimentRunner().execute_campaign(campaign)

    mock_execute.assert_called_once_with(first)
