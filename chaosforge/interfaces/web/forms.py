"""Normalize Web form values using catalog input definitions."""

from chaosforge.application.duration import LOCAL_DURATION_FIELDS, iso8601_duration
from chaosforge.application.validation.input import Validator


def normalize_values(inputs, raw_values):
    values = {}
    errors = {}
    defaults = {field["name"]: field.get("default", "") for field in inputs}
    for field in inputs:
        if any(
            raw_values.get(condition, defaults.get(condition, "")) != expected
            for condition, expected in field.get("visible_when", {}).items()
        ):
            continue
        name = field["name"]
        value = raw_values.get(name, field.get("default", ""))
        if value in (None, "") and field.get("default") is not None:
            value = field["default"]
        validation_field = dict(field)
        if validation_field.get("type") == "aws_region":
            validation_field["type"] = "region"
        if name in LOCAL_DURATION_FIELDS:
            validation_field["type"] = "iso8601_duration"
            try:
                value = iso8601_duration(value)
            except (TypeError, ValueError):
                pass
        elif validation_field.get("type") == "iso8601_duration":
            try:
                value = iso8601_duration(value)
            except (TypeError, ValueError):
                pass
        valid, message = Validator.validate(validation_field, value)
        if not valid:
            errors[name] = message
            continue
        if field.get("type") == "integer" and name not in LOCAL_DURATION_FIELDS and value != "":
            value = int(value)
        elif field.get("type") in {"number", "float"} and value != "":
            number = float(value)
            value = int(number) if number.is_integer() else number
        values[name] = value
    mode = values.get("chaos_mode", values.get("mode", ""))
    if mode in {"fixed", "fixed-percent", "random-max-percent"}:
        mode_value = values.get("chaos_value", "")
        if str(mode_value).strip() == "":
            errors["chaos_value"] = f"Mode Value is required when Chaos Mode is '{mode}'."
        else:
            try:
                number = int(mode_value)
            except (TypeError, ValueError):
                errors["chaos_value"] = "Mode Value must be a whole number."
            else:
                if mode == "fixed" and number < 1:
                    errors["chaos_value"] = "Mode Value must be at least 1 for fixed mode."
                if mode in {"fixed-percent", "random-max-percent"} and not 1 <= number <= 100:
                    errors["chaos_value"] = "Mode Value must be between 1 and 100 for percentage modes."
    return values, errors
