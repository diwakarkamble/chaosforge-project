"""Canonical experiment construction shared by all interfaces."""

import json

from chaosforge.application.duration import LOCAL_DURATION_FIELDS, iso8601_duration
from chaosforge.application.safety import reversibility
from chaosforge.catalog import ExperimentCatalog
from chaosforge.catalog.loader import AZURE_COMPONENT_PACKAGES
from chaosforge.models import Experiment

AZURE_SERVICES = set(AZURE_COMPONENT_PACKAGES)


def create_experiment(service, metadata, variables=None, default_region=None):
    values = dict(variables or {})
    for field in metadata.get("inputs", []):
        name = field.get("name")
        if name and values.get(name) in (None, "") and "default" in field:
            values[name] = field["default"]
        if name in LOCAL_DURATION_FIELDS and name in values:
            values[name] = iso8601_duration(values[name])
        if (
            name == "duration"
            and field.get("type") == "iso8601_duration"
            and name in values
        ):
            values[name] = iso8601_duration(values[name])
    if service not in AZURE_SERVICES and default_region:
        values.setdefault("aws_region", default_region)
    if service not in AZURE_SERVICES and values.get("aws_region"):
        # Older Toolkit definitions use ${region}; Web and CLI collect aws_region.
        values.setdefault("region", values["aws_region"])

    engine = metadata.get("engine", "Chaos Toolkit")
    target_service = service
    if service == "aks":
        engine = "Azure Chaos Studio"
        values["experiment_id"] = metadata["id"]
    elif service in AZURE_SERVICES:
        values["experiment_id"] = metadata["id"]
        if metadata["id"] == "azure-vmss-toolkit-reboot" and isinstance(
            values.get("instance_criteria"), str
        ):
            instance_ids = json.loads(values["instance_criteria"] or "[]")
            values["instance_criteria"] = [
                {"instanceId": str(instance_id)} for instance_id in instance_ids
            ]
    elif service == "fis":
        engine = "AWS FIS"
        target_service = values.get("service_id", "fis")

    name = metadata["name"]
    if service == "fis":
        from chaosforge.providers.aws.fis.catalog import FISCatalog

        fis_experiment = FISCatalog().get_experiment(
            values.get("service_id"),
            values.get("experiment_id"),
        )
        if fis_experiment:
            name = f"{fis_experiment['name']} (AWS FIS)"
    elif service == "chaos_mesh":
        engine = "Chaos Mesh"
        target_service = "eks"

    json_file = ""
    if service != "fis" and metadata.get("json"):
        json_file = str(ExperimentCatalog().definition_path(service, metadata["json"]))

    return Experiment(
        id=metadata["id"],
        service=service,
        name=name,
        json_file=json_file,
        variables=values,
        engine=engine,
        target_service=target_service,
        reversibility=reversibility(service, metadata["id"], values),
    )
