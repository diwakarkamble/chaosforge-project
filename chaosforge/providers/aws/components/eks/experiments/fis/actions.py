"""Direct AWS FIS target preparation for EKS component actions."""

import boto3


def prepare(variables):
    """Resolve the AWS FIS pod target ARN from the selected Kubernetes context."""
    if variables.get("experiment_id") != "pod-delete":
        return
    if variables.get("target_arn"):
        return
    account_id = boto3.client("sts", region_name=variables["aws_region"]).get_caller_identity()["Account"]
    variables["target_arn"] = (
        f"arn:aws:eks:{variables['aws_region']}:{account_id}:pod/"
        f"{variables['eks_cluster']}/{variables['namespace']}/{variables['pod']}"
    )
