from typing import Any

from chaosforge.lifecycle.checks.base import ExperimentCheck
from chaosforge.models.execution import ExecutionContext, ExecutionState


class LifecycleCoordinator:
    """
    Coordinates the common lifecycle around a chaos experiment.

    This class does not execute the chaos experiment itself.
    The existing experiment runner remains responsible for
    fault injection.

    The coordinator is responsible for:
    - execution context
    - precheck
    - baseline capture
    - post-execution validation
    - recovery validation
    - lifecycle state transitions
    """

    def __init__(self, check: ExperimentCheck | None = None):
        self.check = check

    def create_context(
        self,
        execution_id: str,
        experiment_id: str,
        service: str,
        experiment_name: str,
    ) -> ExecutionContext:
        """
        Create a new execution context.

        A new execution always starts in PLANNED state.
        """

        return ExecutionContext(
            execution_id=execution_id,
            experiment_id=experiment_id,
            service=service,
            experiment_name=experiment_name,
            state=ExecutionState.PLANNED,
        )

    def run_precheck(
        self,
        context: ExecutionContext,
        target: dict[str, Any],
    ) -> bool:
        """
        Run the experiment precheck and capture the baseline.

        If no check is configured, this method does nothing and
        returns True. This allows existing experiments to continue
        working without requiring lifecycle checks immediately.

        If a check is configured and fails, the experiment moves to
        PRECHECK_FAILED and should not proceed to fault injection.
        """

        if self.check is None:
            context.precheck = {
                "enabled": False,
                "passed": True,
                "message": "No lifecycle check configured.",
            }
            return True

        try:
            baseline = self.check.capture(target)

            context.baseline = baseline

            context.precheck = {
                "enabled": True,
                "passed": True,
                "check": self.check.name,
                "baseline": baseline,
            }

            return True

        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)

            context.precheck = {
                "enabled": True,
                "passed": False,
                "check": self.check.name,
                "error": error_message,
            }

            context.errors.append(
                f"Precheck failed: {error_message}"
            )

            context.transition(
                ExecutionState.PRECHECK_FAILED
            )

            return False

    def mark_running(
        self,
        context: ExecutionContext,
    ) -> None:
        """
        Mark the execution as running.
        """

        context.start()
        context.transition(
            ExecutionState.RUNNING
        )

    def mark_injection_succeeded(
        self,
        context: ExecutionContext,
    ) -> None:
        """
        Mark fault injection as successful.
        """

        context.transition(
            ExecutionState.FAULT_INJECTION_SUCCEEDED
        )

    def mark_injection_failed(
        self,
        context: ExecutionContext,
        error: str,
    ) -> None:
        """
        Mark fault injection as failed and record the error.
        """

        context.errors.append(error)

        context.transition(
            ExecutionState.FAULT_INJECTION_FAILED
        )

    def validate(
        self,
        context: ExecutionContext,
        target: dict[str, Any],
        phase: str = "post",
    ) -> bool:
        """
        Validate the target against the captured baseline.

        phase can identify where validation happened, for example:
        - post
        - recovery

        If no lifecycle check is configured, validation is skipped.
        """

        if self.check is None:
            context.validation = {
                "enabled": False,
                "passed": True,
                "phase": phase,
                "message": "No lifecycle check configured.",
            }

            return True

        try:
            result = self.check.validate(
                target,
                context.baseline,
            )

            passed = bool(result.get("passed", False))

            validation_result = {
                "enabled": True,
                "phase": phase,
                "check": self.check.name,
                "result": result,
            }

            context.validation = validation_result
            context.warnings.extend(result.get("warnings", []))

            if passed:
                context.transition(
                    ExecutionState.VALIDATION_PASSED
                )
            else:
                context.transition(
                    ExecutionState.VALIDATION_FAILED
                )

            return passed

        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)

            context.validation = {
                "enabled": True,
                "phase": phase,
                "check": self.check.name,
                "passed": False,
                "error": error_message,
            }

            context.errors.append(
                f"Validation failed: {error_message}"
            )

            context.transition(
                ExecutionState.VALIDATION_FAILED
            )

            return False

    def validate_recovery(
        self,
        context: ExecutionContext,
        target: dict[str, Any],
    ) -> bool:
        """
        Validate that the target has recovered to its baseline state.

        Recovery validation uses the same lifecycle check and baseline
        captured during precheck, but stores the result separately in
        context.recovery.

        A successful recovery results in VALIDATION_PASSED.
        A failed recovery results in RECOVERY_FAILED.
        """

        if self.check is None:
            context.recovery = {
                "enabled": False,
                "passed": True,
                "phase": "recovery",
                "message": "No lifecycle check configured.",
            }

            return True


        if not getattr(self.check, "recovery_supported", True):
            context.recovery = {
                "enabled": False,
                "passed": True,
                "phase": "recovery",
                "check": self.check.name,
                "message": "Recovery validation not applicable.",
            }

            if context.state != ExecutionState.VALIDATION_FAILED:
                context.transition(
                    ExecutionState.VALIDATION_PASSED
                )

            return True


        try:
            result = self.check.validate(
                target,
                context.baseline,
            )

            passed = bool(result.get("passed", False))

            context.recovery = {
                "enabled": True,
                "passed": passed,
                "phase": "recovery",
                "check": self.check.name,
                "result": result,
            }

            if passed:
                if context.state != ExecutionState.VALIDATION_FAILED:
                    context.transition(
                        ExecutionState.VALIDATION_PASSED
                    )
            else:
                context.transition(
                    ExecutionState.RECOVERY_FAILED
                )

            return passed

        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)

            context.recovery = {
                "enabled": True,
                "passed": False,
                "phase": "recovery",
                "check": self.check.name,
                "error": error_message,
            }

            context.errors.append(
                f"Recovery validation failed: {error_message}"
            )

            context.transition(
                ExecutionState.RECOVERY_FAILED
            )

            return False

    def record_recovery(
        self,
        context: ExecutionContext,
        result: dict[str, Any],
    ) -> None:
        """Record recovery information supplied by an execution engine."""

        context.recovery = result

    def mark_recovery_failed(
        self,
        context: ExecutionContext,
        error: str,
    ) -> None:
        """
        Mark recovery as failed.
        """

        context.errors.append(error)

        context.transition(
            ExecutionState.RECOVERY_FAILED
        )

    def complete(
        self,
        context: ExecutionContext,
    ) -> None:
        """
        Mark execution completion time.
        """

        context.complete()
