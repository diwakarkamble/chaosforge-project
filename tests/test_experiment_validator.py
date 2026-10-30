from chaosforge.application.validation.experiment import (
    ExperimentValidator,
)


def test_valid_lambda_memory():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "lambda_name",
                "required": True,
                "type": "aws_resource",
            },
            {
                "name": "aws_region",
                "required": True,
                "type": "aws_region",
            },
            {
                "name": "target_memory_size",
                "required": True,
                "type": "integer",
                "min": 128,
                "max": 10240,
            },
            {
                "name": "wait_seconds",
                "required": True,
                "type": "integer",
                "min": 1,
                "max": 3600,
            },
        ]
    }

    variables = {
        "lambda_name": "chaos-test-lambda",
        "aws_region": "eu-central-1",
        "target_memory_size": 512,
        "wait_seconds": 30,
    }

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_lambda_memory_below_minimum():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "target_memory_size",
                "required": True,
                "type": "integer",
                "min": 128,
                "max": 10240,
            }
        ]
    }

    variables = {
        "target_memory_size": 102,
    }

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is False

    assert any(
        "target_memory_size" in error
        and "128" in error
        for error in result["errors"]
    )


def test_lambda_memory_above_maximum():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "target_memory_size",
                "required": True,
                "type": "integer",
                "min": 128,
                "max": 10240,
            }
        ]
    }

    variables = {
        "target_memory_size": 20000,
    }

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is False

    assert any(
        "target_memory_size" in error
        and "10240" in error
        for error in result["errors"]
    )


def test_missing_required_variable():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "lambda_name",
                "required": True,
                "type": "aws_resource",
            }
        ]
    }

    variables = {}

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is False

    assert any(
        "lambda_name" in error
        and "missing" in error.lower()
        for error in result["errors"]
    )


def test_invalid_integer():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "target_memory_size",
                "required": True,
                "type": "integer",
                "min": 128,
                "max": 10240,
            }
        ]
    }

    variables = {
        "target_memory_size": "not-a-number",
    }

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is False

    assert any(
        "target_memory_size" in error
        and "integer" in error.lower()
        for error in result["errors"]
    )


def test_choice_region_number_and_duration_are_validated_for_noninteractive_execution():
    experiment = {
        "inputs": [
            {"name": "mode", "type": "choice", "choices": ["one", "all"]},
            {"name": "region", "type": "aws_region"},
            {"name": "percentage", "type": "number", "min": 1, "max": 100},
            {"name": "duration", "type": "iso8601_duration"},
        ]
    }

    result = ExperimentValidator().validate(
        experiment,
        {"mode": "invalid", "region": "bad-region", "percentage": "101", "duration": "one-minute"},
    )

    assert result["valid"] is False
    assert len(result["errors"]) == 4


def test_invalid_legacy_local_duration_is_reported_as_iso8601_error():
    result = ExperimentValidator().validate(
        {"inputs": [{"name": "wait_seconds", "type": "integer"}]},
        {"wait_seconds": "invalid"},
    )

    assert result["valid"] is False
    assert "ISO 8601 duration" in result["errors"][0]


def test_number_and_yes_no_validation_reject_invalid_values():
    experiment = {
        "inputs": [
            {"name": "boolean_number", "type": "number"},
            {"name": "text_number", "type": "number"},
            {"name": "confirmation", "type": "yes_no"},
        ]
    }

    result = ExperimentValidator().validate(
        experiment,
        {"boolean_number": True, "text_number": "not-a-number", "confirmation": "maybe"},
    )

    assert result["valid"] is False
    assert result["errors"] == [
        "Variable 'boolean_number' must be a number.",
        "Variable 'text_number' must be a number.",
        "Variable 'confirmation' must be Yes or No.",
    ]


def test_integer_minimum_boundary_is_valid():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "target_memory_size",
                "required": True,
                "type": "integer",
                "min": 128,
                "max": 10240,
            }
        ]
    }

    variables = {
        "target_memory_size": 128,
    }

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_integer_maximum_boundary_is_valid():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "target_memory_size",
                "required": True,
                "type": "integer",
                "min": 128,
                "max": 10240,
            }
        ]
    }

    variables = {
        "target_memory_size": 10240,
    }

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_unknown_variable_generates_warning():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "target_memory_size",
                "required": True,
                "type": "integer",
                "min": 128,
                "max": 10240,
            }
        ]
    }

    variables = {
        "target_memory_size": 512,
        "unexpected_variable": "test",
    }

    result = validator.validate(
        experiment,
        variables,
    )

    assert result["valid"] is True

    assert any(
        "unexpected_variable" in warning
        for warning in result["warnings"]
    )


def test_invalid_inputs_definition():
    validator = ExperimentValidator()

    result = validator.validate(
        {"inputs": "invalid"},
        {},
    )

    assert result["valid"] is False
    assert result["errors"] == [
        "Experiment metadata contains an invalid inputs definition."
    ]


def test_blank_required_variable_is_invalid():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "lambda_name",
                "required": True,
                "type": "aws_resource",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"lambda_name": "   "},
    )

    assert result["valid"] is False
    assert any(
        "lambda_name" in error
        and "missing" in error.lower()
        for error in result["errors"]
    )


def test_integer_boolean_is_invalid():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "count",
                "required": True,
                "type": "integer",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"count": True},
    )

    assert result["valid"] is False
    assert any(
        "count" in error
        and "integer" in error.lower()
        for error in result["errors"]
    )


def test_invalid_integer_metadata_limits_are_ignored():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "count",
                "required": True,
                "type": "integer",
                "min": "invalid",
                "max": "invalid",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"count": 10},
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_float_value_is_valid():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "cpu_load",
                "required": True,
                "type": "float",
                "min": 0.0,
                "max": 100.0,
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"cpu_load": 50.5},
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_invalid_float():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "cpu_load",
                "required": True,
                "type": "float",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"cpu_load": "not-a-number"},
    )

    assert result["valid"] is False
    assert any(
        "cpu_load" in error
        and "float" in error.lower()
        for error in result["errors"]
    )


def test_float_boolean_is_invalid():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "cpu_load",
                "required": True,
                "type": "float",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"cpu_load": True},
    )

    assert result["valid"] is False
    assert any(
        "cpu_load" in error
        and "float" in error.lower()
        for error in result["errors"]
    )


def test_float_below_minimum():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "cpu_load",
                "required": True,
                "type": "float",
                "min": 10.0,
                "max": 100.0,
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"cpu_load": 5.5},
    )

    assert result["valid"] is False
    assert any(
        "cpu_load" in error
        and "10.0" in error
        for error in result["errors"]
    )


def test_float_above_maximum():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "cpu_load",
                "required": True,
                "type": "float",
                "min": 0.0,
                "max": 100.0,
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"cpu_load": 105.5},
    )

    assert result["valid"] is False
    assert any(
        "cpu_load" in error
        and "100.0" in error
        for error in result["errors"]
    )


def test_invalid_float_metadata_limits_are_ignored():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "cpu_load",
                "required": True,
                "type": "float",
                "min": "invalid",
                "max": "invalid",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"cpu_load": 50.5},
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_valid_boolean_values():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "enabled",
                "required": True,
                "type": "boolean",
            }
        ]
    }

    for value in (True, False, "true", "false", " TRUE ", " False "):
        result = validator.validate(
            experiment,
            {"enabled": value},
        )

        assert result["valid"] is True
        assert result["errors"] == []


def test_invalid_boolean():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "enabled",
                "required": True,
                "type": "boolean",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {"enabled": "yes"},
    )

    assert result["valid"] is False
    assert any(
        "enabled" in error
        and "boolean" in error.lower()
        for error in result["errors"]
    )


def test_non_dict_input_definitions_are_ignored():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            "invalid",
            {
                "name": "count",
                "required": True,
                "type": "integer",
            },
        ]
    }

    result = validator.validate(
        experiment,
        {"count": 10},
    )

    assert result["valid"] is True
    assert result["errors"] == []

def test_invalid_boolean_non_string_value():
    assert ExperimentValidator._is_boolean(123) is False


def test_optional_input_is_skipped():
    validator = ExperimentValidator()

    experiment = {
        "inputs": [
            {
                "name": "optional_value",
                "required": False,
                "type": "string",
            }
        ]
    }

    result = validator.validate(
        experiment,
        {},
    )

    assert result["valid"] is True
    assert result["errors"] == []
