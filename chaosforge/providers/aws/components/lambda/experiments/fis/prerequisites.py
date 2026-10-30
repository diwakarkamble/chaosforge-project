"""AWS SDK prerequisites for Lambda invocation FIS experiments."""

import json
import time

import boto3
from botocore.exceptions import ClientError

FIS_CONFIG_PREFIX = "FisConfigs/"
FIS_ENVIRONMENT = {
    "AWS_FIS_CONFIGURATION_LOCATION": "",
    "AWS_LAMBDA_EXEC_WRAPPER": "/opt/aws-fis/bootstrap",
    "AWS_FIS_SLOW_POLL_INTERVAL_SECONDS": "5",
}


def prepare_lambda_invocation_fis(
    function_arn, bucket_name, fis_role_arn, region
):
    """Configure a Lambda target and its roles for an AWS FIS Lambda action."""
    if not bucket_name:
        raise ValueError("Select an S3 bucket for the Lambda FIS configuration.")

    lambda_client = boto3.client("lambda", region_name=region)
    s3_client = boto3.client("s3", region_name=region)
    iam_client = boto3.client("iam", region_name=region)
    ssm_client = boto3.client("ssm", region_name=region)
    config = lambda_client.get_function_configuration(FunctionName=function_arn)
    execution_role_arn = config.get("Role", "")
    if not execution_role_arn:
        raise ValueError("The selected Lambda function has no execution role.")

    _validate_bucket_region(s3_client, bucket_name, region)
    _ensure_prefix(s3_client, bucket_name)
    _put_role_policy(iam_client, _role_name(execution_role_arn), "ChaosForgeFISLambdaS3Read", _lambda_s3_policy(bucket_name))
    _put_role_policy(iam_client, _role_name(fis_role_arn), "ChaosForgeFISLambdaS3Write", _fis_s3_policy(bucket_name))

    environment = dict(config.get("Environment", {}).get("Variables", {}))
    original_environment = {key: environment.get(key) for key in FIS_ENVIRONMENT}
    location = f"arn:aws:s3:::{bucket_name}/{FIS_CONFIG_PREFIX}"
    environment.update(FIS_ENVIRONMENT)
    environment["AWS_FIS_CONFIGURATION_LOCATION"] = location
    layers = list(config.get("Layers", []))
    layer_arn = _latest_fis_extension_layer_arn(ssm_client, region, config)
    layers = [
        layer for layer in layers if "aws-fis-extension" not in layer.get("Arn", "").lower()
    ]
    layers.append({"Arn": layer_arn})

    lambda_client.update_function_configuration(
        FunctionName=function_arn,
        Environment={"Variables": environment},
        Layers=[layer["Arn"] for layer in layers],
    )
    _wait_for_update(lambda_client, function_arn)
    return {"function_arn": function_arn, "original_environment": original_environment}


def restore_lambda_fis_environment(state, region):
    """Restore only environment variables ChaosForge changed for an auto-cleanup run."""
    if not state:
        return
    lambda_client = boto3.client("lambda", region_name=region)
    config = lambda_client.get_function_configuration(FunctionName=state["function_arn"])
    environment = dict(config.get("Environment", {}).get("Variables", {}))
    for key, value in state["original_environment"].items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    lambda_client.update_function_configuration(
        FunctionName=state["function_arn"], Environment={"Variables": environment}
    )
    _wait_for_update(lambda_client, state["function_arn"])


def lambda_s3_policy(bucket_name):
    return _lambda_s3_policy(bucket_name)


def fis_s3_policy(bucket_name):
    return _fis_s3_policy(bucket_name)


def _ensure_prefix(client, bucket_name):
    try:
        client.head_object(Bucket=bucket_name, Key=FIS_CONFIG_PREFIX)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        client.put_object(Bucket=bucket_name, Key=FIS_CONFIG_PREFIX)


def _validate_bucket_region(client, bucket_name, region):
    bucket_region = client.get_bucket_location(Bucket=bucket_name).get("LocationConstraint") or "us-east-1"
    if bucket_region != region:
        raise ValueError(
            f"S3 bucket '{bucket_name}' is in '{bucket_region}', not Lambda region '{region}'."
        )


def _latest_fis_extension_layer_arn(client, region, config):
    architecture = (config.get("Architectures") or ["x86_64"])[0]
    if architecture not in {"x86_64", "arm64"}:
        raise ValueError(f"AWS FIS Lambda extension does not support architecture '{architecture}'.")
    parameter_name = f"/aws/service/fis/lambda-extension/AWS-FIS-extension-{architecture}/1.x.x"
    try:
        layer_arn = client.get_parameter(Name=parameter_name)["Parameter"]["Value"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"AccessDenied", "AccessDeniedException"}:
            raise PermissionError(
                "AWS permissions must allow ssm:GetParameter on "
                f"{parameter_name} to resolve the latest AWS FIS extension."
            ) from exc
        raise
    expected_layer = f":layer:aws-fis-extension-{architecture}:"
    if not layer_arn.startswith(f"arn:aws:lambda:{region}:") or expected_layer not in layer_arn:
        raise ValueError(f"AWS returned an invalid FIS extension ARN from {parameter_name}.")
    return layer_arn


def _put_role_policy(client, role_name, policy_name, document):
    client.put_role_policy(RoleName=role_name, PolicyName=policy_name, PolicyDocument=json.dumps(document))


def _role_name(role_arn):
    if "/" not in role_arn:
        raise ValueError(f"Invalid IAM role ARN '{role_arn}'.")
    return role_arn.rsplit("/", 1)[-1]


def _lambda_s3_policy(bucket_name):
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": [f"arn:aws:s3:::{bucket_name}", f"arn:aws:s3:::{bucket_name}/{FIS_CONFIG_PREFIX}*"]}],
    }


def _fis_s3_policy(bucket_name):
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": ["s3:PutObject", "s3:DeleteObject"], "Resource": f"arn:aws:s3:::{bucket_name}/{FIS_CONFIG_PREFIX}*"}],
    }


def _wait_for_update(client, function_arn):
    for _ in range(15):
        status = client.get_function_configuration(FunctionName=function_arn).get("LastUpdateStatus", "Successful")
        if status == "Successful":
            return
        if status == "Failed":
            raise RuntimeError("Lambda configuration update failed.")
        time.sleep(2)
    raise TimeoutError("Lambda configuration update did not finish in time.")
