import pytest

from chaosforge.application.duration import (
    duration_seconds,
    execution_variables,
    iso8601_duration,
    normalize_named_duration_field,
)
from chaosforge.catalog import ExperimentCatalog


@pytest.mark.parametrize(
    ("value", "expected"),
    [("PT100S", 100), ("PT5M", 300), ("PT1H30M", 5400), ("P1D", 86400)],
)
def test_duration_seconds_parses_iso8601_values(value, expected):
    assert duration_seconds(value) == expected


def test_duration_helpers_reject_invalid_and_negative_values():
    with pytest.raises(ValueError, match="ISO 8601"):
        duration_seconds("five minutes")
    with pytest.raises(ValueError, match="negative"):
        iso8601_duration(-1)


def test_execution_variables_converts_only_local_wait_fields():
    values = {
        "wait_seconds": "PT5M",
        "duration_seconds": "PT30S",
        "fault_duration_seconds": "PT1M",
        "duration": "PT15M",
    }

    assert execution_variables(values) == {
        "wait_seconds": 300,
        "duration_seconds": 30,
        "fault_duration_seconds": 60,
        "duration": "PT15M",
    }


def test_iso8601_duration_normalizes_legacy_seconds():
    assert iso8601_duration(300) == "PT300S"
    assert iso8601_duration("PT5M") == "PT5M"


def test_catalog_exposes_all_fault_duration_fields_as_iso8601():
    catalog = ExperimentCatalog()
    duration_names = {"duration", "wait_seconds", "duration_seconds", "fault_duration_seconds"}

    for service in catalog.list_services():
        for experiment in catalog.load_service(service).get("experiments", []):
            for field in experiment.get("inputs", []):
                if field.get("name") in duration_names:
                    assert field["type"] == "iso8601_duration", (
                        service,
                        experiment["id"],
                        field,
                    )


def test_named_duration_normalizes_kubernetes_seconds_syntax():
    metadata = {
        "experiments": [
            {"inputs": [{"name": "duration", "type": "text", "default": "30s"}]}
        ]
    }

    normalize_named_duration_field(metadata)

    assert metadata["experiments"][0]["inputs"][0] == {
        "name": "duration",
        "type": "iso8601_duration",
        "default": "PT30S",
    }
