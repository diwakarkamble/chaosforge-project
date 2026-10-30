"""Execution states and evidence context."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ExecutionState(str, Enum):
    """Lifecycle state for one experiment execution."""

    PLANNED = "PLANNED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    RUNNING = "RUNNING"
    ABORTED_BY_GUARDRAIL = "ABORTED_BY_GUARDRAIL"
    ABORTED_BY_USER = "ABORTED_BY_USER"
    FAULT_INJECTION_FAILED = "FAULT_INJECTION_FAILED"
    FAULT_INJECTION_SUCCEEDED = "FAULT_INJECTION_SUCCEEDED"
    VALIDATION_PASSED = "VALIDATION_PASSED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CLEANUP_FAILED = "CLEANUP_FAILED"


@dataclass
class ExecutionContext:
    """Structured lifecycle evidence for one experiment execution."""

    execution_id: str
    experiment_id: str
    service: str
    experiment_name: str
    state: ExecutionState = ExecutionState.PLANNED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    baseline: dict[str, Any] = field(default_factory=dict)
    precheck: dict[str, Any] = field(default_factory=dict)
    injection: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    recovery: dict[str, Any] = field(default_factory=dict)
    target: dict[str, Any] = field(default_factory=dict)
    provider: dict[str, Any] = field(default_factory=dict)
    observability: dict[str, Any] = field(default_factory=dict)
    approval: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    logs: list[Any] = field(default_factory=list)
    events: list[Any] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, state: ExecutionState) -> None:
        self.state = state

    def start(self) -> None:
        self.started_at = datetime.now(timezone.utc)

    def complete(self) -> None:
        self.completed_at = datetime.now(timezone.utc)
