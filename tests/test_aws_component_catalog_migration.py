import importlib
import json

import pytest

from chaosforge.catalog import ExperimentCatalog


def _python_providers(activity):
    provider = activity.get("provider", {})
    if provider.get("type") == "python":
        yield provider


@pytest.mark.parametrize(
    ("service", "component", "experiment_count"),
    [
        ("apigateway", "apigateway", 6),
        ("elb", "elb", 7),
        ("elasticache", "elasticache", 5),
    ],
)
def test_component_catalog_uses_migrated_definitions_and_providers(
    service, component, experiment_count
):
    catalog = ExperimentCatalog()
    metadata = catalog.load_service(service)

    assert metadata is not None
    assert len(metadata["experiments"]) == experiment_count

    component_prefix = f"chaosforge.providers.aws.components.{component}."
    for experiment in metadata["experiments"]:
        definition_path = catalog.definition_path(service, experiment["json"])
        assert definition_path.is_file()

        definition = json.loads(definition_path.read_text(encoding="utf-8"))
        activities = definition.get("method", []) + definition.get("rollbacks", [])

        for activity in activities:
            for provider in _python_providers(activity):
                module = importlib.import_module(provider["module"])
                assert hasattr(module, provider["func"])
                if provider["module"] != "chaosforge.providers.aws.common_actions":
                    assert provider["module"].startswith(component_prefix)


def test_ecs_catalog_includes_runtime_discovery_permissions():
    metadata = ExperimentCatalog().load_service("ecs")

    for experiment in metadata["experiments"]:
        assert {"ecs:ListClusters", "ecs:ListServices"}.issubset(experiment["iam"]["read"])

    cpu = next(item for item in metadata["experiments"] if item["id"] == "ecs-cpu-modification")
    memory = next(item for item in metadata["experiments"] if item["id"] == "ecs-memory-modification")
    assert cpu["iam"]["additional"] == ["iam:PassRole"]
    assert memory["iam"]["additional"] == ["iam:PassRole"]
