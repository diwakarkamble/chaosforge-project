import json
from unittest.mock import mock_open, patch

from chaosforge.application.experiment_descriptions import (
    get_experiment_description,
    load_experiment_descriptions,
)


@patch("chaosforge.application.experiment_descriptions.DESCRIPTION_PATH", "missing.json")
def test_load_experiment_descriptions_missing_file():
    with patch("chaosforge.application.experiment_descriptions.os.path.exists", return_value=False):
        result = load_experiment_descriptions()

    assert result == {}


@patch("chaosforge.application.experiment_descriptions.DESCRIPTION_PATH", "descriptions.json")
def test_load_experiment_descriptions():
    data = {
        "lambda": {
            "timeout": {
                "description": "Increase Lambda timeout",
            }
        }
    }

    mocked_file = mock_open(read_data=json.dumps(data))

    with (
        patch("chaosforge.application.experiment_descriptions.os.path.exists", return_value=True),
        patch("chaosforge.application.experiment_descriptions.open", mocked_file),
    ):
        result = load_experiment_descriptions()

    assert result == data
    mocked_file.assert_called_once_with(
        "descriptions.json",
        "r",
        encoding="utf-8-sig",
    )


@patch("chaosforge.application.experiment_descriptions.load_experiment_descriptions")
def test_get_experiment_description_found(mock_load):
    data = {
        "lambda": {
            "timeout": {
                "description": "Increase Lambda timeout",
                "risk": "low",
            }
        }
    }
    mock_load.return_value = data

    result = get_experiment_description("lambda", "timeout")

    assert result["description"] == "Increase Lambda timeout"
    assert result["impact"]
    assert result["expected_behavior"]
    mock_load.assert_called_once()


@patch("chaosforge.application.experiment_descriptions.ExperimentCatalog")
@patch("chaosforge.application.experiment_descriptions.load_experiment_descriptions")
def test_get_experiment_description_missing_experiment(mock_load, mock_catalog):
    mock_load.return_value = {
        "lambda": {
            "timeout": {
                "description": "Increase Lambda timeout",
            }
        }
    }

    mock_catalog.return_value.get_experiment.return_value = {"name": "Missing Fault"}
    result = get_experiment_description("lambda", "missing")

    assert result["description"] == "Runs the controlled missing fault resilience experiment."
    assert result["impact"]
    assert result["expected_behavior"]


@patch("chaosforge.application.experiment_descriptions.ExperimentCatalog")
@patch("chaosforge.application.experiment_descriptions.load_experiment_descriptions")
def test_get_experiment_description_missing_service(mock_load, mock_catalog):
    mock_load.return_value = {
        "lambda": {
            "timeout": {
                "description": "Increase Lambda timeout",
            }
        }
    }
    mock_catalog.return_value.get_experiment.return_value = None

    result = get_experiment_description("ec2", "stop-instance")

    assert result == {}


@patch("chaosforge.application.experiment_descriptions.load_experiment_descriptions")
def test_get_experiment_description_empty_data(mock_load):
    mock_load.return_value = {}

    with patch(
        "chaosforge.application.experiment_descriptions.ExperimentCatalog"
    ) as catalog:
        catalog.return_value.get_experiment.return_value = None
        result = get_experiment_description("lambda", "timeout")

    assert result == {}
