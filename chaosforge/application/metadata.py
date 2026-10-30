from chaosforge.catalog import ExperimentCatalog


def load_service_metadata(service):

    return ExperimentCatalog().load_service(service)


def get_experiments(service):

    metadata = load_service_metadata(service)

    if not metadata:
        return []

    return [
        experiment
        for experiment in metadata.get("experiments", [])
        if not (service == "fis" and experiment.get("internal"))
    ]


def get_experiment(service, experiment_id):

    for experiment in get_experiments(service):
        if experiment["id"] == experiment_id:
            return experiment

    if service == "fis" and experiment_id == "fis-create-experiment":
        metadata = load_service_metadata(service) or {}
        return next(
            (
                experiment
                for experiment in metadata.get("experiments", [])
                if experiment.get("id") == experiment_id
            ),
            None,
        )

    return None
