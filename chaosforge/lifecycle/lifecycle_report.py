from __future__ import annotations

from typing import Any


class LifecycleReportRenderer:
    """Render the client-facing lifecycle validation report."""

    LABEL_WIDTH = 12

    def render(
        self,
        *,
        precheck: dict[str, Any] | None = None,
        injection: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
    ) -> str:
        precheck = precheck or {}
        injection = injection or {}
        validation = validation or {}

        overall = self._calculate_overall(
            injection,
            validation,
        )

        lines: list[str] = [
            "=" * 70,
            "",
            "Lifecycle Validation",
            "",
            "=" * 70,
            "",
        ]

        self._add_precheck(lines, precheck)
        self._add_chaos_execution(lines, injection)
        self._add_post_validation(lines, validation)

        lines.extend(
            [
                "",
                "FINAL RESULT",
                "",
                self._line(
                    "OVERALL",
                    overall,
                ),
                "",
                "=" * 70,
            ]
        )

        return "\n".join(lines)

    def _add_precheck(
        self,
        lines: list[str],
        result: dict[str, Any],
    ) -> None:
        lines.extend(
            [
                "PRE-CHECK",
                "",
                self._line(
                    "Check",
                    result.get("check", "-"),
                ),
                self._line(
                    "Resource",
                    result.get("resource", "-"),
                ),
                self._line(
                    "Baseline",
                    result.get("baseline", "Captured"),
                ),
                self._line(
                    "Result",
                    self._result(
                        result.get("passed"),
                        skipped=result.get("enabled") is False,
                        warnings=result.get("warnings", []),
                    ),
                ),
                "",
            ]
        )

        if result.get("error"):
            lines.insert(len(lines) - 1, self._line("Error", result["error"]))

    def _add_chaos_execution(
        self,
        lines: list[str],
        result: dict[str, Any],
    ) -> None:
        display = result.get("display", {})

        lines.extend(
            [
                "CHAOS EXECUTION",
                "",
                self._line(
                    "Check",
                    result.get("check", "-"),
                ),
                self._line(
                    "Expected",
                    display.get("Expected", "-"),
                ),
                self._line(
                    "Observed",
                    display.get("Observed", "-"),
                ),
                self._line(
                    "Result",
                    self._result(
                        result.get("success"),
                    ),
                ),
                "",
            ]
        )

        if result.get("error"):
            lines.insert(len(lines) - 1, self._line("Error", result["error"]))

    def _add_post_validation(
        self,
        lines: list[str],
        result: dict[str, Any],
    ) -> None:
        display = result.get("display", {})

        lines.extend(
            [
                "POST-VALIDATION",
                "",
                self._line(
                    "Check",
                    result.get("check", "-"),
                ),
                self._line(
                    "Expected",
                    display.get("Expected", "-"),
                ),
                self._line(
                    "Observed",
                    display.get("Observed", "-"),
                ),
                self._line(
                    "Result",
                    self._result(
                        result.get("passed"),
                        skipped=result.get("enabled") is False,
                        warnings=result.get("warnings", []),
                    ),
                ),
                "",
            ]
        )

        for warning in result.get("warnings", []):
            label = warning.get("label", "Advisory")
            detail = warning.get("detail", "")
            lines.insert(len(lines) - 1, self._line("Warning", f"{label}: {detail}"))

    @staticmethod
    def _calculate_overall(
        injection: dict[str, Any],
        validation: dict[str, Any],
    ) -> str:
        injection_passed = injection.get("success") is True

        validation_enabled = (
            validation.get("enabled", False) is True
        )

        validation_passed = (
            validation.get("passed") is True
            if validation_enabled
            else True
        )

        if not injection_passed or not validation_passed:
            return "FAILED"
        if validation.get("warnings"):
            return "PASSED WITH WARNINGS"
        return "PASSED"

    @staticmethod
    def _result(
        value: Any,
        *,
        skipped: bool = False,
        warnings: list[dict[str, Any]] | None = None,
    ) -> str:
        if skipped:
            return "SKIPPED"

        if value is True:
            return "PASSED WITH WARNINGS" if warnings else "PASSED"

        if value is False:
            return "FAILED"

        return "SKIPPED"

    @classmethod
    def _line(
        cls,
        label: str,
        value: Any,
    ) -> str:
        if value is None:
            value = "-"

        return f"  {label:<{cls.LABEL_WIDTH}}: {value}"
