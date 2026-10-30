import pytest

from chaosforge.lifecycle.checks.base import ExperimentCheck


class ConcreteExperimentCheck(ExperimentCheck):
    name = "test-check"

    def capture(self, target):
        return super().capture(target)

    def validate(self, target, baseline):
        return super().validate(target, baseline)


def test_experiment_check_capture_raises_not_implemented():
    check = ConcreteExperimentCheck()

    with pytest.raises(NotImplementedError):
        check.capture({"id": "test-target"})


def test_experiment_check_validate_raises_not_implemented():
    check = ConcreteExperimentCheck()

    with pytest.raises(NotImplementedError):
        check.validate(
            {"id": "test-target"},
            {"state": "baseline"},
        )