import time
from collections.abc import Callable
from typing import Any

from chaosforge.lifecycle.checks.adapter import ResourceAdapter
from chaosforge.lifecycle.checks.base import ExperimentCheck


class CommonResourceCheck(ExperimentCheck):
    """
    Generic lifecycle check for resources.

    Provider-specific resource access is supplied through a
    ResourceAdapter.

    Validation behavior is supplied through optional predicates,
    keeping the lifecycle framework independent of any specific
    AWS or Kubernetes resource type.
    """

    name = "common-resource"

    def __init__(
        self,
        adapter: ResourceAdapter,
        *,
        predicates: dict[
            str,
            Callable[[dict[str, Any], dict[str, Any]], bool],
        ]
        | None = None,
        name: str = "common-resource",
        report_field: tuple[str, str, str] | None = None,
        recovery_supported: bool = True,
        validation_timeout_seconds: int = 0,
        validation_poll_seconds: int = 5,
        preconditions: dict[
            str,
            Callable[[dict[str, Any]], bool],
        ]
        | None = None,
    ):
        self.adapter = adapter
        self.predicates = predicates or {}
        self.name = name
        self.report_field = report_field
        self.recovery_supported = recovery_supported
        self.validation_timeout_seconds = validation_timeout_seconds
        self.validation_poll_seconds = validation_poll_seconds
        self.preconditions = preconditions or {}

    def capture(
        self, target: dict[str, Any], *, validate_preconditions: bool = True
    ) -> dict[str, Any]:
        snapshot = self.adapter.capture(target)

        failed = [
            name
            for name, predicate in self.preconditions.items()
            if not predicate(snapshot)
        ] if validate_preconditions else []

        if failed:
            raise ValueError(
                "Target is not eligible for this experiment: "
                + ", ".join(failed)
            )

        return snapshot

    def validate(
        self,
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.validation_timeout_seconds
        while True:
            result = self._validate_once(target, baseline)
            if result["passed"] or not self.validation_timeout_seconds or time.monotonic() >= deadline:
                return result
            time.sleep(self.validation_poll_seconds)

    def _validate_once(self, target, baseline):
        try:
            current = self.capture(target, validate_preconditions=False)
        except Exception as exc:  # noqa: BLE001
            return {"passed": False, "exists": False, "error": str(exc)}
        checks: dict[str, bool] = {}
        if self.predicates:
            for name, predicate in self.predicates.items():
                try:
                    checks[name] = bool(predicate(current, baseline))
                except Exception:  # noqa: BLE001
                    checks[name] = False
        else:
            checks["exists"] = current.get("exists") == baseline.get("exists")
        result = {"passed": all(checks.values()), "baseline": baseline, "current": current, "checks": checks}
        if display := self._build_validation_display(baseline, current):
            result["display"] = display
        return result

    def build_execution_display(
        self,
        target: dict[str, Any],
    ) -> dict[str, str]:
        """
        Build Expected/Observed values for the chaos execution report.
        """

        if not self.report_field:
            return {}

        target_key, _, label = self.report_field
        expected = target.get(target_key)

        if expected is None:
            return {
                "Expected": "-",
                "Observed": "-",
            }

        expected_text = f"{expected} {label}".strip()

        return {
            "Expected": expected_text,
            "Observed": "Applied successfully",
        }

    def _build_validation_display(
        self,
        baseline: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, str]:
        """
        Build Expected/Observed values for post-validation.
        """

        if not self.report_field:
            return {}

        _, field_path, label = self.report_field

        baseline_value = self._get_field_value(
            baseline,
            field_path,
        )
        current_value = self._get_field_value(
            current,
            field_path,
        )

        if baseline_value is None and current_value is None:
            return {}

        return {
            "Expected": f"{baseline_value} {label}".strip(),
            "Observed": f"{current_value} {label}".strip(),
        }

    @staticmethod
    def _get_field_value(
        snapshot: dict[str, Any],
        field_path: str,
    ) -> Any:
        value: Any = snapshot

        for part in field_path.split("."):
            if not isinstance(value, dict):
                return None

            value = value.get(part)

        return value
