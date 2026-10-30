from typing import Any


class ExperimentValidator:
    """
    Validates a ChaosForge experiment definition and its variables.

    This validator operates on already-loaded experiment metadata.
    It does not execute the experiment or make AWS changes.
    """

    def validate(
        self,
        experiment: dict[str, Any],
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Validate an experiment against its metadata.

        Returns a structured validation result:

            {
                "valid": True/False,
                "errors": [],
                "warnings": []
            }
        """

        errors = []
        warnings = []

        inputs = experiment.get("inputs", [])

        if not isinstance(inputs, list):
            errors.append(
                "Experiment metadata contains an invalid inputs definition."
            )

            return self._result(
                errors,
                warnings,
            )

        input_definitions = {
            item.get("name"): item
            for item in inputs
            if isinstance(item, dict)
            and item.get("name")
        }

        # ---------------------------------------------------------
        # Required inputs
        # ---------------------------------------------------------

        for name, definition in input_definitions.items():
            if not definition.get("required", False):
                continue

            value = variables.get(name)

            if value is None or str(value).strip() == "":
                errors.append(
                    f"Required variable '{name}' is missing."
                )

        # ---------------------------------------------------------
        # Unknown variables
        # ---------------------------------------------------------

        for name in variables:
            if name not in input_definitions:
                warnings.append(
                    f"Variable '{name}' is not defined in experiment metadata."
                )

        # ---------------------------------------------------------
        # Type and range validation
        # ---------------------------------------------------------

        for name, definition in input_definitions.items():

            if name not in variables:
                continue

            value = variables.get(name)

            if value is None or str(value).strip() == "":
                continue

            input_type = definition.get("type")

            # -----------------------------------------------------
            # Integer
            # -----------------------------------------------------

            if input_type == "integer":

                integer_value = self._parse_integer(
                    name,
                    value,
                    errors,
                )

                if integer_value is None:
                    continue

                minimum = definition.get("min")
                maximum = definition.get("max")

                if minimum is not None:
                    minimum_value = self._parse_integer_limit(
                        minimum
                    )

                    if (
                        minimum_value is not None
                        and integer_value < minimum_value
                    ):
                        errors.append(
                            f"Variable '{name}' must be "
                            f"greater than or equal to "
                            f"{minimum_value}. "
                            f"Received: {integer_value}."
                        )

                if maximum is not None:
                    maximum_value = self._parse_integer_limit(
                        maximum
                    )

                    if (
                        maximum_value is not None
                        and integer_value > maximum_value
                    ):
                        errors.append(
                            f"Variable '{name}' must be "
                            f"less than or equal to "
                            f"{maximum_value}. "
                            f"Received: {integer_value}."
                        )

            # -----------------------------------------------------
            # Float
            # -----------------------------------------------------

            elif input_type == "float":

                float_value = self._parse_float(
                    name,
                    value,
                    errors,
                )

                if float_value is None:
                    continue

                minimum = definition.get("min")
                maximum = definition.get("max")

                if minimum is not None:
                    minimum_value = self._parse_float_limit(
                        minimum
                    )

                    if (
                        minimum_value is not None
                        and float_value < minimum_value
                    ):
                        errors.append(
                            f"Variable '{name}' must be "
                            f"greater than or equal to "
                            f"{minimum_value}. "
                            f"Received: {float_value}."
                        )

                if maximum is not None:
                    maximum_value = self._parse_float_limit(
                        maximum
                    )

                    if (
                        maximum_value is not None
                        and float_value > maximum_value
                    ):
                        errors.append(
                            f"Variable '{name}' must be "
                            f"less than or equal to "
                            f"{maximum_value}. "
                            f"Received: {float_value}."
                        )

            # -----------------------------------------------------
            # Boolean
            # -----------------------------------------------------

            elif input_type == "boolean":

                if not self._is_boolean(value):
                    errors.append(
                        f"Variable '{name}' must be a boolean. "
                        f"Received: {value!r}."
                    )

        # ---------------------------------------------------------
        # Result
        # ---------------------------------------------------------

        return self._result(
            errors,
            warnings,
        )

    @staticmethod
    def _result(
        errors: list[str],
        warnings: list[str],
    ) -> dict[str, Any]:
        """
        Build the structured validation result.
        """

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
        }

    @staticmethod
    def _parse_integer(
        name: str,
        value: Any,
        errors: list[str],
    ) -> int | None:
        """
        Parse an integer input.
        """

        if isinstance(value, bool):
            errors.append(
                f"Variable '{name}' must be an integer. "
                f"Received: {value!r}."
            )

            return None

        try:
            return int(value)

        except (TypeError, ValueError):
            errors.append(
                f"Variable '{name}' must be an integer. "
                f"Received: {value!r}."
            )

            return None

    @staticmethod
    def _parse_integer_limit(
        value: Any,
    ) -> int | None:
        """
        Parse an integer metadata limit.
        """

        try:
            return int(value)

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_float(
        name: str,
        value: Any,
        errors: list[str],
    ) -> float | None:
        """
        Parse a floating-point input.
        """

        if isinstance(value, bool):
            errors.append(
                f"Variable '{name}' must be a float. "
                f"Received: {value!r}."
            )

            return None

        try:
            return float(value)

        except (TypeError, ValueError):
            errors.append(
                f"Variable '{name}' must be a float. "
                f"Received: {value!r}."
            )

            return None

    @staticmethod
    def _parse_float_limit(
        value: Any,
    ) -> float | None:
        """
        Parse a floating-point metadata limit.
        """

        try:
            return float(value)

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_boolean(
        value: Any,
    ) -> bool:
        """
        Determine whether a value represents a boolean.
        """

        if isinstance(value, bool):
            return True

        if isinstance(value, str):
            return value.strip().lower() in {
                "true",
                "false",
            }

        return False
