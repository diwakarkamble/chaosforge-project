from chaosforge.lifecycle.checks.lambda_adapter import LambdaResourceAdapter
from chaosforge.lifecycle.checks.resolver import CheckResolver


class FakeLambdaAdapter(LambdaResourceAdapter):
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)

    def capture(self, target):
        return next(self.snapshots)


def test_lambda_memory_validation_passes_when_memory_is_restored():
    resolver = CheckResolver()

    check = resolver.resolve(
        type("Experiment", (), {"id": "lambda-memory"})()
    )

    baseline = {
        "exists": True,
        "configuration": {
            "memory_size": 512,
        },
    }

    current = {
        "exists": True,
        "configuration": {
            "memory_size": 512,
        },
    }

    check.adapter = FakeLambdaAdapter([current])

    result = check.validate(
        {
            "lambda_name": "demo",
            "aws_region": "ap-south-1",
        },
        baseline,
    )

    assert result["passed"] is True
    assert result["checks"]["memory_size"] is True
    assert result["checks"]["exists"] is True
    assert result["checks"]["resource_exists"] is True


def test_lambda_memory_validation_fails_when_memory_is_not_restored():
    resolver = CheckResolver()

    check = resolver.resolve(
        type("Experiment", (), {"id": "lambda-memory"})()
    )

    baseline = {
        "exists": True,
        "configuration": {
            "memory_size": 512,
        },
    }

    current = {
        "exists": True,
        "configuration": {
            "memory_size": 1024,
        },
    }

    check.adapter = FakeLambdaAdapter([current])

    result = check.validate(
        {
            "lambda_name": "demo",
            "aws_region": "ap-south-1",
        },
        baseline,
    )

    assert result["passed"] is False
    assert result["checks"]["memory_size"] is False


def test_lambda_timeout_validation_passes_when_timeout_is_restored():
    resolver = CheckResolver()

    check = resolver.resolve(
        type("Experiment", (), {"id": "lambda-timeout"})()
    )

    baseline = {
        "exists": True,
        "configuration": {
            "timeout": 30,
        },
    }

    current = {
        "exists": True,
        "configuration": {
            "timeout": 30,
        },
    }

    check.adapter = FakeLambdaAdapter([current])

    result = check.validate(
        {
            "lambda_name": "demo",
            "aws_region": "ap-south-1",
        },
        baseline,
    )

    assert result["passed"] is True
    assert result["checks"]["timeout"] is True


def test_lambda_concurrency_validation_detects_failed_recovery():
    resolver = CheckResolver()

    check = resolver.resolve(
        type("Experiment", (), {"id": "lambda-concurrency"})()
    )

    baseline = {
        "exists": True,
        "concurrency": {
            "reserved_concurrency": 25,
        },
    }

    current = {
        "exists": True,
        "concurrency": {
            "reserved_concurrency": 10,
        },
    }

    check.adapter = FakeLambdaAdapter([current])

    result = check.validate(
        {
            "lambda_name": "demo",
            "aws_region": "ap-south-1",
        },
        baseline,
    )

    assert result["passed"] is False
    assert result["checks"]["reserved_concurrency"] is False


def test_lambda_retry_validation_passes_with_default_retry_baseline():
    resolver = CheckResolver()

    check = resolver.resolve(
        type("Experiment", (), {"id": "lambda-retry"})()
    )

    baseline = {
        "exists": True,
        "async_invoke": {
            "maximum_retry_attempts": 2,
        },
    }

    current = {
        "exists": True,
        "async_invoke": {
            "maximum_retry_attempts": 2,
        },
    }

    check.adapter = FakeLambdaAdapter([current])

    result = check.validate(
        {
            "lambda_name": "demo",
            "aws_region": "ap-south-1",
        },
        baseline,
    )

    assert result["passed"] is True
    assert result["checks"]["maximum_retry_attempts"] is True
