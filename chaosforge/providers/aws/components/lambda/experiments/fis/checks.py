"""Lifecycle validation for native AWS FIS Lambda experiments."""

import boto3
from botocore.exceptions import ClientError

from chaosforge.lifecycle.checks.base import ExperimentCheck

FIS_ENVIRONMENT_KEYS = (
    "AWS_FIS_CONFIGURATION_LOCATION",
    "AWS_LAMBDA_EXEC_WRAPPER",
    "AWS_FIS_SLOW_POLL_INTERVAL_SECONDS",
)


class LambdaFISCheck(ExperimentCheck):
    name = "lambda-fis-lifecycle"

    def capture(self, target):
        function_arn = target["target_arn"]
        region = target["aws_region"]
        lambda_client = boto3.client("lambda", region_name=region)
        s3_client = boto3.client("s3", region_name=region)
        iam_client = boto3.client("iam", region_name=region)
        configuration = lambda_client.get_function_configuration(FunctionName=function_arn)
        environment = configuration.get("Environment", {}).get("Variables", {})
        bucket_name = target["fis_config_bucket"]
        bucket_region = s3_client.get_bucket_location(Bucket=bucket_name).get("LocationConstraint") or "us-east-1"
        if bucket_region != region:
            raise ValueError(f"The FIS configuration bucket must be in Lambda region '{region}'.")
        try:
            s3_client.head_object(Bucket=bucket_name, Key="FisConfigs/")
            prefix_exists = True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise
            # Lambda FIS preparation creates this marker immediately before the
            # FIS template is run, so a new configuration bucket is valid.
            prefix_exists = False

        if configuration.get("State") != "Active":
            raise ValueError("The selected Lambda function must be Active.")
        if configuration.get("LastUpdateStatus", "Successful") != "Successful":
            raise ValueError("The selected Lambda function configuration must be updated successfully.")

        execution_role_arn = configuration.get("Role")
        if not execution_role_arn:
            raise ValueError("The selected Lambda function has no execution role.")
        fis_role_arn = target.get("role_arn")
        if not fis_role_arn:
            raise ValueError("A FIS execution role ARN is required.")
        iam_client.get_role(RoleName=execution_role_arn.rsplit("/", 1)[-1])
        iam_client.get_role(RoleName=fis_role_arn.rsplit("/", 1)[-1])

        return {
            "exists": True,
            "state": {
                "state": configuration.get("State"),
                "last_update_status": configuration.get("LastUpdateStatus", "Successful"),
            },
            "fis_environment": {key: environment.get(key) for key in FIS_ENVIRONMENT_KEYS},
            "layers": [layer.get("Arn") for layer in configuration.get("Layers", [])],
            "s3_configuration_prefix": prefix_exists,
            "s3_bucket_region": bucket_region,
            "roles_resolved": True,
        }

    def validate(self, target, baseline):
        try:
            current = self.capture(target)
        except Exception as exc:  # noqa: BLE001
            return {"passed": False, "error": str(exc)}

        auto_delete = str(target.get("auto_delete_template", "N")).upper() == "Y"
        if auto_delete:
            environment_matches = current["fis_environment"] == baseline["fis_environment"]
        else:
            environment_matches = (
                current["fis_environment"]["AWS_FIS_CONFIGURATION_LOCATION"]
                == f"arn:aws:s3:::{target['fis_config_bucket']}/FisConfigs/"
                and current["fis_environment"]["AWS_LAMBDA_EXEC_WRAPPER"] == "/opt/aws-fis/bootstrap"
                and current["fis_environment"]["AWS_FIS_SLOW_POLL_INTERVAL_SECONDS"] == "5"
            )

        checks = {
            "lambda_active": current["state"]["state"] == "Active",
            "lambda_configuration_updated": current["state"]["last_update_status"] == "Successful",
            "fis_environment_expected": environment_matches,
            "fis_extension_attached": any(
                "aws-fis-extension" in (layer or "").lower() for layer in current["layers"]
            ),
            "s3_configuration_prefix_reachable": current["s3_configuration_prefix"] is True,
            "s3_bucket_in_lambda_region": current["s3_bucket_region"] == target["aws_region"],
            "lambda_and_fis_roles_resolved": current["roles_resolved"] is True,
        }
        return {"passed": all(checks.values()), "baseline": baseline, "current": current, "checks": checks}
