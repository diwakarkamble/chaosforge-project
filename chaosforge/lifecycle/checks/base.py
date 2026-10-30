from abc import ABC, abstractmethod
from typing import Any


class ExperimentCheck(ABC):
    """
    Base interface for experiment prechecks and postchecks.

    A check can capture the initial state before fault injection
    and validate the resulting state after fault injection or recovery.
    """

    name: str = "unnamed-check"

    @abstractmethod
    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        """
        Capture the current state of the target.

        This is used for the baseline/precheck phase.
        """
        raise NotImplementedError

    @abstractmethod
    def validate(
        self,
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Validate the target against the captured baseline.

        The returned dictionary should contain structured,
        machine-readable validation information.
        """
        raise NotImplementedError
