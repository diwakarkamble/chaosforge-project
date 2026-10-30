from datetime import datetime, timezone
from typing import Any

from chaosforge.models.execution import ExecutionContext


class EvidenceBuilder:
    """
    Builds the reproducible evidence artifact for a ChaosForge execution.

    The evidence structure is provider-agnostic so that
    Chaos Toolkit, AWS FIS and future Chaos Mesh executions
    can use the same evidence contract.
    """

    EVIDENCE_VERSION = "2.0"

    def build(
        self,
        context: ExecutionContext,
        experiment: Any,
    ) -> dict[str, Any]:
        """
        Build a structured evidence record from the execution context.
        """

        return {
            "evidence_version": self.EVIDENCE_VERSION,

            # -----------------------------------------------------
            # EXECUTION
            # -----------------------------------------------------

            "execution": {
                "execution_id": context.execution_id,
                "experiment_id": context.experiment_id,
                "service": context.service,
                "experiment_name": context.experiment_name,
                "state": context.state.value,
                "started_at": self._serialize_datetime(
                    context.started_at
                ),
                "completed_at": self._serialize_datetime(
                    context.completed_at
                ),
            },

            # -----------------------------------------------------
            # EXPERIMENT DEFINITION
            # -----------------------------------------------------

            "experiment": {
                "id": experiment.id,
                "service": experiment.service,
                "name": experiment.name,
                "json_file": getattr(
                    experiment,
                    "json_file",
                    None,
                ),
                "engine": getattr(
                    experiment,
                    "engine",
                    None,
                ),
                "variables": dict(
                    experiment.variables
                ),
                "status": getattr(
                    experiment,
                    "status",
                    None,
                ),
                "error_message": getattr(
                    experiment,
                    "error_message",
                    None,
                ),
            },

            # -----------------------------------------------------
            # RESOLVED TARGET
            # -----------------------------------------------------

            "target": context.target or {
                "resolved": dict(
                    experiment.variables
                ),
            },

            # -----------------------------------------------------
            # PROVIDER
            # -----------------------------------------------------

            "provider": context.provider,

            # -----------------------------------------------------
            # PRECHECK
            # -----------------------------------------------------

            "precheck": context.precheck,

            # -----------------------------------------------------
            # BASELINE
            # -----------------------------------------------------

            "baseline": context.baseline,

            # -----------------------------------------------------
            # FAULT INJECTION
            # -----------------------------------------------------

            "injection": context.injection,

            # -----------------------------------------------------
            # VALIDATION
            # -----------------------------------------------------

            "validation": context.validation,

            # -----------------------------------------------------
            # RECOVERY
            # -----------------------------------------------------

            "recovery": context.recovery,

            # -----------------------------------------------------
            # OBSERVABILITY
            # -----------------------------------------------------

            "observability": context.observability,

            # -----------------------------------------------------
            # APPROVAL
            # -----------------------------------------------------

            "approval": context.approval,

            # -----------------------------------------------------
            # ENVIRONMENT
            # -----------------------------------------------------

            "environment": context.environment,

            # -----------------------------------------------------
            # LOGS
            # -----------------------------------------------------

            "logs": context.logs,

            # -----------------------------------------------------
            # EVENTS
            # -----------------------------------------------------

            "events": context.events,

            # -----------------------------------------------------
            # FINAL RESULT
            # -----------------------------------------------------

            "result": context.result,

            # -----------------------------------------------------
            # ERRORS
            # -----------------------------------------------------

            "errors": list(
                context.errors
            ),

            "warnings": list(
                context.warnings
            ),

            # -----------------------------------------------------
            # METADATA
            # -----------------------------------------------------

            "generated_at": self._serialize_datetime(
                datetime.now(timezone.utc)
            ),
        }

    @staticmethod
    def _serialize_datetime(
        value: datetime | None,
    ) -> str | None:
        """
        Convert datetime values into ISO-8601 strings.
        """

        if value is None:
            return None

        return value.isoformat()
