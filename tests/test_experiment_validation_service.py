from types import SimpleNamespace

from chaosforge.application.services.experiment_validation import (
    ExperimentValidationService,
)


def make_lambda_experiment(
    target_memory_size=512,
    wait_seconds=30,
):
    return SimpleNamespace(
        id="lambda-memory",
        service="lambda",
        name="Memory Modification",
        variables={
            "lambda_name": "chaos-test-lambda",
            "aws_region": "eu-central-1",
            "target_memory_size": target_memory_size,
            "wait_seconds": wait_seconds,
        },
    )


def test_lambda_experiment_valid():
    service = ExperimentValidationService()

    experiment = make_lambda_experiment(
        target_memory_size=512,
        wait_seconds=30,
    )

    result = service.validate_experiment(
        experiment
    )

    assert result["valid"] is True
    assert result["errors"] == []


def test_lambda_memory_below_metadata_minimum():
    service = ExperimentValidationService()

    experiment = make_lambda_experiment(
        target_memory_size=102,
        wait_seconds=30,
    )

    result = service.validate_experiment(
        experiment
    )

    assert result["valid"] is False

    assert any(
        "target_memory_size" in error
        and "128" in error
        for error in result["errors"]
    )


def test_lambda_memory_above_metadata_maximum():
    service = ExperimentValidationService()

    experiment = make_lambda_experiment(
        target_memory_size=20000,
        wait_seconds=30,
    )

    result = service.validate_experiment(
        experiment
    )

    assert result["valid"] is False

    assert any(
        "target_memory_size" in error
        and "10240" in error
        for error in result["errors"]
    )


def test_lambda_missing_required_variable():
    service = ExperimentValidationService()

    experiment = make_lambda_experiment()

    del experiment.variables["lambda_name"]

    result = service.validate_experiment(
        experiment
    )

    assert result["valid"] is False

    assert any(
        "lambda_name" in error
        and "missing" in error.lower()
        for error in result["errors"]
    )


def test_unknown_experiment_metadata():
    service = ExperimentValidationService()

    experiment = SimpleNamespace(
        id="does-not-exist",
        service="lambda",
        name="Unknown Experiment",
        variables={},
    )

    result = service.validate_experiment(
        experiment
    )

    assert result["valid"] is False

    assert any(
        "metadata not found" in error.lower()
        for error in result["errors"]
    )


def test_campaign_validation():
    service = ExperimentValidationService()

    valid_experiment = make_lambda_experiment(
        target_memory_size=512,
        wait_seconds=30,
    )

    invalid_experiment = make_lambda_experiment(
        target_memory_size=102,
        wait_seconds=30,
    )

    campaign = SimpleNamespace(
        experiments=[
            valid_experiment,
            invalid_experiment,
        ]
    )

    result = service.validate_campaign(
        campaign
    )

    assert result["valid"] is False

    assert len(
        result["experiments"]
    ) == 2

    assert (
        result["experiments"][0]["valid"]
        is True
    )

    assert (
        result["experiments"][1]["valid"]
        is False
    )
