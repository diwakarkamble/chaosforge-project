"""Execution-based presentation metadata for experiment catalogs.

Labels describe the mechanism that executes the fault: AWS FIS, Azure Chaos
Studio, Chaos Mesh, Chaos Toolkit, or a direct SDK/custom-script action.
"""

from chaosforge.application.experiment_descriptions import get_experiment_description
from chaosforge.application.safety import reversibility

ENGINE_DETAILS = {
    "FIS": {"class": "fis", "rich": "yellow"},
    "Chaos Mesh": {"class": "chaos-mesh", "rich": "magenta"},
    "Chaos Studio": {"class": "chaos-studio", "rich": "bright_blue"},
    "Chaos Toolkit": {"class": "chaos-toolkit", "rich": "cyan"},
    "Custom": {"class": "custom", "rich": "green"},
}

CHAOS_TOOLKIT_SERVICES = {
    "apigateway",
    "dynamodb",
    "ec2",
    "ecs",
    "eks",
    "elasticache",
    "elb",
    "lambda",
    "rds",
    "s3",
    "sns",
    "vpc",
}


def present_experiment(service, experiment, *, engine=None):
    """Return an experiment enriched with a uniform engine label and summary."""
    presented = dict(experiment)
    engine_label = _engine_label(engine or experiment.get("engine") or experiment.get("source"), service)
    catalog_description = get_experiment_description(service, experiment.get("id", "")).get("description")
    description = (
        experiment.get("description")
        or catalog_description
        or f"Controlled {experiment['name'].lower()} resilience experiment."
    )
    presented.update(
        {
            "description": description,
            "engine_label": engine_label,
            "engine_class": ENGINE_DETAILS[engine_label]["class"],
            "engine_rich": ENGINE_DETAILS[engine_label]["rich"],
            "reversibility": reversibility(
                service,
                experiment.get("id"),
                experiment.get("variables")
                or {
                    "service_id": experiment.get("fis_service_id"),
                    "experiment_id": experiment.get("fis_experiment_id"),
                },
            ),
        }
    )
    return presented


def rich_engine_label(experiment):
    """Render the normalized engine and safety labels with their CLI colors."""
    engine = (
        f"[bold {experiment['engine_rich']}]"
        f"[{experiment['engine_label']}]"
        f"[/bold {experiment['engine_rich']}]"
    )
    safety = (
        "[bold green][REVERSIBLE][/bold green]"
        if experiment["reversibility"] == "reversible"
        else "[bold red][IRREVERSIBLE][/bold red]"
    )
    return f"{engine} {safety}"


def _engine_label(engine, service):
    normalized = (engine or "").lower()
    if service == "fis" or "fis" in normalized:
        return "FIS"
    if service == "chaos_mesh" or "chaos mesh" in normalized:
        return "Chaos Mesh"
    if service == "aks" or "chaos studio" in normalized:
        return "Chaos Studio"
    if "chaos toolkit" in normalized or service in CHAOS_TOOLKIT_SERVICES:
        return "Chaos Toolkit"
    return "Custom"
