"""Read-only execution plan model."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PlanResult:
    """Normalized read-only execution plan."""

    executable: bool = True
    experiments: list[dict[str, Any]] = field(default_factory=list)
    targets: list[dict[str, Any]] = field(default_factory=list)
    impact: dict[str, Any] = field(
        default_factory=lambda: {
            "capacity": {},
            "dependencies": [],
            "availability_zones": [],
            "traffic": {
                "status": "UNKNOWN",
                "reason": "No traffic telemetry configured.",
            },
            "customer_impact": {
                "status": "UNKNOWN",
                "reason": "No customer-impact telemetry configured.",
            },
        }
    )
    permissions: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)
    duration: dict[str, Any] = field(
        default_factory=lambda: {
            "estimated_seconds": None,
            "status": "UNKNOWN",
        }
    )
    recovery: dict[str, Any] = field(
        default_factory=lambda: {
            "behavior": "UNKNOWN",
            "details": [],
        }
    )
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def finalize(self) -> "PlanResult":
        self.executable = not bool(self.blockers)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
