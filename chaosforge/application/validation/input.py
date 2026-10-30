"""
Generic Input Validator
"""

import re

from chaosforge.application.duration import is_iso8601_duration


class Validator:
    @staticmethod
    def validate(field, value):

        field_type = field.get("type", "text")
        required = field.get("required", False)

        #
        # Required validation
        #

        if required and str(value).strip() == "":
            return False, "This field is required."

        #
        # Empty optional field
        #

        if str(value).strip() == "":
            return True, ""

        #
        # Integer validation
        #

        if field_type == "integer":
            try:
                value = int(value)
            except ValueError:
                return False, "Please enter a valid integer."

            minimum = field.get("min")
            maximum = field.get("max")

            if minimum is not None and value < minimum:
                return False, f"Value must be greater than or equal to {minimum}."

            if maximum is not None and value > maximum:
                return False, f"Value must be less than or equal to {maximum}."

            return True, ""

        #
        # Float validation
        #

        if field_type in {"float", "number"}:
            try:
                value = float(value)
            except (TypeError, ValueError):
                return False, "Please enter a valid number."

            minimum = field.get("min")
            maximum = field.get("max")

            if minimum is not None and value < minimum:
                return False, f"Value must be greater than or equal to {minimum}."

            if maximum is not None and value > maximum:
                return False, f"Value must be less than or equal to {maximum}."

            return True, ""

        if field_type == "boolean":
            if isinstance(value, bool):
                return True, ""

            if str(value).strip().lower() not in {
                "true",
                "false",
                "yes",
                "no",
                "y",
                "n",
                "1",
                "0",
            }:
                return False, "Enter true or false."

            return True, ""

        #
        # Yes / No
        #

        if field_type == "yes_no":
            if value.lower() not in ["y", "yes", "n", "no"]:
                return False, "Enter Yes or No."

            return True, ""

        #
        # Choice validation
        #

        if field_type == "choice":
            choices = field.get("choices", [])

            if value not in choices:
                return False, f"Allowed values: {', '.join(choices)}"

            return True, ""

        #
        # ARN validation
        #

        if field_type == "arn":
            if not re.match(r"^arn:aws[a-zA-Z-]*:.*", value):
                return False, "Invalid AWS ARN."

            return True, ""

        #
        # Region validation
        #

        if field_type == "region":
            if not re.match(r"^[a-z]{2}-[a-z]+-\d$", value):
                return False, "Invalid AWS Region."

            return True, ""

        #
        # ISO 8601 duration used by AWS FIS (for example PT1M or PT30S)
        #

        if field_type == "iso8601_duration":
            if not is_iso8601_duration(value):
                return (
                    False,
                    ("Enter an ISO 8601 duration, for example PT1M, PT30S, "
                    "PT1H, or P1D."),
                )

            return True, ""

        #
        # Default text validation
        #

        return True, ""
