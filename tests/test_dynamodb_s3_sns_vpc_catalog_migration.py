import importlib
import json
from pathlib import Path

import pytest

COMPONENTS_ROOT = Path("chaosforge/providers/aws/components")


@pytest.mark.parametrize(
    ("service", "experiment_count"),
    [("dynamodb", 4), ("s3", 5), ("sns", 5), ("vpc", 4)],
)
def test_component_files_and_providers_are_migrated(service, experiment_count):
    experiments = COMPONENTS_ROOT / service / "experiments"
    metadata = json.loads((experiments / "metadata.json").read_text(encoding="utf-8"))

    assert len(metadata["experiments"]) == experiment_count

    for experiment in metadata["experiments"]:
        definition_path = (
            experiments / "toolkit" / "definitions" / experiment["json"]
        )
        assert definition_path.is_file()

        definition_text = definition_path.read_text(encoding="utf-8")
        if not definition_text.strip():
            assert experiment["id"] == "vpc-route-table"
            continue

        definition = json.loads(definition_text)
        activities = definition.get("method", []) + definition.get("rollbacks", [])
        for activity in activities:
            provider = activity.get("provider", {})
            if provider.get("type") != "python":
                continue

            module = importlib.import_module(provider["module"])
            assert hasattr(module, provider["func"])
            if provider["module"] != "chaosforge.providers.aws.common_actions":
                assert provider["module"].startswith(
                    f"chaosforge.providers.aws.components.{service}."
                )
