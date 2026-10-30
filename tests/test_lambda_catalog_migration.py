import importlib
import json

from chaosforge.catalog import ExperimentCatalog


def _python_providers(activity):
    provider = activity.get("provider", {})
    if provider.get("type") == "python":
        yield provider


def test_lambda_catalog_uses_migrated_definitions_and_providers():
    catalog = ExperimentCatalog()
    metadata = catalog.load_service("lambda")

    assert metadata is not None
    assert len(metadata["experiments"]) == 5

    for experiment in metadata["experiments"]:
        definition_path = catalog.definition_path("lambda", experiment["json"])
        assert definition_path.is_file()

        definition = json.loads(definition_path.read_text(encoding="utf-8"))
        activities = definition.get("method", []) + definition.get("rollbacks", [])

        for activity in activities:
            for provider in _python_providers(activity):
                module = importlib.import_module(provider["module"])
                assert hasattr(module, provider["func"])
                assert provider["module"].startswith(
                    "chaosforge.providers.aws.components.lambda."
                )
