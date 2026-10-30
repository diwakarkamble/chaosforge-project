from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from chaosforge.models.execution import ExecutionState
from chaosforge.providers.aws.fis import runner


def _experiment(**overrides):
    variables = {
        "experiment_name": "Lambda delay",
        "description": "Controlled delay",
        "created_by": "operator@example.com",
        "service_id": "lambda",
        "experiment_id": "invocation-delay",
        "target_arn": "arn:aws:lambda:eu-central-1:123:function:processor",
        "role_arn": "arn:aws:iam::123:role/FISRole",
        "aws_region": "eu-central-1",
        "fis_config_bucket": "fis-config",
    }
    variables.update(overrides.pop("variables", {}))
    experiment_id = overrides.pop("id", "fis-create-experiment")
    return SimpleNamespace(
        id=experiment_id,
        service="fis",
        name="Invocation Delay (AWS FIS)",
        variables=variables,
        status="Pending",
        error_message="",
        **overrides,
    )


def test_direct_fis_runner_calls_native_fis_action(monkeypatch):
    dispatch = MagicMock()
    monkeypatch.setattr(runner, "execute_component_fis_action", dispatch)
    experiment = _experiment()

    context = runner.FISExperimentRunner().execute(experiment)

    assert context.state == ExecutionState.FAULT_INJECTION_SUCCEEDED
    assert experiment.status == "SUCCESS"
    assert "Direct AWS FIS SDK execution" in experiment.cli_output
    assert dispatch.call_args.args[0]["service_id"] == "lambda"
    assert dispatch.call_args.args[0]["fis_config_bucket"] == "fis-config"
    assert dispatch.call_args.args[1] is runner.create_experiment


def test_direct_fis_runner_records_native_fis_failure(monkeypatch):
    monkeypatch.setattr(runner, "execute_component_fis_action", MagicMock(side_effect=RuntimeError("FIS denied")))
    experiment = _experiment()

    context = runner.FISExperimentRunner().execute(experiment)

    assert context.state == ExecutionState.FAULT_INJECTION_FAILED
    assert experiment.status == "FAILED"
    assert experiment.error_message == "FIS denied"


def test_direct_fis_runner_keeps_unmigrated_actions_on_generic_fis_path(monkeypatch):
    dispatch = MagicMock()
    monkeypatch.setattr(runner, "execute_component_fis_action", dispatch)
    experiment = _experiment(variables={"service_id": "ec2", "experiment_id": "stop"})

    runner.FISExperimentRunner().execute(experiment)

    assert dispatch.call_args.args[0]["service_id"] == "ec2"
    assert dispatch.call_args.args[1] is runner.create_experiment


def test_direct_fis_runner_removes_recovery_file(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.tempfile, "gettempdir", lambda: str(tmp_path))

    def dispatch(variables, _create):
        Path(variables["recovery_file"]).write_text("{}", encoding="utf-8")

    monkeypatch.setattr(runner, "execute_component_fis_action", dispatch)

    runner.FISExperimentRunner().execute(_experiment())

    assert not list(tmp_path.glob("chaosforge-fis-recovery-*.json"))


def test_direct_fis_runner_dispatches_management_actions_without_definition(monkeypatch):
    action = MagicMock()
    monkeypatch.setattr(runner, "execute_management_action", action)
    experiment = _experiment(
        id="fis-start-template",
        variables={"service_id": "", "experiment_id": "", "aws_region": "eu-central-1", "experiment_template_id": "template-1"},
    )

    runner.FISExperimentRunner().execute(experiment)

    action.assert_called_once_with("fis-start-template", experiment.variables | {"recovery_file": experiment.variables["recovery_file"]})
