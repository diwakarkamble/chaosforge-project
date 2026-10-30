from chaosforge.application.experiment_aliases import (
    EXPERIMENT_ALIASES,
)


def test_lambda_delay_alias():
    alias = EXPERIMENT_ALIASES["lambda-delay"]

    assert alias["service"] == "lambda"
    assert alias["fis_service"] == "lambda"
    assert alias["fis_experiment"] == "invocation-delay"


def test_lambda_error_alias():
    alias = EXPERIMENT_ALIASES["lambda-error"]

    assert alias["service"] == "lambda"
    assert alias["fis_service"] == "lambda"
    assert alias["fis_experiment"] == "invocation-error"


def test_lambda_http_alias():
    alias = EXPERIMENT_ALIASES["lambda-http"]

    assert alias["service"] == "lambda"
    assert alias["fis_service"] == "lambda"
    assert alias["fis_experiment"] == "http-response"


def test_all_aliases_have_required_keys():
    required_keys = {
        "service",
        "fis_service",
        "fis_experiment",
    }

    for alias in EXPERIMENT_ALIASES.values():
        assert set(alias.keys()) == required_keys


def test_all_services_are_lambda():
    for alias in EXPERIMENT_ALIASES.values():
        assert alias["service"] == "lambda"
        assert alias["fis_service"] == "lambda"
