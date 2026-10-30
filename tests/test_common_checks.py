from typing import Any

from chaosforge.lifecycle.checks.adapter import ResourceAdapter
from chaosforge.lifecycle.checks.common import CommonResourceCheck


class DummyAdapter(ResourceAdapter):
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        return self.snapshot


def test_common_resource_check_capture():
    check = CommonResourceCheck(
        DummyAdapter(
            {
                "exists": True,
                "state": "running",
            }
        )
    )

    result = check.capture({"id": "resource-1"})

    assert result["exists"] is True
    assert result["state"] == "running"


def test_common_resource_check_validation_passes():
    check = CommonResourceCheck(
        DummyAdapter(
            {
                "exists": True,
                "state": "running",
            }
        ),
        predicates={
            "exists": lambda current, baseline: (
                current["exists"] == baseline["exists"]
            ),
            "state": lambda current, baseline: (
                current["state"] == baseline["state"]
            ),
        },
    )

    baseline = {
        "exists": True,
        "state": "running",
    }

    result = check.validate(
        {"id": "resource-1"},
        baseline,
    )

    assert result["passed"] is True
    assert result["checks"]["exists"] is True
    assert result["checks"]["state"] is True


def test_common_resource_check_validation_fails():
    check = CommonResourceCheck(
        DummyAdapter(
            {
                "exists": True,
                "state": "stopped",
            }
        ),
        predicates={
            "state": lambda current, baseline: (
                current["state"] == baseline["state"]
            ),
        },
    )

    baseline = {
        "exists": True,
        "state": "running",
    }

    result = check.validate(
        {"id": "resource-1"},
        baseline,
    )

    assert result["passed"] is False
    assert result["checks"]["state"] is False


def test_common_resource_check_custom_predicate():
    check = CommonResourceCheck(
        DummyAdapter(
            {
                "exists": True,
                "desired_replicas": 10,
                "ready_replicas": 10,
            }
        ),
        predicates={
            "desired_replicas": lambda current, baseline: (
                current["desired_replicas"]
                == baseline["desired_replicas"]
            ),
            "ready_replicas": lambda current, baseline: (
                current["ready_replicas"]
                == baseline["ready_replicas"]
            ),
        },
    )

    baseline = {
        "exists": True,
        "desired_replicas": 10,
        "ready_replicas": 10,
    }

    result = check.validate(
        {"id": "resource-1"},
        baseline,
    )

    assert result["passed"] is True
    assert result["checks"]["desired_replicas"] is True
    assert result["checks"]["ready_replicas"] is True


def test_common_resource_check_capture_failure():
    class FailingAdapter(ResourceAdapter):
        def capture(self, target: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("resource unavailable")

    check = CommonResourceCheck(FailingAdapter())

    result = check.validate(
        {"id": "resource-1"},
        {"exists": True},
    )

    assert result["passed"] is False
    assert result["exists"] is False
    assert result["error"] == "resource unavailable"


def test_common_resource_check_retries_until_eventual_state_is_observed(monkeypatch):
    snapshots = iter((
        {"state": "shutting-down"},
        {"state": "terminated"},
    ))

    class TransitioningAdapter(ResourceAdapter):
        def capture(self, target: dict[str, Any]) -> dict[str, Any]:
            return next(snapshots)

    check = CommonResourceCheck(
        TransitioningAdapter(),
        predicates={"terminated": lambda current, _baseline: current["state"] == "terminated"},
        validation_timeout_seconds=60,
        validation_poll_seconds=1,
    )
    monkeypatch.setattr("chaosforge.lifecycle.checks.common.time.sleep", lambda _: None)

    assert check.validate({"id": "resource-1"}, {})["passed"] is True
