from chaosforge.application.validation.input import Validator


def test_required_validation():

    field = {"required": True}

    valid, _ = Validator.validate(field, "")

    assert valid is False


def test_optional_validation():

    field = {"required": False}

    valid, _ = Validator.validate(field, "")

    assert valid is True


def test_integer_validation():

    field = {"type": "integer"}

    valid, _ = Validator.validate(field, "10")

    assert valid is True


def test_invalid_integer():

    field = {"type": "integer"}

    valid, _ = Validator.validate(field, "abc")

    assert valid is False


def test_integer_min_validation():

    field = {"type": "integer", "min": 5}

    valid, _ = Validator.validate(field, "3")

    assert valid is False


def test_integer_max_validation():

    field = {"type": "integer", "max": 10}

    valid, _ = Validator.validate(field, "20")

    assert valid is False


def test_float_validation():

    field = {"type": "float"}

    valid, _ = Validator.validate(field, "5.5")

    assert valid is True


def test_invalid_float():

    field = {"type": "float"}

    valid, _ = Validator.validate(field, "abc")

    assert valid is False


def test_float_min_validation():

    field = {"type": "float", "min": 2.5}

    valid, _ = Validator.validate(field, "1.5")

    assert valid is False


def test_float_max_validation():

    field = {"type": "float", "max": 5.5}

    valid, _ = Validator.validate(field, "10.5")

    assert valid is False


def test_yes_no_validation():

    field = {"type": "yes_no"}

    valid, _ = Validator.validate(field, "yes")

    assert valid is True


def test_invalid_yes_no():

    field = {"type": "yes_no"}

    valid, _ = Validator.validate(field, "maybe")

    assert valid is False


def test_choice_validation():

    field = {"type": "choice", "choices": ["red", "green", "blue"]}

    valid, _ = Validator.validate(field, "green")

    assert valid is True


def test_invalid_choice():

    field = {"type": "choice", "choices": ["red", "green"]}

    valid, _ = Validator.validate(field, "yellow")

    assert valid is False


def test_valid_arn():

    field = {"type": "arn"}

    valid, _ = Validator.validate(
        field, "arn:aws:lambda:eu-central-1:123456789012:function:test"
    )

    assert valid is True


def test_invalid_arn():

    field = {"type": "arn"}

    valid, _ = Validator.validate(field, "invalid-arn")

    assert valid is False


def test_valid_region():

    field = {"type": "region"}

    valid, _ = Validator.validate(field, "eu-central-1")

    assert valid is True


def test_invalid_region():

    field = {"type": "region"}

    valid, _ = Validator.validate(field, "central-europe")

    assert valid is False


def test_valid_iso8601_duration():
    field = {"type": "iso8601_duration"}

    for value in ("PT1M", "PT30S", "PT1H30M", "P1D"):
        valid, _ = Validator.validate(field, value)
        assert valid is True


def test_invalid_iso8601_duration_has_actionable_message():
    for value in ("1M", "pt1m", "PT", ""):
        field = {
            "type": "iso8601_duration",
            "required": value == "",
        }
        valid, message = Validator.validate(field, value)

        assert valid is False
        if value:
            assert "PT1M" in message


def test_default_text_validation():

    field = {"type": "text"}

    valid, _ = Validator.validate(field, "ChaosForge")

    assert valid is True
