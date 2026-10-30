"""Component ownership dispatch for native AWS FIS catalog actions."""

from importlib import import_module


def execute(variables, create_experiment):
    """Run a component FIS action or the shared FIS template lifecycle."""
    if variables["service_id"] == "lambda":
        return import_module(
            "chaosforge.providers.aws.components.lambda.experiments.fis.actions"
        ).execute(variables)

    if variables["service_id"] == "eks":
        import_module(
            "chaosforge.providers.aws.components.eks.experiments.fis.actions"
        ).prepare(variables)

    return create_experiment(
        experiment_name=variables["experiment_name"],
        description=variables["description"],
        created_by=variables.get("created_by", "ChaosForge"),
        service_id=variables["service_id"],
        experiment_id=variables["experiment_id"],
        target_arn=variables["target_arn"],
        role_arn=variables["role_arn"],
        region=variables["aws_region"],
        recovery_file=variables.get("recovery_file", ""),
        **{
            key: value
            for key, value in variables.items()
            if key
            not in {
                "experiment_name",
                "description",
                "created_by",
                "service_id",
                "experiment_id",
                "target_arn",
                "role_arn",
                "aws_region",
                "region",
                "recovery_file",
            }
        },
    )
