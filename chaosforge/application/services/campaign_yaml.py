"""Portable YAML import and export for ChaosForge campaigns."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import yaml

from chaosforge.application.campaigns.duplicates import duplicate_experiment_indexes
from chaosforge.application.campaigns.factory import AZURE_SERVICES, create_experiment
from chaosforge.application.services.experiment_validation import (
    ExperimentValidationService,
)
from chaosforge.application.validation.yaml import YAMLValidator
from chaosforge.catalog import ExperimentCatalog
from chaosforge.models import Campaign

MAX_CAMPAIGN_YAML_BYTES = 1_048_576


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True)
class CampaignYAMLReview:
    valid: bool
    campaign: Campaign | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_name: str = ""
    sha256: str = ""
    document: dict[str, Any] | None = None
    experiment_summaries: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    is_template: bool = False


class CampaignYAMLService:
    def __init__(self, catalog=None, validation_service=None):
        self.catalog = catalog or ExperimentCatalog()
        self.validation_service = validation_service or ExperimentValidationService()

    def inspect_bytes(
        self,
        content: bytes,
        *,
        source_name: str = "",
        expected_provider: str | None = None,
        max_bytes: int = MAX_CAMPAIGN_YAML_BYTES,
    ) -> CampaignYAMLReview:
        digest = hashlib.sha256(content if isinstance(content, bytes) else b"").hexdigest()
        if not isinstance(content, bytes):
            return self._invalid("Campaign YAML content must be bytes.", source_name, digest)
        if not content:
            return self._invalid("Campaign YAML is empty.", source_name, digest)
        if len(content) > max_bytes:
            return self._invalid(
                f"Campaign YAML exceeds the {max_bytes} byte limit.", source_name, digest
            )
        if b"\x00" in content:
            return self._invalid("Campaign YAML contains a NUL byte.", source_name, digest)

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return self._invalid("Campaign YAML must be UTF-8 encoded.", source_name, digest)

        loader = UniqueKeySafeLoader(text)
        try:
            documents = []
            while loader.check_data():
                documents.append(loader.get_data())
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            return self._invalid(f"Invalid YAML{location}: {exc}", source_name, digest)
        finally:
            loader.dispose()

        if len(documents) != 1:
            return self._invalid(
                "Campaign YAML must contain exactly one document.", source_name, digest
            )
        document = documents[0]
        schema_result = YAMLValidator().validate(document)
        if not schema_result["valid"]:
            return CampaignYAMLReview(
                valid=False,
                errors=tuple(schema_result["errors"]),
                warnings=tuple(schema_result["warnings"]),
                source_name=source_name,
                sha256=digest,
                document=document if isinstance(document, dict) else None,
            )

        provider = str(document.get("cloud", {}).get("provider", "aws")).lower()
        is_template = bool(document.get("template", False))
        if expected_provider and provider != expected_provider:
            return self._invalid(
                f"Uploaded campaign targets '{provider}', but '{expected_provider}' is selected.",
                source_name,
                digest,
                document,
            )

        try:
            campaign = self.build_document(document, provider=provider)
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            return self._invalid(str(exc), source_name, digest, document)

        duplicates = duplicate_experiment_indexes(campaign.experiments)
        if duplicates:
            duplicate_index, original_index = duplicates[0]
            experiment = campaign.experiments[duplicate_index]
            return self._invalid(
                f"experiments[{duplicate_index}] duplicates experiments[{original_index}]: "
                f"{experiment.service}/{experiment.id} has the same target and configuration.",
                source_name,
                digest,
                document,
            )

        validation = self.validation_service.validate_campaign(campaign)
        errors = []
        warnings = []
        for result in validation.get("experiments", []):
            errors.extend(
                f"{result['experiment_id']}: {message}" for message in result.get("errors", [])
            )
            warnings.extend(
                f"{result['experiment_id']}: {message}"
                for message in result.get("warnings", [])
            )
        if not validation.get("valid", False):
            return CampaignYAMLReview(
                valid=False,
                campaign=campaign,
                errors=tuple(errors),
                warnings=tuple(warnings),
                source_name=source_name,
                sha256=digest,
                document=document,
                experiment_summaries=self._summaries(campaign),
                is_template=is_template,
            )

        return CampaignYAMLReview(
            valid=True,
            campaign=campaign,
            warnings=tuple(warnings),
            source_name=source_name,
            sha256=digest,
            document=document,
            experiment_summaries=self._summaries(campaign),
            is_template=is_template,
        )

    def campaign_from_bytes(self, content: bytes, **kwargs) -> Campaign:
        review = self.inspect_bytes(content, **kwargs)
        if not review.valid or review.campaign is None:
            raise ValueError("; ".join(review.errors) or "Invalid campaign YAML.")
        return review.campaign

    def document_from_campaign(self, campaign: Campaign, *, environment=None) -> dict[str, Any]:
        document = {
            "campaign": {
                "name": campaign.name,
                "continue_on_failure": bool(campaign.continue_on_failure),
                "irreversible_operations_acknowledged": bool(
                    campaign.irreversible_operations_acknowledged
                ),
            },
            "cloud": {"provider": str(campaign.cloud_provider or "aws").lower()},
            "experiments": [
                {
                    "service": experiment.service,
                    "experiment": experiment.id,
                    "variables": self._portable_value(experiment.variables),
                }
                for experiment in campaign.experiments
            ],
        }
        if environment:
            document["environment"] = self._portable_value(environment)
        else:
            document["template"] = True
        if campaign.report_timezone:
            document["settings"] = {"timezone": campaign.report_timezone}
        return document

    def export_bytes(self, campaign: Campaign, *, environment=None) -> bytes:
        document = self.document_from_campaign(campaign, environment=environment)
        return yaml.safe_dump(
            document,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        ).encode("utf-8")

    def build_document(self, document, *, provider=None):
        provider = str(
            provider or document.get("cloud", {}).get("provider", "aws")
        ).lower()
        campaign_data = document.get("campaign", {})
        campaign = Campaign(
            name=campaign_data.get("name", "Default Campaign"),
            continue_on_failure=campaign_data.get("continue_on_failure", False),
            irreversible_operations_acknowledged=campaign_data.get(
                "irreversible_operations_acknowledged", False
            ),
            cloud_provider=provider,
            report_timezone=(document.get("settings") or {}).get("timezone"),
        )
        for item in document["experiments"]:
            service = item["service"]
            if (service in AZURE_SERVICES) != (provider == "azure"):
                raise ValueError(
                    f"Service '{service}' does not belong to provider '{provider}'."
                )
            metadata = self.catalog.get_experiment(service, item["experiment"])
            if metadata is None:
                raise LookupError(
                    f"Experiment '{item['experiment']}' not found for service '{service}'."
                )
            campaign.experiments.append(
                create_experiment(service, metadata, dict(item["variables"]))
            )
        return campaign

    @staticmethod
    def _portable_value(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [CampaignYAMLService._portable_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): CampaignYAMLService._portable_value(item)
                for key, item in value.items()
            }
        raise TypeError(f"Campaign variable type '{type(value).__name__}' is not portable.")

    @staticmethod
    def _summaries(campaign):
        return tuple(
            {
                "service": experiment.service,
                "id": experiment.id,
                "name": experiment.name,
                "engine": experiment.engine,
                "variables": experiment.variables,
                "reversibility": experiment.reversibility,
            }
            for experiment in campaign.experiments
        )

    @staticmethod
    def _invalid(message, source_name, digest, document=None):
        return CampaignYAMLReview(
            valid=False,
            errors=(message,),
            source_name=source_name,
            sha256=digest,
            document=document,
        )
