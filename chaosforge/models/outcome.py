"""Canonical experiment outcome helpers."""

from enum import Enum


class ExperimentOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    SUCCESS_WITH_WARNINGS = "SUCCESS_WITH_WARNINGS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


def is_success(status: str | ExperimentOutcome | None) -> bool:
    return status in {
        ExperimentOutcome.SUCCESS,
        ExperimentOutcome.SUCCESS_WITH_WARNINGS,
    }


def is_warning_success(status: str | ExperimentOutcome | None) -> bool:
    return status == ExperimentOutcome.SUCCESS_WITH_WARNINGS


def is_failure(status: str | ExperimentOutcome | None) -> bool:
    return status == ExperimentOutcome.FAILED
