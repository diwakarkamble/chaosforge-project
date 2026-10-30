import json

from chaosforge.catalog import ExperimentCatalog


def test_catalog_loads_canonical_lambda_metadata():
    catalog = ExperimentCatalog()

    experiment = catalog.get_experiment("lambda", "lambda-memory")

    assert experiment is not None
    assert experiment["json"] == "lambda-memory-chaos.json"
    assert catalog.definition_path("lambda", "lambda-memory-chaos.json").is_file()


def test_catalog_returns_none_for_unknown_service_or_experiment():
    catalog = ExperimentCatalog()

    assert catalog.load_service("unknown") is None
    assert catalog.get_experiment("unknown", "experiment") is None


def test_every_catalog_experiment_references_valid_json_definition():
    catalog = ExperimentCatalog()

    for service in catalog.list_services():
        if service == "chaos_mesh":
            continue
        metadata = catalog.load_service(service)
        for experiment in metadata["experiments"]:
            if service == "fis":
                assert "json" not in experiment
                continue
            definition = catalog.definition_path(service, experiment["json"])
            assert definition.is_file(), f"{service}/{experiment['id']}"
            assert json.loads(definition.read_text(encoding="utf-8")), (
                f"{service}/{experiment['id']}"
            )
