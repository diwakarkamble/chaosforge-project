"""Centralized paths for source resources and generated runtime artifacts."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChaosForgePaths:
    """Filesystem roots used by the application.

    Built-in definitions live within the ``chaosforge`` package. Generated
    artifacts are isolated under ``runtime`` so callers do not depend on the
    current working directory.
    """

    root: Path

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def campaigns(self) -> Path:
        return self.runtime / "campaigns"

    @property
    def executions(self) -> Path:
        return self.runtime / "executions"

    @property
    def evidence(self) -> Path:
        return self.runtime / "evidence"

    @property
    def reports(self) -> Path:
        return self.runtime / "reports"

    @property
    def logs(self) -> Path:
        return self.runtime / "logs"

    @property
    def rollback(self) -> Path:
        return self.runtime / "rollback"

    @property
    def settings(self) -> Path:
        return self.runtime / "settings.json"

    def ensure_runtime_directories(self) -> None:
        """Create generated-artifact directories only when explicitly asked."""
        for directory in (
            self.campaigns,
            self.executions,
            self.evidence,
            self.reports,
            self.logs,
            self.rollback,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def repository_paths() -> ChaosForgePaths:
    """Return paths rooted at the repository containing this package."""
    return ChaosForgePaths(Path(__file__).resolve().parents[2])
