"""Direct AWS FIS execution for Lambda component actions."""

from importlib import import_module

from chaosforge.providers.aws.fis.actions import create_experiment

_prerequisites = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.fis.prerequisites"
)
prepare_lambda_invocation_fis = _prerequisites.prepare_lambda_invocation_fis
restore_lambda_fis_environment = _prerequisites.restore_lambda_fis_environment


def execute(variables):
    """Prepare the selected Lambda and run its native AWS FIS action."""
    state = prepare_lambda_invocation_fis(
        variables["target_arn"],
        variables["fis_config_bucket"],
        variables["role_arn"],
        variables["aws_region"],
    )
    create_experiment(
        experiment_name=variables["experiment_name"],
        description=variables["description"],
        created_by=variables.get("created_by", "ChaosForge"),
        service_id="lambda",
        experiment_id=variables["experiment_id"],
        target_arn=variables["target_arn"],
        role_arn=variables["role_arn"],
        region=variables["aws_region"],
        recovery_file=variables.get("recovery_file", ""),
        cleanup=lambda: restore_lambda_fis_environment(state, variables["aws_region"]),
        **{
            key: value
            for key, value in variables.items()
            if key
            not in {
                "experiment_name", "description", "created_by", "service_id",
                "experiment_id", "target_arn", "role_arn", "aws_region", "region",
                "recovery_file",
            }
        },
    )
