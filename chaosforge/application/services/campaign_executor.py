"""Canonical sequential campaign execution policy."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from chaosforge.models.outcome import ExperimentOutcome, is_failure, is_warning_success


@dataclass
class CampaignExecutionResult:
    """Aggregate outcome produced by the shared campaign loop."""

    executed: list[Any] = field(default_factory=list)
    failed: list[Any] = field(default_factory=list)
    warnings: list[Any] = field(default_factory=list)
    skipped: list[Any] = field(default_factory=list)
    status: str = "SUCCESS"


class CampaignExecutor:
    """Execute an ordered campaign with one continuation policy.

    Engine-specific work remains in the supplied ``run_experiment`` callable.
    Interfaces may subscribe through callbacks without owning loop semantics.
    """

    def execute(
        self,
        campaign,
        run_experiment: Callable[[Any], Any],
        *,
        before_experiment: Callable[[int, int, Any], None] | None = None,
        after_experiment: Callable[[int, int, Any, Any], None] | None = None,
    ) -> CampaignExecutionResult:
        experiments = list(getattr(campaign, "experiments", []))
        result = CampaignExecutionResult()
        campaign.start_time = datetime.now(timezone.utc)

        for index, experiment in enumerate(experiments, start=1):
            if before_experiment is not None:
                before_experiment(index, len(experiments), experiment)

            configured_variables = deepcopy(getattr(experiment, "variables", {}))
            try:
                execution_result = run_experiment(experiment)
            finally:
                # Engines may consume or augment their runtime configuration.
                # The campaign remains a reusable portable definition.
                experiment.variables = configured_variables
            result.executed.append(experiment)

            if after_experiment is not None:
                after_experiment(index, len(experiments), experiment, execution_result)

            if is_warning_success(getattr(experiment, "status", None)):
                result.warnings.append(experiment)

            if is_failure(getattr(experiment, "status", None)):
                result.failed.append(experiment)
                if not getattr(campaign, "continue_on_failure", False):
                    for skipped in experiments[index:]:
                        skipped.status = "SKIPPED"
                        result.skipped.append(skipped)
                    break

        campaign.end_time = datetime.now(timezone.utc)
        campaign.duration = (campaign.end_time - campaign.start_time).total_seconds()

        if result.failed and result.skipped:
            result.status = "PARTIAL"
        elif result.failed:
            result.status = "FAILED"
        elif result.warnings:
            result.status = ExperimentOutcome.SUCCESS_WITH_WARNINGS.value
        return result
