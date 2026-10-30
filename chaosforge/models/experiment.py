"""Experiment model."""

from dataclasses import dataclass, field


@dataclass
class Experiment:
    """A catalog experiment plus its resolved runtime variables."""

    id: str
    service: str
    name: str
    json_file: str
    variables: dict
    engine: str = "Chaos Toolkit"
    target_service: str = ""
    status: str = "Pending"
    warnings: list[dict] = field(default_factory=list)
    reversibility: str = "reversible"
