"""Canonical duplicate detection for executable campaign experiments."""

import json


def experiment_fingerprint(experiment):
    """Identify an experiment by configuration, excluding mutable execution outcome."""
    if isinstance(experiment, dict):
        value = experiment.get
    else:
        def value(name, default=None):
            return getattr(experiment, name, default)

    service = value("service", "")
    experiment_id = value("id", "")
    if not str(service).strip() or not str(experiment_id).strip():
        return None
    return json.dumps(
        {
            "service": service,
            "id": experiment_id,
            "engine": value("engine", "Chaos Toolkit"),
            "target_service": value("target_service", ""),
            "variables": value("variables", {}),
        },
        sort_keys=True,
        default=str,
    )


def duplicate_experiment_indexes(experiments):
    """Return duplicate and original indexes for executable experiment configurations."""
    indexes = {}
    duplicates = []
    for index, experiment in enumerate(experiments):
        if (fingerprint := experiment_fingerprint(experiment)) is None:
            continue
        if fingerprint in indexes:
            duplicates.append((index, indexes[fingerprint]))
        else:
            indexes[fingerprint] = index
    return duplicates
