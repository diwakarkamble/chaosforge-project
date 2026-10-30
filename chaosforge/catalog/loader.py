"""Anchored access to built-in experiment metadata and definitions."""

import json
from pathlib import Path
from typing import Any

from chaosforge.application.duration import (
    normalize_duration_fields,
    normalize_named_duration_field,
)
from chaosforge.common.paths import ChaosForgePaths, repository_paths

AWS_COMPONENT_PACKAGES = {
    "apigateway": "apigateway",
    "dynamodb": "dynamodb",
    "ec2": "ec2",
    "ecs": "ecs",
    "eks": "eks",
    "elasticache": "elasticache",
    "elb": "elb",
    "lambda": "lambda",
    "rds": "rds",
    "s3": "s3",
    "sns": "sns",
    "vpc": "vpc",
}

FIS_ROOT = ("chaosforge", "providers", "aws", "fis")
AKS_ROOT = (
    "chaosforge",
    "providers",
    "azure",
    "components",
    "aks",
)
AZURE_COMPONENT_PACKAGES = {
    "aks": "aks",
    "azure_redis": "azure_redis",
    "azure_vm": "azure_vm",
    "azure_vmss": "azure_vmss",
    "azure_app_service": "azure_app_service",
    "azure_key_vault": "azure_key_vault",
    "azure_cosmos_db": "azure_cosmos_db",
    "azure_event_hub": "azure_event_hub",
    "azure_postgres_flexible": "azure_postgres_flexible",
    "azure_container_apps": "azure_container_apps",
    "azure_functions": "azure_functions",
}


class ExperimentCatalog:
    """Read built-in experiment metadata without depending on the CWD."""

    def __init__(self, paths: ChaosForgePaths | None = None):
        self.paths = paths or repository_paths()

    def metadata_path(self, service: str) -> Path:
        if service == "aks":
            return self.paths.root.joinpath(
                *AKS_ROOT, "experiments", "metadata.json"
            )
        if service in AZURE_COMPONENT_PACKAGES:
            return (
                self.paths.root
                / "chaosforge"
                / "providers"
                / "azure"
                / "components"
                / AZURE_COMPONENT_PACKAGES[service]
                / "experiments"
                / "metadata.json"
            )
        if service == "chaos_mesh":
            return (
                self.paths.root
                / "chaosforge"
                / "engines"
                / "chaos_mesh"
                / "experiments"
                / "metadata.json"
            )
        if service == "fis":
            return self.paths.root.joinpath(*FIS_ROOT, "metadata.json")
        component_package = AWS_COMPONENT_PACKAGES.get(service)
        if component_package:
            migrated_path = (
                self.paths.root
                / "chaosforge"
                / "providers"
                / "aws"
                / "components"
                / component_package
                / "experiments"
                / "metadata.json"
            )
            if migrated_path.is_file():
                return migrated_path
        return self.paths.root / "chaosforge" / "catalog" / "missing-metadata.json"

    def list_services(self) -> list[str]:
        """Return services registered in the canonical package layout."""
        services = {
            service
            for service in AWS_COMPONENT_PACKAGES
            if self.metadata_path(service).is_file()
        }

        if self.metadata_path("fis").is_file():
            services.add("fis")

        if self.metadata_path("chaos_mesh").is_file():
            services.add("chaos_mesh")

        if self.metadata_path("aks").is_file():
            services.add("aks")

        for service in AZURE_COMPONENT_PACKAGES:
            if self.metadata_path(service).is_file():
                services.add(service)

        return sorted(services)

    def load_service(self, service: str) -> dict[str, Any] | None:
        """Return one service catalog or ``None`` when it is not registered."""
        path = self.metadata_path(service)
        if not path.is_file():
            return None
        with open(path, encoding="utf-8") as handle:
            metadata = json.load(handle)
        normalize_duration_fields(metadata)
        if service in {"aks", "chaos_mesh"}:
            normalize_named_duration_field(metadata)
        if service == "chaos_mesh":
            from chaosforge.engines.chaos_mesh.target_contract import bind_workload_target_contract

            for experiment in metadata.get("experiments", []):
                bind_workload_target_contract(experiment)
        if service == "aks":
            from chaosforge.providers.azure.components.aks.target_contract import (
                bind_workload_target_contract,
            )

            for experiment in metadata.get("experiments", []):
                bind_workload_target_contract(experiment)
        return metadata

    def get_experiment(
        self, service: str, experiment_id: str
    ) -> dict[str, Any] | None:
        """Return one catalog experiment by its stable identifier."""
        metadata = self.load_service(service)
        if metadata is None:
            return None
        return next(
            (
                experiment
                for experiment in metadata.get("experiments", [])
                if experiment.get("id") == experiment_id
            ),
            None,
        )

    def definition_path(self, service: str, filename: str) -> Path:
        """Resolve a definition path beneath the selected service catalog."""
        metadata_path = self.metadata_path(service)
        if service == "chaos_mesh" and "chaosforge" in metadata_path.parts:
            return metadata_path.parent / "definitions" / filename
        if service == "aks" and "chaosforge" in metadata_path.parts:
            return metadata_path.parent / "toolkit" / filename
        if service in AZURE_COMPONENT_PACKAGES and "chaosforge" in metadata_path.parts:
            if filename == "classic_definition.json":
                return self.paths.root / "chaosforge" / "providers" / "azure" / "chaos_studio" / filename
            if filename.startswith(("custom/", "chaos_studio/")):
                return metadata_path.parent / filename
            if service != "azure_redis":
                return metadata_path.parent / "toolkit" / "definitions" / filename
            return metadata_path.parent / filename
        if service in AWS_COMPONENT_PACKAGES and "chaosforge" in metadata_path.parts:
            return (
                metadata_path.parent
                / "toolkit"
                / "definitions"
                / filename
            )
        return self.paths.root / "chaosforge" / "catalog" / "missing-definition.json"
