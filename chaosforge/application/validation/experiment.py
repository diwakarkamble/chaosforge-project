"""Experiment metadata validation."""

import re
from typing import Any

from chaosforge.application.duration import (
    LOCAL_DURATION_FIELDS,
    is_iso8601_duration,
    iso8601_duration,
)


class ExperimentValidator:
    """Validates an experiment definition and its variables without execution."""

    def validate(
        self,
        experiment: dict[str, Any],
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        errors = []
        warnings = []
        inputs = experiment.get("inputs", [])

        if not isinstance(inputs, list):
            errors.append("Experiment metadata contains an invalid inputs definition.")
            return self._result(errors, warnings)

        input_definitions = {
            item.get("name"): item
            for item in inputs
            if isinstance(item, dict) and item.get("name")
        }

        for name, definition in input_definitions.items():
            if definition.get("required", False):
                value = variables.get(name)
                has_azure_name_alias = (
                    name == "resource_id"
                    and definition.get("type") == "azure_component_resource"
                    and str(variables.get("resource_name") or "").strip()
                )
                if not has_azure_name_alias and (value is None or str(value).strip() == ""):
                    errors.append(f"Required variable '{name}' is missing.")

        for name in variables:
            if name not in input_definitions and name != "resource_name":
                warnings.append(
                    f"Variable '{name}' is not defined in experiment metadata."
                )

        for name, definition in input_definitions.items():
            if name not in variables or variables[name] is None:
                continue
            self._validate_type_and_range(
                name,
                variables[name],
                definition,
                errors,
            )

        return self._result(errors, warnings)

    @staticmethod
    def _result(errors: list[str], warnings: list[str]) -> dict[str, Any]:
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    @staticmethod
    def _validate_type_and_range(name, value, definition, errors):
        field_type = definition.get("type")
        if name in LOCAL_DURATION_FIELDS:
            field_type = "iso8601_duration"
            try:
                value = iso8601_duration(value)
            except (TypeError, ValueError):
                pass
        if field_type == "integer":
            if isinstance(value, bool):
                errors.append(f"Variable '{name}' must be an integer.")
                return
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                errors.append(f"Variable '{name}' must be an integer.")
                return
            ExperimentValidator._validate_range(name, numeric, definition, errors)
        elif field_type == "float":
            if isinstance(value, bool):
                errors.append(f"Variable '{name}' must be a float.")
                return
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors.append(f"Variable '{name}' must be a float.")
                return
            ExperimentValidator._validate_range(name, numeric, definition, errors)
        elif field_type == "number":
            if isinstance(value, bool):
                errors.append(f"Variable '{name}' must be a number.")
                return
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors.append(f"Variable '{name}' must be a number.")
                return
            ExperimentValidator._validate_range(name, numeric, definition, errors)
        elif field_type == "boolean" and not isinstance(value, bool):
            if str(value).strip().lower() not in {"true", "false"}:
                errors.append(f"Variable '{name}' must be a boolean.")
        elif field_type in {"choice", "chaos_mode"}:
            choices = definition.get("choices") or (
                ["one", "all", "fixed", "fixed-percent", "random-max-percent"]
                if field_type == "chaos_mode"
                else []
            )
            if value not in choices:
                errors.append(
                    f"Variable '{name}' must be one of: {', '.join(choices)}."
                )
        elif field_type == "yes_no" and str(value).strip().lower() not in {"y", "yes", "n", "no"}:
            errors.append(f"Variable '{name}' must be Yes or No.")
        elif field_type == "aws_region":
            if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", str(value).strip()):
                errors.append(f"Variable '{name}' must be a valid AWS Region.")
        elif field_type == "iso8601_duration":
            if not is_iso8601_duration(value):
                errors.append(
                    f"Variable '{name}' must be an ISO 8601 duration, for example PT1M."
                )

    @staticmethod
    def _validate_range(name, value, definition, errors):
        minimum = definition.get("min")
        maximum = definition.get("max")
        if not isinstance(minimum, (int, float)):
            minimum = None
        if not isinstance(maximum, (int, float)):
            maximum = None
        if minimum is not None and value < minimum:
            errors.append(f"Variable '{name}' must be at least {minimum}.")
        if maximum is not None and value > maximum:
            errors.append(f"Variable '{name}' must be at most {maximum}.")

    @staticmethod
    def _is_boolean(value):
        return isinstance(value, bool) or (
            isinstance(value, str)
            and value.strip().lower() in {"true", "false"}
        )
