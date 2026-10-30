from typing import Any

from chaosforge.application.metadata import get_experiment
from chaosforge.application.validation.experiment import (
    ExperimentValidator,
)


class ExperimentValidationService:
    """
    Connects ChaosForge campaign experiments with the
    experiment metadata validation engine.

    This service does not execute experiments and does not
    contact AWS.
    """

    def __init__(
        self,
        validator: ExperimentValidator | None = None,
    ):
        self.validator = (
            validator
            if validator is not None
            else ExperimentValidator()
        )

    def validate_experiment(
        self,
        experiment: Any,
    ) -> dict[str, Any]:
        """
        Validate an existing ChaosForge Experiment object
        against its metadata.
        """

        metadata = get_experiment(
            experiment.service,
            experiment.id,
        )

        if metadata is None:
            return {
                "valid": False,
                "errors": [
                    (
                        "Experiment metadata not found for "
                        f"service '{experiment.service}' "
                        f"and experiment '{experiment.id}'."
                    )
                ],
                "warnings": [],
            }

        return self.validator.validate(
            metadata,
            dict(experiment.variables),
        )

    def validate_campaign(
        self,
        campaign: Any,
    ) -> dict[str, Any]:
        """
        Validate all experiments in a campaign.

        Returns one structured result containing the
        campaign-level status and individual experiment
        validation results.
        """

        results = []

        for experiment in campaign.experiments:
            result = self.validate_experiment(
                experiment
            )

            results.append(
                {
                    "experiment_id": experiment.id,
                    "service": experiment.service,
                    "name": experiment.name,
                    "valid": result["valid"],
                    "errors": result["errors"],
                    "warnings": result["warnings"],
                }
            )

        valid = all(
            result["valid"]
            for result in results
        )

        return {
            "valid": valid,
            "experiments": results,
        }
