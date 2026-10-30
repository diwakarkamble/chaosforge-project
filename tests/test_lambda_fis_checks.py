from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

checks = import_module("chaosforge.providers.aws.components.lambda.experiments.fis.checks")
from chaosforge.lifecycle.checks.resolver import CheckResolver


def _target(auto_delete="Y"):
    return {
        "target_arn": "arn:aws:lambda:eu-central-1:123:function:processor",
        "aws_region": "eu-central-1",
        "fis_config_bucket": "fis-config",
        "role_arn": "arn:aws:iam::123456789012:role/FISRole",
        "auto_delete_template": auto_delete,
    }


def _configuration(environment):
    return {
        "State": "Active",
        "LastUpdateStatus": "Successful",
        "Role": "arn:aws:iam::123456789012:role/lambda-execution",
        "Environment": {"Variables": environment},
        "Layers": [{"Arn": "arn:aws:lambda:eu-central-1:339712832950:layer:aws-fis-extension-x86_64:411"}],
    }


def _clients(monkeypatch, configurations):
    lambda_client = MagicMock()
    lambda_client.get_function_configuration.side_effect = configurations
    s3_client = MagicMock()
    s3_client.get_bucket_location.return_value = {"LocationConstraint": "eu-central-1"}
    iam_client = MagicMock()
    monkeypatch.setattr(
        checks.boto3,
        "client",
        lambda service, **_: {"lambda": lambda_client, "s3": s3_client, "iam": iam_client}[service],
    )
    return lambda_client, s3_client, iam_client


def test_lambda_fis_check_captures_baseline_and_validates_auto_cleanup(monkeypatch):
    baseline_environment = {"EXISTING": "value"}
    _clients(monkeypatch, [_configuration(baseline_environment), _configuration(baseline_environment)])
    check = checks.LambdaFISCheck()

    baseline = check.capture(_target())
    result = check.validate(_target(), baseline)

    assert baseline["fis_environment"] == {
        "AWS_FIS_CONFIGURATION_LOCATION": None,
        "AWS_LAMBDA_EXEC_WRAPPER": None,
        "AWS_FIS_SLOW_POLL_INTERVAL_SECONDS": None,
    }
    assert result["passed"] is True
    assert all(result["checks"].values())


def test_lambda_fis_check_requires_configuration_when_template_is_retained(monkeypatch):
    environment = {
        "AWS_FIS_CONFIGURATION_LOCATION": "arn:aws:s3:::fis-config/FisConfigs/",
        "AWS_LAMBDA_EXEC_WRAPPER": "/opt/aws-fis/bootstrap",
        "AWS_FIS_SLOW_POLL_INTERVAL_SECONDS": "5",
    }
    _clients(monkeypatch, [_configuration(environment), _configuration(environment)])
    check = checks.LambdaFISCheck()
    target = _target(auto_delete="N")

    result = check.validate(target, check.capture(target))

    assert result["passed"] is True
    assert result["checks"]["fis_environment_expected"] is True


def test_lambda_fis_check_allows_a_missing_prefix_during_precheck(monkeypatch):
    _, s3_client, _ = _clients(monkeypatch, [_configuration({})])
    s3_client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    baseline = checks.LambdaFISCheck().capture(_target())

    assert baseline["s3_configuration_prefix"] is False


def test_lambda_fis_check_preserves_non_missing_prefix_errors(monkeypatch):
    _, s3_client, _ = _clients(monkeypatch, [_configuration({})])
    s3_client.head_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject")

    result = checks.LambdaFISCheck().validate(_target(), {"fis_environment": {}})

    assert result["passed"] is False
    assert "AccessDenied" in result["error"]


def test_lambda_fis_check_reports_missing_extension_or_s3_prefix_after_execution(monkeypatch):
    configuration = _configuration({})
    configuration["Layers"] = []
    lambda_client, s3_client, _ = _clients(monkeypatch, [configuration])
    s3_client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    result = checks.LambdaFISCheck().validate(_target(), {"fis_environment": {}})

    assert result["passed"] is False
    assert result["checks"]["s3_configuration_prefix_reachable"] is False
    lambda_client.get_function_configuration.assert_called_once()


def test_lambda_fis_check_rejects_bucket_in_a_different_region(monkeypatch):
    _, s3_client, _ = _clients(monkeypatch, [_configuration({})])
    s3_client.get_bucket_location.return_value = {"LocationConstraint": "us-east-1"}

    with pytest.raises(ValueError, match="must be in Lambda region"):
        checks.LambdaFISCheck().capture(_target())


def test_lambda_fis_check_rejects_inactive_or_updating_lambda(monkeypatch):
    inactive = _configuration({})
    inactive["State"] = "Pending"
    _clients(monkeypatch, [inactive])
    with pytest.raises(ValueError, match="must be Active"):
        checks.LambdaFISCheck().capture(_target())

    updating = _configuration({})
    updating["LastUpdateStatus"] = "InProgress"
    _clients(monkeypatch, [updating])
    with pytest.raises(ValueError, match="updated successfully"):
        checks.LambdaFISCheck().capture(_target())


def test_lambda_fis_check_requires_lambda_and_fis_roles(monkeypatch):
    missing_lambda_role = _configuration({})
    missing_lambda_role.pop("Role")
    _clients(monkeypatch, [missing_lambda_role])
    with pytest.raises(ValueError, match="no execution role"):
        checks.LambdaFISCheck().capture(_target())

    _clients(monkeypatch, [_configuration({})])
    target = _target()
    target.pop("role_arn")
    with pytest.raises(ValueError, match="FIS execution role ARN"):
        checks.LambdaFISCheck().capture(target)


def test_resolver_registers_lambda_fis_check_for_all_lambda_fis_actions():
    for experiment_id in ("invocation-delay", "invocation-error", "http-response"):
        check = CheckResolver().resolve(
            SimpleNamespace(
                id="fis-create-experiment",
                variables={"service_id": "lambda", "experiment_id": experiment_id},
            )
        )
        assert isinstance(check, checks.LambdaFISCheck)
