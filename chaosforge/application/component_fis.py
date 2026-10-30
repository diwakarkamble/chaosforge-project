"""Component-bound metadata for native AWS FIS actions shared by interfaces."""

from copy import deepcopy
from importlib import import_module

from chaosforge.application.discovery import display_name
from chaosforge.providers.aws.fis.catalog import FISCatalog

FIS_TARGET_SELECTORS = {
    "aws:ec2:instance": "ec2",
    "aws:ec2:spot-instance": "ec2-spot",
    "aws:ec2:autoscaling-group": "autoscaling-group",
    "aws:ec2:ebs-volume": "ebs-volume",
    "aws:iam:role": "iam-role",
    "aws:ecs:task": "ecs_task",
    "aws:eks:cluster": "eks",
    "aws:eks:nodegroup": "eks-nodegroup",
    "aws:eks:pod": "eks-pod",
    "aws:kinesis:stream": "kinesis",
    "aws:s3:bucket": "s3",
    "aws:rds:db": "rds",
    "aws:rds:cluster": "rds-cluster",
    "aws:dynamodb:global-table": "dynamodb-global-table",
    "aws:elasticache:replicationgroup": "elasticache-replication-group",
    "aws:arc:zonal-shift-managed-resource": "elb",
}

FIS_TARGET_LABELS = {
    "lambda": "Lambda Function",
    "ec2": "EC2 Target",
    "rds": "RDS Target",
    "dynamodb": "DynamoDB Target",
    "elasticache": "ElastiCache Target",
    "ecs": "ECS Task",
    "elb": "Load Balancer Target",
    "eks": "EKS Target",
    "s3": "S3 Bucket",
    "kinesis": "Kinesis Target",
}


def fis_target_selector(service_id, experiment):
    """Return the ChaosForge selector type for one component FIS target."""
    resource_type = experiment.get("resource_type")
    return FIS_TARGET_SELECTORS.get(resource_type) if resource_type else service_id


def bind_component_fis(metadata, service_id, experiment_id):
    """Bind the generic FIS template contract to one component catalog action."""
    fis_experiment = FISCatalog().get_experiment(service_id, experiment_id)
    if fis_experiment is None:
        return metadata

    bound = deepcopy(metadata)
    bound["name"] = fis_experiment["name"]
    bound["fis_service_id"] = service_id
    bound["fis_experiment_id"] = experiment_id
    bound["fis_component_display_name"] = display_name(service_id)
    bound["fis_target_selector"] = fis_target_selector(service_id, fis_experiment)
    bound["inputs"] = [
        field
        for field in bound.get("inputs", [])
        if field["name"] not in {"service_id", "experiment_id", "created_by"}
    ]
    for field in bound["inputs"]:
        if field["name"] == "target_arn":
            field["label"] = FIS_TARGET_LABELS.get(service_id, f"{display_name(service_id)} Target")
            field["resource_type"] = bound["fis_target_selector"]
            break
    if service_id == "eks" and experiment_id == "pod-delete":
        bound["inputs"] = [
            field for field in bound["inputs"] if field["name"] != "target_arn"
        ]
        bound["inputs"][4:4] = [
            {"name": "eks_cluster", "label": "EKS Cluster", "type": "aws_resource", "resource_type": "eks", "return": "name", "required": True},
            {"name": "namespace", "label": "Namespace", "type": "aws_resource", "resource_type": "eks-namespace", "parent": "eks_cluster", "return": "name", "required": True},
            {"name": "pod", "label": "Pod", "type": "aws_resource", "resource_type": "eks-pod", "parent": "namespace", "return": "name", "required": True},
        ]
        bound["fis_target_selector"] = "eks-pod"
    for parameter in fis_experiment.get("parameters", []):
        field = dict(parameter)
        field["type"] = "iso8601_duration" if field["name"] == "duration" else field.get("type", "text")
        field["required"] = field.get("required", True)
        bound["inputs"].append(field)

    bound["inputs"].append(
        {"name": "created_by", "label": "Created By", "type": "text", "readonly": True, "default": ""}
    )
    if service_id == "lambda":
        bound["inputs"].extend(
            [
                {"name": "fis_config_bucket", "label": "FIS Configuration S3 Bucket", "type": "aws_resource", "resource_type": "s3", "return": "id", "required": True, "hint": "ChaosForge creates the FisConfigs/ prefix when it is missing."},
            ]
        )
    return bound


def prepare_component_fis_variables(variables):
    """Resolve component-specific FIS variables before campaign validation."""
    if variables.get("service_id") == "eks":
        import_module(
            "chaosforge.providers.aws.components.eks.experiments.fis.actions"
        ).prepare(variables)
    return variables
