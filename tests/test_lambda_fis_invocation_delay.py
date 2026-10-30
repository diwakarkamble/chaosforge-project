from importlib import import_module
from unittest.mock import MagicMock

import pytest

invocation_delay = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.fis.actions"
)


def _variables(auto_delete_template="Y"):
    return {
        "experiment_name": "Lambda delay",
        "description": "Controlled delay",
        "created_by": "operator@example.com",
        "experiment_id": "invocation-delay",
        "target_arn": "arn:aws:lambda:eu-central-1:123:function:processor",
        "role_arn": "arn:aws:iam::123:role/FISRole",
        "aws_region": "eu-central-1",
        "fis_config_bucket": "fis-config",
        "auto_delete_template": auto_delete_template,
    }


def test_lambda_fis_action_owns_lambda_preparation_and_cleanup(monkeypatch):
    prepare = MagicMock(return_value={"function_arn": "function", "original_environment": {}})
    restore = MagicMock()
    action = MagicMock()
    monkeypatch.setattr(invocation_delay, "prepare_lambda_invocation_fis", prepare)
    monkeypatch.setattr(invocation_delay, "restore_lambda_fis_environment", restore)
    monkeypatch.setattr(invocation_delay, "create_experiment", action)

    invocation_delay.execute(_variables())

    prepare.assert_called_once_with(
        "arn:aws:lambda:eu-central-1:123:function:processor",
        "fis-config",
        "arn:aws:iam::123:role/FISRole",
        "eu-central-1",
    )
    assert action.call_args.kwargs["service_id"] == "lambda"
    assert action.call_args.kwargs["experiment_id"] == "invocation-delay"
    action.call_args.kwargs["cleanup"]()
    restore.assert_called_once_with(prepare.return_value, "eu-central-1")


def test_lambda_fis_action_does_not_run_generic_action_when_preparation_fails(monkeypatch):
    monkeypatch.setattr(
        invocation_delay, "prepare_lambda_invocation_fis", MagicMock(side_effect=RuntimeError("layer unavailable"))
    )
    action = MagicMock()
    monkeypatch.setattr(invocation_delay, "create_experiment", action)

    with pytest.raises(RuntimeError, match="layer unavailable"):
        invocation_delay.execute(_variables())

    action.assert_not_called()
