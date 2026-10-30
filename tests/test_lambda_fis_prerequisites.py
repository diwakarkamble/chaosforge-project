from importlib import import_module
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

prerequisites = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.fis.prerequisites"
)
_ensure_prefix = prerequisites._ensure_prefix
_role_name = prerequisites._role_name
_validate_bucket_region = prerequisites._validate_bucket_region
_latest_fis_extension_layer_arn = prerequisites._latest_fis_extension_layer_arn
_wait_for_update = prerequisites._wait_for_update
prepare_lambda_invocation_fis = prerequisites.prepare_lambda_invocation_fis
restore_lambda_fis_environment = prerequisites.restore_lambda_fis_environment


@patch.object(prerequisites.boto3, "client")
def test_prepare_lambda_invocation_fis_configures_bucket_roles_and_function(mock_client):
    lambda_client = MagicMock()
    s3_client = MagicMock()
    iam_client = MagicMock()
    ssm_client = MagicMock()
    mock_client.side_effect = lambda service, **_: {
        "lambda": lambda_client, "s3": s3_client, "iam": iam_client, "ssm": ssm_client
    }[service]
    lambda_client.get_function_configuration.side_effect = [
        {
            "Role": "arn:aws:iam::123456789012:role/lambda-execution",
            "Environment": {"Variables": {"EXISTING": "value"}},
            "Layers": [],
            "Architectures": ["x86_64"],
            "Runtime": "python3.12",
        },
        {"LastUpdateStatus": "Successful"},
    ]
    s3_client.get_bucket_location.return_value = {"LocationConstraint": "eu-central-1"}
    s3_client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    ssm_client.get_parameter.return_value = {
        "Parameter": {"Value": "arn:aws:lambda:eu-central-1:339712832950:layer:aws-fis-extension-x86_64:411"}
    }
    state = prepare_lambda_invocation_fis(
        "arn:aws:lambda:eu-central-1:123456789012:function:processor",
        "fis-config",
        "arn:aws:iam::123456789012:role/fis-execution",
        "eu-central-1",
    )

    s3_client.put_object.assert_called_once_with(Bucket="fis-config", Key="FisConfigs/")
    assert iam_client.put_role_policy.call_count == 2
    update = lambda_client.update_function_configuration.call_args.kwargs
    assert update["Environment"]["Variables"]["AWS_FIS_CONFIGURATION_LOCATION"] == "arn:aws:s3:::fis-config/FisConfigs/"
    assert update["Layers"] == [
        "arn:aws:lambda:eu-central-1:339712832950:layer:aws-fis-extension-x86_64:411"
    ]
    ssm_client.get_parameter.assert_called_once_with(
        Name="/aws/service/fis/lambda-extension/AWS-FIS-extension-x86_64/1.x.x"
    )
    assert state["original_environment"] == {key: None for key in ["AWS_FIS_CONFIGURATION_LOCATION", "AWS_LAMBDA_EXEC_WRAPPER", "AWS_FIS_SLOW_POLL_INTERVAL_SECONDS"]}


@patch.object(prerequisites.boto3, "client")
def test_prepare_lambda_invocation_fis_reuses_attached_extension_layer(mock_client):
    lambda_client = MagicMock()
    s3_client = MagicMock()
    iam_client = MagicMock()
    ssm_client = MagicMock()
    mock_client.side_effect = lambda service, **_: {
        "lambda": lambda_client, "s3": s3_client, "iam": iam_client, "ssm": ssm_client
    }[service]
    lambda_client.get_function_configuration.side_effect = [
        {
            "Role": "arn:aws:iam::123456789012:role/lambda-execution",
            "Environment": {"Variables": {}},
            "Layers": [
                {"Arn": "arn:aws:lambda:eu-central-1:aws:layer:unrelated:1"},
                {"Arn": "arn:aws:lambda:eu-central-1:339712832950:layer:aws-fis-extension-x86_64:5"},
            ],
        },
        {"LastUpdateStatus": "Successful"},
    ]
    s3_client.get_bucket_location.return_value = {"LocationConstraint": "eu-central-1"}
    s3_client.head_object.return_value = {}
    ssm_client.get_parameter.return_value = {
        "Parameter": {"Value": "arn:aws:lambda:eu-central-1:339712832950:layer:aws-fis-extension-x86_64:411"}
    }

    prepare_lambda_invocation_fis(
        "function",
        "fis-config",
        "arn:aws:iam::123456789012:role/fis-execution",
        "eu-central-1",
    )

    assert lambda_client.update_function_configuration.call_args.kwargs["Layers"] == [
        "arn:aws:lambda:eu-central-1:aws:layer:unrelated:1",
        "arn:aws:lambda:eu-central-1:339712832950:layer:aws-fis-extension-x86_64:411",
    ]


@patch.object(prerequisites.boto3, "client")
def test_restore_lambda_fis_environment_removes_only_fis_variables(mock_client):
    client = mock_client.return_value
    client.get_function_configuration.side_effect = [
        {"Environment": {"Variables": {"EXISTING": "value", "AWS_FIS_CONFIGURATION_LOCATION": "location", "AWS_LAMBDA_EXEC_WRAPPER": "wrapper", "AWS_FIS_SLOW_POLL_INTERVAL_SECONDS": "5"}}},
        {"LastUpdateStatus": "Successful"},
    ]

    restore_lambda_fis_environment(
        {"function_arn": "function", "original_environment": {"AWS_FIS_CONFIGURATION_LOCATION": None, "AWS_LAMBDA_EXEC_WRAPPER": None, "AWS_FIS_SLOW_POLL_INTERVAL_SECONDS": None}},
        "eu-central-1",
    )

    assert client.update_function_configuration.call_args.kwargs["Environment"] == {"Variables": {"EXISTING": "value"}}


@patch.object(prerequisites.boto3, "client")
def test_prepare_lambda_invocation_fis_rejects_missing_bucket_or_execution_role(mock_client):
    with pytest.raises(ValueError, match="Select an S3 bucket"):
        prepare_lambda_invocation_fis("function", "", "arn:aws:iam::123:role/fis", "eu-central-1")

    mock_client.side_effect = lambda service, **_: MagicMock(
        get_function_configuration=lambda **__: {"Role": ""}
    )
    with pytest.raises(ValueError, match="no execution role"):
        prepare_lambda_invocation_fis("function", "bucket", "arn:aws:iam::123:role/fis", "eu-central-1")


def test_lambda_fis_prerequisite_helpers_cover_safety_paths(monkeypatch):
    client = MagicMock()
    client.get_bucket_location.return_value = {"LocationConstraint": "us-west-2"}
    with pytest.raises(ValueError, match="not Lambda region"):
        _validate_bucket_region(client, "bucket", "eu-central-1")

    client.head_object.return_value = {}
    _ensure_prefix(client, "bucket")
    client.put_object.assert_not_called()

    client.head_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject")
    with pytest.raises(ClientError):
        _ensure_prefix(client, "bucket")

    client.get_parameter.return_value = {
        "Parameter": {"Value": "arn:aws:lambda:eu-central-1:339712832950:layer:aws-fis-extension-arm64:411"}
    }
    assert _latest_fis_extension_layer_arn(
        client, "eu-central-1", {"Architectures": ["arm64"]}
    ).endswith("aws-fis-extension-arm64:411")
    assert _role_name("arn:aws:iam::123:role/team/fis") == "fis"
    with pytest.raises(ValueError, match="Invalid IAM role ARN"):
        _role_name("not-an-arn")

    client.get_function_configuration.return_value = {"LastUpdateStatus": "Failed"}
    with pytest.raises(RuntimeError, match="update failed"):
        _wait_for_update(client, "function")

    client.get_function_configuration.return_value = {"LastUpdateStatus": "InProgress"}
    monkeypatch.setattr("chaosforge.providers.aws.components.lambda.experiments.fis.prerequisites.time.sleep", lambda _: None)
    with pytest.raises(TimeoutError, match="did not finish"):
        _wait_for_update(client, "function")


def test_latest_fis_extension_layer_reports_missing_publisher_permission():
    client = MagicMock()
    client.get_parameter.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException"}}, "GetParameter"
    )

    with pytest.raises(PermissionError, match="ssm:GetParameter"):
        _latest_fis_extension_layer_arn(
            client, "eu-central-1", {"Architectures": ["x86_64"]}
        )


def test_latest_fis_extension_layer_rejects_unsupported_architecture_and_missing_versions():
    client = MagicMock()
    with pytest.raises(ValueError, match="does not support architecture"):
        _latest_fis_extension_layer_arn(client, "eu-central-1", {"Architectures": ["mips64"]})

    client.get_parameter.return_value = {"Parameter": {"Value": "unexpected"}}
    with pytest.raises(ValueError, match="invalid FIS extension ARN"):
        _latest_fis_extension_layer_arn(client, "eu-central-1", {"Architectures": ["x86_64"]})

    client.get_parameter.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException"}}, "GetParameter"
    )
    with pytest.raises(ClientError):
        _latest_fis_extension_layer_arn(client, "eu-central-1", {"Architectures": ["x86_64"]})


@patch.object(prerequisites.boto3, "client")
def test_restore_lambda_fis_environment_restores_previous_values_and_ignores_empty_state(mock_client):
    restore_lambda_fis_environment(None, "eu-central-1")
    mock_client.assert_not_called()

    client = mock_client.return_value
    client.get_function_configuration.side_effect = [
        {"Environment": {"Variables": {"AWS_FIS_CONFIGURATION_LOCATION": "new", "EXISTING": "value"}}},
        {"LastUpdateStatus": "Successful"},
    ]
    restore_lambda_fis_environment(
        {"function_arn": "function", "original_environment": {"AWS_FIS_CONFIGURATION_LOCATION": "old"}},
        "eu-central-1",
    )
    assert client.update_function_configuration.call_args.kwargs["Environment"] == {
        "Variables": {"AWS_FIS_CONFIGURATION_LOCATION": "old", "EXISTING": "value"}
    }


def test_lambda_and_fis_s3_policy_wrappers_delegate_to_shared_builders(monkeypatch):
    monkeypatch.setattr(prerequisites, "_lambda_s3_policy", lambda bucket: {"bucket": bucket, "kind": "lambda"})
    monkeypatch.setattr(prerequisites, "_fis_s3_policy", lambda bucket: {"bucket": bucket, "kind": "fis"})

    assert prerequisites.lambda_s3_policy("config-bucket") == {"bucket": "config-bucket", "kind": "lambda"}
    assert prerequisites.fis_s3_policy("config-bucket") == {"bucket": "config-bucket", "kind": "fis"}
