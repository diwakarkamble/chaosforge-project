from unittest.mock import patch

from chaosforge.application.campaigns.builder import build_experiment
from chaosforge.catalog import ExperimentCatalog


@patch("chaosforge.application.campaigns.builder.add")
@patch("chaosforge.application.campaigns.builder.context")
def test_build_lambda_experiment(mock_context, mock_add):

    mock_context.region = "eu-central-1"

    metadata = {
        "id": "lambda-memory",
        "name": "Lambda Memory",
        "json": "lambda-memory.json",
    }

    experiment = build_experiment("lambda", metadata)

    assert experiment.service == "lambda"
    assert experiment.engine == "Chaos Toolkit"
    assert experiment.variables["aws_region"] == "eu-central-1"

    mock_add.assert_called_once_with(experiment)


@patch("chaosforge.application.campaigns.builder.add")
@patch("chaosforge.application.campaigns.builder.context")
def test_build_fis_experiment(mock_context, mock_add):

    mock_context.region = "us-east-1"

    metadata = {"id": "fis-delay", "name": "Delay", "json": "delay.json"}

    experiment = build_experiment("fis", metadata)

    assert experiment.engine == "AWS FIS"
    assert experiment.variables["aws_region"] == "us-east-1"


@patch("chaosforge.application.campaigns.builder.add")
@patch("chaosforge.application.campaigns.builder.context")
def test_existing_region_not_overwritten(mock_context, mock_add):

    mock_context.region = "eu-central-1"

    metadata = {"id": "id", "name": "name", "json": "test.json"}

    variables = {"aws_region": "ap-south-1"}

    experiment = build_experiment("lambda", metadata, variables)

    assert experiment.variables["aws_region"] == "ap-south-1"


@patch("chaosforge.application.campaigns.builder.add")
@patch("chaosforge.application.campaigns.builder.context")
def test_variables_none(mock_context, mock_add):

    mock_context.region = "eu-west-1"

    metadata = {"id": "id", "name": "name", "json": "test.json"}

    experiment = build_experiment("lambda", metadata, None)

    assert experiment.variables == {"aws_region": "eu-west-1", "region": "eu-west-1"}


def test_factory_materializes_omitted_configuration_defaults():
    metadata = {
        "id": "memory",
        "name": "Memory",
        "json": "test.json",
        "inputs": [
            {"name": "target_memory_size", "type": "integer", "default": 512},
            {"name": "wait_seconds", "type": "integer", "default": 300},
        ],
    }

    experiment = build_experiment("lambda", metadata, {})

    assert experiment.variables["target_memory_size"] == 512
    assert experiment.variables["wait_seconds"] == "PT300S"


@patch("chaosforge.application.campaigns.builder.add")
@patch("chaosforge.application.campaigns.builder.context")
def test_json_path(mock_context, mock_add):

    mock_context.region = "eu-central-1"

    metadata = {"id": "abc", "name": "ABC", "json": "memory.json"}

    experiment = build_experiment("lambda", metadata)

    assert experiment.json_file == str(
        ExperimentCatalog().definition_path("lambda", "memory.json")
    )
