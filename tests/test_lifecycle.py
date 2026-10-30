from chaosforge.lifecycle.execution_states import ExecutionState
from chaosforge.lifecycle.lifecycle import LifecycleCoordinator


class MockCheck:
    name = "mock-check"

    def capture(self, target):
        return {"baseline": 10}

    def validate(self, target, baseline):
        return {
            "passed": True,
            "baseline": baseline,
            "current": {"value": 10},
        }


class FailedCaptureCheck:
    name = "failed-capture"

    def capture(self, target):
        raise RuntimeError("capture failed")


class FailedValidationCheck:
    name = "failed-validation"

    def capture(self, target):
        return {"baseline": 10}

    def validate(self, target, baseline):
        return {
            "passed": False,
            "baseline": baseline,
            "current": {"value": 5},
        }


class ExceptionValidationCheck:
    name = "exception-validation"

    def capture(self, target):
        return {"baseline": 10}

    def validate(self, target, baseline):
        raise RuntimeError("validation failed")


def create_context(coordinator):
    return coordinator.create_context(
        execution_id="execution-1",
        experiment_id="experiment-1",
        service="eks",
        experiment_name="Replica Reduction",
    )


def test_create_context():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    assert context.execution_id == "execution-1"
    assert context.experiment_id == "experiment-1"
    assert context.service == "eks"
    assert context.experiment_name == "Replica Reduction"
    assert context.state == ExecutionState.PLANNED


def test_precheck_without_configured_check():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    result = coordinator.run_precheck(
        context,
        {"name": "target"},
    )

    assert result is True
    assert context.precheck["enabled"] is False
    assert context.precheck["passed"] is True
    assert "No lifecycle check configured." in context.precheck["message"]


def test_precheck_success():
    coordinator = LifecycleCoordinator(
        check=MockCheck(),
    )

    context = create_context(coordinator)

    result = coordinator.run_precheck(
        context,
        {"name": "target"},
    )

    assert result is True
    assert context.baseline == {"baseline": 10}
    assert context.precheck["enabled"] is True
    assert context.precheck["passed"] is True
    assert context.precheck["check"] == "mock-check"


def test_precheck_failure():
    coordinator = LifecycleCoordinator(
        check=FailedCaptureCheck(),
    )

    context = create_context(coordinator)

    result = coordinator.run_precheck(
        context,
        {"name": "target"},
    )

    assert result is False
    assert context.precheck["enabled"] is True
    assert context.precheck["passed"] is False
    assert context.precheck["error"] == "capture failed"
    assert context.errors == [
        "Precheck failed: capture failed"
    ]
    assert context.state == ExecutionState.PRECHECK_FAILED


def test_mark_running():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    coordinator.mark_running(context)

    assert context.state == ExecutionState.RUNNING
    assert context.started_at is not None


def test_mark_injection_succeeded():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)
    coordinator.mark_running(context)

    coordinator.mark_injection_succeeded(context)

    assert (
        context.state
        == ExecutionState.FAULT_INJECTION_SUCCEEDED
    )


def test_mark_injection_failed():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)
    coordinator.mark_running(context)

    coordinator.mark_injection_failed(
        context,
        "injection failed",
    )

    assert (
        context.state
        == ExecutionState.FAULT_INJECTION_FAILED
    )
    assert context.errors == ["injection failed"]


def test_validation_without_configured_check():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    result = coordinator.validate(
        context,
        {"name": "target"},
        phase="post",
    )

    assert result is True
    assert context.validation["enabled"] is False
    assert context.validation["passed"] is True
    assert context.validation["phase"] == "post"


def test_validation_success():
    coordinator = LifecycleCoordinator(
        check=MockCheck(),
    )

    context = create_context(coordinator)
    coordinator.mark_running(context)
    coordinator.mark_injection_succeeded(context)

    context.baseline = {"baseline": 10}

    result = coordinator.validate(
        context,
        {"name": "target"},
    )

    assert result is True
    assert context.validation["enabled"] is True
    assert context.validation["phase"] == "post"
    assert context.validation["check"] == "mock-check"
    assert context.validation["result"]["passed"] is True
    assert context.state == ExecutionState.VALIDATION_PASSED


def test_validation_failure():
    coordinator = LifecycleCoordinator(
        check=FailedValidationCheck(),
    )

    context = create_context(coordinator)
    coordinator.mark_running(context)
    coordinator.mark_injection_succeeded(context)

    context.baseline = {"baseline": 10}

    result = coordinator.validate(
        context,
        {"name": "target"},
    )

    assert result is False
    assert context.validation["enabled"] is True
    assert context.validation["result"]["passed"] is False
    assert context.state == ExecutionState.VALIDATION_FAILED


def test_validation_exception():
    coordinator = LifecycleCoordinator(
        check=ExceptionValidationCheck(),
    )

    context = create_context(coordinator)
    coordinator.mark_running(context)
    coordinator.mark_injection_succeeded(context)

    context.baseline = {"baseline": 10}

    result = coordinator.validate(
        context,
        {"name": "target"},
    )

    assert result is False
    assert context.validation["enabled"] is True
    assert context.validation["passed"] is False
    assert context.validation["error"] == "validation failed"
    assert context.errors == [
        "Validation failed: validation failed"
    ]
    assert context.state == ExecutionState.VALIDATION_FAILED


def test_recovery_without_configured_check():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    result = coordinator.validate_recovery(
        context,
        {"name": "target"},
    )

    assert result is True
    assert context.recovery["enabled"] is False
    assert context.recovery["passed"] is True
    assert context.recovery["phase"] == "recovery"


def test_recovery_success():
    coordinator = LifecycleCoordinator(
        check=MockCheck(),
    )

    context = create_context(coordinator)
    coordinator.mark_running(context)
    coordinator.mark_injection_succeeded(context)

    context.baseline = {"baseline": 10}

    coordinator.validate(
        context,
        {"name": "target"},
    )

    result = coordinator.validate_recovery(
        context,
        {"name": "target"},
    )

    assert result is True
    assert context.recovery["enabled"] is True
    assert context.recovery["passed"] is True
    assert context.recovery["phase"] == "recovery"
    assert context.recovery["check"] == "mock-check"


def test_recovery_failure():
    coordinator = LifecycleCoordinator(
        check=FailedValidationCheck(),
    )

    context = create_context(coordinator)
    coordinator.mark_running(context)
    coordinator.mark_injection_succeeded(context)

    context.baseline = {"baseline": 10}

    result = coordinator.validate_recovery(
        context,
        {"name": "target"},
    )

    assert result is False
    assert context.recovery["enabled"] is True
    assert context.recovery["passed"] is False
    assert context.recovery["phase"] == "recovery"
    assert context.state == ExecutionState.RECOVERY_FAILED


def test_recovery_exception():
    coordinator = LifecycleCoordinator(
        check=ExceptionValidationCheck(),
    )

    context = create_context(coordinator)
    coordinator.mark_running(context)
    coordinator.mark_injection_succeeded(context)

    context.baseline = {"baseline": 10}

    result = coordinator.validate_recovery(
        context,
        {"name": "target"},
    )

    assert result is False
    assert context.recovery["enabled"] is True
    assert context.recovery["passed"] is False
    assert context.recovery["phase"] == "recovery"
    assert context.recovery["error"] == "validation failed"
    assert context.errors == [
        "Recovery validation failed: validation failed"
    ]
    assert context.state == ExecutionState.RECOVERY_FAILED


def test_record_recovery():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    recovery_result = {
        "enabled": True,
        "passed": True,
        "phase": "recovery",
    }

    coordinator.record_recovery(
        context,
        recovery_result,
    )

    assert context.recovery == recovery_result


def test_mark_recovery_failed():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    coordinator.mark_recovery_failed(
        context,
        "recovery failed",
    )

    assert context.errors == ["recovery failed"]
    assert context.state == ExecutionState.RECOVERY_FAILED


def test_complete():
    coordinator = LifecycleCoordinator()

    context = create_context(coordinator)

    coordinator.mark_running(context)
    coordinator.mark_injection_succeeded(context)
    coordinator.validate(
        context,
        {"name": "target"},
    )

    coordinator.complete(context)

    assert context.completed_at is not None