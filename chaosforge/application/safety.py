"""Authoritative user-facing experiment reversibility classifications."""

IRREVERSIBLE_EXPERIMENTS = {
    ("sns", "sns-publish-message"),
    ("sns", "sns-delete-subscription"),
    ("azure_redis", "azure-redis-flush"),
    ("azure_key_vault", "azure-key-vault-increment-certificate-version"),
    ("azure_cosmos_db", "azure-cosmos-db-failover"),
    ("chaos_mesh", "chaos-mesh-schedule"),
}

IRREVERSIBLE_FIS_EXPERIMENTS = {
    ("ec2", "terminate-instances"),
    ("ec2", "spot-instance-interruption"),
    ("ecs", "stop-task"),
    ("eks", "terminate-nodegroup-instances"),
    ("rds", "failover-db-cluster"),
}


def reversibility(service, experiment_id, variables=None):
    """Return the installed catalog's safety classification for an experiment."""
    service = str(service or "")
    experiment_id = str(experiment_id or "")
    if service == "fis":
        variables = variables or {}
        key = (str(variables.get("service_id") or ""), str(variables.get("experiment_id") or ""))
        return "irreversible" if key in IRREVERSIBLE_FIS_EXPERIMENTS else "reversible"
    return "irreversible" if (service, experiment_id) in IRREVERSIBLE_EXPERIMENTS else "reversible"


def irreversible_experiments(campaign):
    """Return experiments that require an explicit irreversible-operation acknowledgement."""
    return [
        experiment
        for experiment in getattr(campaign, "experiments", [])
        if reversibility(
            getattr(experiment, "service", ""),
            getattr(experiment, "id", ""),
            getattr(experiment, "variables", {}),
        )
        == "irreversible"
    ]
