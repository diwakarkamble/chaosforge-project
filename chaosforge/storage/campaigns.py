"""Canonical campaign persistence with anchored runtime paths."""

import json
from pathlib import Path

from chaosforge.common.paths import ChaosForgePaths, repository_paths
from chaosforge.models import Campaign, Experiment


class CampaignStore:
    """Persist campaign models without relying on the current working directory."""

    def __init__(self, paths: ChaosForgePaths | None = None):
        self.paths = paths or repository_paths()

    def _path(self, name: str) -> Path:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"Invalid campaign name: {name}")
        return self.paths.campaigns / f"{name}.campaign.json"

    def save(self, campaign: Campaign, name: str | None = None) -> Path:
        campaign_name = name or campaign.name
        path = self._path(campaign_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "name": campaign_name,
            "continue_on_failure": campaign.continue_on_failure,
            "irreversible_operations_acknowledged": campaign.irreversible_operations_acknowledged,
            "cloud_provider": campaign.cloud_provider,
            "experiments": [
                {
                    "id": experiment.id,
                    "service": experiment.service,
                    "name": experiment.name,
                    "json_file": experiment.json_file,
                    "variables": experiment.variables,
                    "engine": experiment.engine,
                    "target_service": experiment.target_service,
                    "reversibility": experiment.reversibility,
                }
                for experiment in campaign.experiments
            ],
        }
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        return path

    def load(self, name: str) -> Campaign:
        path = self._path(name)
        data = json.loads(path.read_text(encoding="utf-8"))
        campaign = Campaign(
            name=data.get("name", name),
            continue_on_failure=data.get("continue_on_failure", False),
            irreversible_operations_acknowledged=data.get(
                "irreversible_operations_acknowledged", False
            ),
            cloud_provider=data.get("cloud_provider", "aws"),
        )
        for item in data.get("experiments", []):
            campaign.experiments.append(
                Experiment(
                    id=item["id"],
                    service=item["service"],
                    name=item["name"],
                    json_file=item["json_file"],
                    variables=item["variables"],
                    engine=item.get("engine", "Chaos Toolkit"),
                    target_service=item.get("target_service", ""),
                    reversibility=item.get("reversibility", "reversible"),
                )
            )
        return campaign

    def list(self) -> list[dict]:
        if not self.paths.campaigns.is_dir():
            return []
        result = []
        for path in self.paths.campaigns.glob("*.campaign.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append(
                {
                    "name": data.get("name", path.stem.removesuffix(".campaign")),
                    "experiments": len(data.get("experiments", [])),
                    "modified": path.stat().st_mtime,
                }
            )
        return sorted(result, key=lambda item: item["modified"], reverse=True)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if path.exists():
            path.unlink()
