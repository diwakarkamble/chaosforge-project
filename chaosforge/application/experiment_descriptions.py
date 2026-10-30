import json
import os

from chaosforge.catalog import ExperimentCatalog
from chaosforge.common.paths import repository_paths

DESCRIPTION_PATH = str(
    repository_paths().root / "chaosforge" / "catalog" / "descriptions.json"
)


def load_experiment_descriptions():
    """Load centralized experiment descriptions."""

    if not os.path.exists(DESCRIPTION_PATH):
        return {}

    with open(DESCRIPTION_PATH, "r", encoding="utf-8-sig") as file:
        return json.load(file)


def get_experiment_description(service, experiment_id, *, fallback_name=""):
    """Return complete presentation metadata for a registered experiment."""

    descriptions = load_experiment_descriptions()
    description = descriptions.get(service, {}).get(experiment_id, {})
    metadata = ExperimentCatalog().get_experiment(service, experiment_id)
    name = fallback_name or (metadata or {}).get("name") or experiment_id.replace("-", " ")
    if not description and metadata is None and not fallback_name:
        return {}

    return {
        "description": description.get("description")
        or f"Runs the controlled {name.lower()} resilience experiment.",
        "impact": description.get("impact")
        or description.get("potential_impact")
        or (
            "The selected target may experience the configured fault, temporary "
            "degradation, or service disruption during the experiment window."
        ),
        "expected_behavior": description.get("expected_behavior")
        or (
            "The workload should tolerate the fault within its resilience "
            "objectives and recover after cleanup completes."
        ),
    }
