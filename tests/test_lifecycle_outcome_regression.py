from chaosforge.lifecycle.lifecycle import LifecycleCoordinator
from chaosforge.models.execution import ExecutionContext, ExecutionState


class SequenceCheck:
    name = "sequence-check"
    recovery_supported = True

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)

    def validate(self, _target, _baseline):
        return {"passed": next(self.outcomes)}


def _context():
    return ExecutionContext(
        execution_id="execution",
        experiment_id="experiment",
        service="lambda",
        experiment_name="Experiment",
    )


def test_successful_recovery_does_not_erase_failed_post_validation():
    lifecycle = LifecycleCoordinator(SequenceCheck([False, True]))
    context = _context()

    assert lifecycle.validate(context, {}, phase="post") is False
    assert lifecycle.validate_recovery(context, {}) is True

    assert context.state is ExecutionState.VALIDATION_FAILED
    assert context.validation["result"]["passed"] is False
    assert context.recovery["result"]["passed"] is True


def test_failed_recovery_has_recovery_failed_state():
    lifecycle = LifecycleCoordinator(SequenceCheck([True, False]))
    context = _context()

    assert lifecycle.validate(context, {}, phase="post") is True
    assert lifecycle.validate_recovery(context, {}) is False

    assert context.state is ExecutionState.RECOVERY_FAILED
