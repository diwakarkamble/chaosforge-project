"""Campaign model."""

from dataclasses import dataclass, field


@dataclass
class Campaign:
    """An ordered collection of controlled chaos experiments."""

    name: str = "Default Campaign"
    experiments: list = field(default_factory=list)
    continue_on_failure: bool = False
    irreversible_operations_acknowledged: bool = False
    cloud_provider: str = "aws"
    report_timezone: str | None = None
    campaign_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    history_reset_at: str | None = None
    chaos_mesh_version_decisions: dict = field(default_factory=dict)
