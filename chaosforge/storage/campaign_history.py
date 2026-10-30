"""Durable cloud-scoped draft campaigns and immutable execution history."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from chaosforge.common.paths import ChaosForgePaths, repository_paths
from chaosforge.common.version import chaosforge_version
from chaosforge.models import Campaign, Experiment


class CampaignHistoryStore:
    """Store named campaign drafts and their execution snapshots locally."""

    def __init__(self, paths: ChaosForgePaths | None = None):
        self.paths = paths or repository_paths()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _cloud(cloud):
        if cloud not in {"aws", "azure"}:
            raise ValueError(f"Unsupported cloud: {cloud}")
        return cloud

    def _draft_path(self, cloud, campaign_id):
        if not campaign_id or Path(campaign_id).name != campaign_id:
            raise ValueError("Invalid campaign ID")
        return self.paths.campaigns / self._cloud(cloud) / f"{campaign_id}.json"

    def _execution_path(self, execution_id):
        if not execution_id or Path(execution_id).name != execution_id:
            raise ValueError("Invalid execution ID")
        return self.paths.executions / f"{execution_id}.json"

    def _active_draft_path(self, cloud):
        return self.paths.campaigns / self._cloud(cloud) / ".active.json"

    @staticmethod
    def _write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _experiment_data(experiment):
        return {
            "id": getattr(experiment, "id", ""),
            "service": getattr(experiment, "service", ""),
            "name": getattr(experiment, "name", ""),
            "json_file": getattr(experiment, "json_file", ""),
            "variables": getattr(experiment, "variables", {}),
            "engine": getattr(experiment, "engine", "Chaos Toolkit"),
            "target_service": getattr(experiment, "target_service", ""),
            "status": getattr(experiment, "status", "Pending"),
            "warnings": getattr(experiment, "warnings", []),
            "reversibility": getattr(experiment, "reversibility", "reversible"),
            "error_message": getattr(experiment, "error_message", ""),
            "cli_output": getattr(experiment, "cli_output", ""),
        }

    @classmethod
    def _campaign_data(cls, campaign):
        cls._validate_experiments(campaign)
        return {
            "schema_version": 1,
            "id": getattr(campaign, "campaign_id", None),
            "name": getattr(campaign, "name", "YAML Campaign"),
            "cloud": getattr(campaign, "cloud_provider", "aws"),
            "created_at": getattr(campaign, "created_at", None),
            "updated_at": getattr(campaign, "updated_at", None),
            "history_reset_at": getattr(campaign, "history_reset_at", None),
            "chaos_mesh_version_decisions": getattr(
                campaign, "chaos_mesh_version_decisions", {}
            ),
            "continue_on_failure": getattr(campaign, "continue_on_failure", False),
            "irreversible_operations_acknowledged": getattr(
                campaign, "irreversible_operations_acknowledged", False
            ),
            "report_timezone": getattr(campaign, "report_timezone", None),
            "experiments": [cls._experiment_data(experiment) for experiment in getattr(campaign, "experiments", [])],
        }

    @staticmethod
    def _campaign(data):
        campaign = Campaign(
            name=data["name"],
            continue_on_failure=data.get("continue_on_failure", False),
            irreversible_operations_acknowledged=data.get(
                "irreversible_operations_acknowledged", False
            ),
            cloud_provider=data["cloud"],
            report_timezone=data.get("report_timezone"),
            campaign_id=data["id"],
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            history_reset_at=data.get("history_reset_at"),
            chaos_mesh_version_decisions=data.get("chaos_mesh_version_decisions", {}),
        )
        for item in data.get("experiments", []):
            experiment = Experiment(
                id=item["id"], service=item["service"], name=item["name"],
                json_file=item["json_file"], variables=item["variables"],
                engine=item.get("engine", "Chaos Toolkit"), target_service=item.get("target_service", ""),
                status=item.get("status", "Pending"), warnings=item.get("warnings", []),
                reversibility=item.get("reversibility", "reversible"),
            )
            if item.get("error_message"):
                experiment.error_message = item["error_message"]
            if item.get("cli_output"):
                experiment.cli_output = item["cli_output"]
            campaign.experiments.append(experiment)
        return campaign

    @staticmethod
    def _validate_experiments(campaign):
        invalid = [
            experiment
            for experiment in getattr(campaign, "experiments", [])
            if not str(getattr(experiment, "id", "")).strip()
            or not str(getattr(experiment, "service", "")).strip()
        ]
        if invalid:
            raise ValueError("Campaign contains an invalid experiment without an ID or service.")

    def _name_exists(self, cloud, name, except_id=None):
        normalized = name.casefold()
        return any(
            item["name"].casefold() == normalized and item["id"] != except_id
            for item in self.list_drafts(cloud)
        )

    def create_draft(self, cloud, name):
        cloud = self._cloud(cloud)
        name = str(name).strip()
        if not name:
            raise ValueError("Campaign name is required")
        if self._name_exists(cloud, name):
            raise ValueError(f"A {cloud.upper()} campaign named '{name}' already exists")
        now = self._now()
        campaign = Campaign(
            name=name, cloud_provider=cloud, campaign_id=f"campaign-{uuid.uuid4()}",
            created_at=now, updated_at=now,
        )
        self.save_draft(campaign)
        return campaign

    def save_draft(self, campaign):
        cloud = self._cloud(campaign.cloud_provider)
        if not campaign.campaign_id:
            raise ValueError("Campaign draft has no ID")
        if self._name_exists(cloud, campaign.name, campaign.campaign_id):
            raise ValueError(f"A {cloud.upper()} campaign named '{campaign.name}' already exists")
        campaign.created_at = campaign.created_at or self._now()
        campaign.updated_at = self._now()
        self._write(self._draft_path(cloud, campaign.campaign_id), self._campaign_data(campaign))
        return campaign

    def load_draft(self, cloud, campaign_id):
        return self._campaign(json.loads(self._draft_path(cloud, campaign_id).read_text(encoding="utf-8")))

    def list_drafts(self, cloud):
        directory = self.paths.campaigns / self._cloud(cloud)
        if not directory.is_dir():
            return []
        drafts = []
        for path in directory.glob("campaign-*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if any(not item.get("id") or not item.get("service") for item in data.get("experiments", [])):
                continue
            drafts.append({
                "id": data["id"], "name": data["name"], "cloud": data["cloud"],
                "created_at": data.get("created_at"), "updated_at": data.get("updated_at"),
                "experiments": len(data.get("experiments", [])),
            })
        return sorted(drafts, key=lambda item: item.get("updated_at") or "", reverse=True)

    def delete_draft(self, cloud, campaign_id):
        path = self._draft_path(cloud, campaign_id)
        if path.exists():
            path.unlink()
        if self.active_draft_id(cloud) == campaign_id:
            self.clear_active_draft(cloud)

    def set_active_draft(self, cloud, campaign_id):
        self._write(self._active_draft_path(cloud), {"campaign_id": campaign_id})

    def active_draft_id(self, cloud):
        path = self._active_draft_path(cloud)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("campaign_id")

    def clear_active_draft(self, cloud):
        path = self._active_draft_path(cloud)
        if path.exists():
            path.unlink()

    def start_execution(self, campaign, source):
        if source not in {"web", "interactive-cli", "yaml-cli"}:
            raise ValueError(f"Unsupported execution source: {source}")
        now = self._now()
        execution_id = f"execution-{uuid.uuid4()}"
        record = {
            "schema_version": 1, "id": execution_id, "campaign_id": getattr(campaign, "campaign_id", None),
            "campaign_name": getattr(campaign, "name", "YAML Campaign"),
            "cloud": self._cloud(getattr(campaign, "cloud_provider", "aws")),
            "source": source, "status": "RUNNING", "created_at": now, "started_at": now,
            "chaosforge_version": chaosforge_version(),
            "completed_at": None, "logs": [], "report_path": None,
            "campaign_snapshot": self._campaign_data(campaign), "experiments": [],
        }
        self._write(self._execution_path(execution_id), record)
        return execution_id

    def finish_execution(self, execution_id, campaign, status, logs=None, report_path=None):
        path = self._execution_path(execution_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update({
            "status": status, "completed_at": self._now(), "logs": list(logs or []),
            "report_path": str(report_path) if report_path else None,
            "experiments": [self._experiment_data(experiment) for experiment in getattr(campaign, "experiments", [])],
        })
        self._write(path, record)
        return record

    def list_executions(self, cloud, campaign_id=None):
        if not self.paths.executions.is_dir():
            return []
        records = []
        for path in self.paths.executions.glob("execution-*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("cloud") == self._cloud(cloud) and (
                campaign_id is None or record.get("campaign_id") == campaign_id
            ):
                records.append(record)
        return sorted(records, key=lambda item: item.get("started_at") or "", reverse=True)

    def load_execution(self, execution_id):
        return json.loads(self._execution_path(execution_id).read_text(encoding="utf-8"))
