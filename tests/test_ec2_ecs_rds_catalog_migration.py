import importlib
import inspect
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("service", ["ec2", "ecs", "rds"])
def test_migrated_definitions_and_providers(service):
    experiments_path = (
        Path(__file__).parents[1]
        / "chaosforge"
        / "providers"
        / "aws"
        / "components"
        / service
        / "experiments"
    )
    metadata = json.loads(
        (experiments_path / "metadata.json").read_text(encoding="utf-8")
    )

    for experiment in metadata["experiments"]:
        definition_path = (
            experiments_path / "toolkit" / "definitions" / experiment["json"]
        )

        if service == "rds" and experiment["id"] == "rds-reboot":
            assert not definition_path.exists()
            continue

        assert definition_path.is_file()
        definition = json.loads(definition_path.read_text(encoding="utf-8"))
        if service == "rds" and experiment["id"] == "rds-iops":
            assert definition["rollbacks"][0]["provider"]["func"] == "rollback_iops"
            threshold = next(field for field in experiment["inputs"] if field["name"] == "threshold_percent")
            assert threshold["label"] == "Target IOPS (% of current, decrease only)"
            assert "minimum of 1000" in threshold["hint"]
        if service == "rds" and experiment["id"] == "rds-instance-class":
            target = next(field for field in experiment["inputs"] if field["name"] == "target_instance_class")
            assert target["type"] == "aws_resource"
            assert target["resource_type"] == "rds-instance-class"
            assert target["parent"] == "db_instance_identifier"
        if service == "vpc":
            waits = [item for item in definition.get("method", []) if item["name"] == "Wait"]
            for wait in waits:
                assert wait["provider"] == {
                    "type": "python",
                    "module": "chaosforge.providers.aws.common_actions",
                    "func": "wait_for_duration",
                    "arguments": {"wait_seconds": "${wait_seconds}"},
                }
        if service == "rds":
            assert "${region}" not in definition_path.read_text(encoding="utf-8")
        activities = definition.get("method", []) + definition.get("rollbacks", [])

        for activity in activities:
            provider = activity.get("provider", {})
            if provider.get("type") != "python":
                continue

            module = importlib.import_module(provider["module"])
            assert hasattr(module, provider["func"])
            assert set(provider.get("arguments", {})) <= set(
                inspect.signature(getattr(module, provider["func"])).parameters
            )
            assert provider["module"].startswith(
                f"chaosforge.providers.aws.components.{service}."
            )
