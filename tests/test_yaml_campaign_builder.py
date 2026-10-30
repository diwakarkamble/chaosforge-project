import json
from unittest.mock import mock_open, patch

import pytest

from chaosforge.application.campaigns.yaml_builder import build_campaign
from chaosforge.catalog import ExperimentCatalog


def test_build_campaign():
    data = {
        "campaign": {
            "name": "Test Campaign",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-timeout",
                "variables": {
                    "lambda_name": "test-function",
                    "target_timeout": 3,
                },
            }
        ],
    }

    metadata = {
        "display_name": "AWS Lambda",
        "experiments": [
            {
                "id": "lambda-timeout",
                "name": "Lambda Timeout",
                "json": "lambda-timeout-chaos.json",
            }
        ],
    }

    with patch(
        "builtins.open",
        mock_open(read_data=json.dumps(metadata)),
    ):
        campaign = build_campaign(data)

    assert campaign.name == "Test Campaign"
    assert len(campaign.experiments) == 1

    experiment = campaign.experiments[0]

    assert experiment.id == "lambda-timeout"
    assert experiment.service == "lambda"
    assert experiment.name == "Lambda Timeout"
    assert experiment.json_file == str(
        ExperimentCatalog().definition_path(
            "lambda", "lambda-timeout-chaos.json"
        )
    )
    assert experiment.variables == {
        "lambda_name": "test-function",
        "target_timeout": 3,
    }


def test_build_campaign_multiple_experiments():
    data = {
        "campaign": {
            "name": "Multi Experiment Campaign",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-timeout",
                "variables": {
                    "lambda_name": "function-a",
                },
            },
            {
                "service": "lambda",
                "experiment": "lambda-memory",
                "variables": {
                    "lambda_name": "function-b",
                },
            },
        ],
    }

    metadata = {
        "display_name": "AWS Lambda",
        "experiments": [
            {
                "id": "lambda-timeout",
                "name": "Lambda Timeout",
                "json": "lambda-timeout-chaos.json",
            },
            {
                "id": "lambda-memory",
                "name": "Lambda Memory",
                "json": "lambda-memory-chaos.json",
            },
        ],
    }

    with patch(
        "builtins.open",
        mock_open(read_data=json.dumps(metadata)),
    ):
        campaign = build_campaign(data)

    assert campaign.name == "Multi Experiment Campaign"
    assert len(campaign.experiments) == 2

    assert campaign.experiments[0].id == "lambda-timeout"
    assert campaign.experiments[1].id == "lambda-memory"


def test_build_campaign_experiment_not_found():
    data = {
        "campaign": {
            "name": "Invalid Campaign",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "does-not-exist",
                "variables": {},
            }
        ],
    }

    metadata = {
        "display_name": "AWS Lambda",
        "experiments": [
            {
                "id": "lambda-timeout",
                "name": "Lambda Timeout",
                "json": "lambda-timeout-chaos.json",
            }
        ],
    }

    with (
        patch(
            "builtins.open",
            mock_open(read_data=json.dumps(metadata)),
        ),
        pytest.raises(
            LookupError,
            match="Experiment 'does-not-exist' not found",
        ),
    ):
        build_campaign(data)

def test_build_campaign_reads_campaign_execution_settings():
    data = {
        "campaign": {
            "name": "AWS Chaos Campaign",
            "continue_on_failure": True,
        },
        "cloud": {
            "provider": "aws",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-timeout",
                "variables": {
                    "lambda_name": "test-function",
                },
            }
        ],
    }

    metadata = {
        "display_name": "AWS Lambda",
        "experiments": [
            {
                "id": "lambda-timeout",
                "name": "Lambda Timeout",
                "json": "lambda-timeout-chaos.json",
            }
        ],
    }

    with patch(
        "builtins.open",
        mock_open(read_data=json.dumps(metadata)),
    ):
        campaign = build_campaign(data)

    assert campaign.name == "AWS Chaos Campaign"
    assert campaign.continue_on_failure is True
    assert campaign.cloud_provider == "aws"

def test_build_campaign_uses_execution_setting_defaults():
    data = {
        "campaign": {
            "name": "Default Settings Campaign",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-timeout",
                "variables": {
                    "lambda_name": "test-function",
                },
            }
        ],
    }

    metadata = {
        "display_name": "AWS Lambda",
        "experiments": [
            {
                "id": "lambda-timeout",
                "name": "Lambda Timeout",
                "json": "lambda-timeout-chaos.json",
            }
        ],
    }

    with patch(
        "builtins.open",
        mock_open(read_data=json.dumps(metadata)),
    ):
        campaign = build_campaign(data)

    assert campaign.continue_on_failure is False
    assert campaign.cloud_provider == "aws"

def test_build_campaign_loads_chaos_mesh_experiment():
    from chaosforge.application.campaigns.yaml_builder import build_campaign

    data = {
        "campaign": {
            "name": "chaos-mesh-test",
        },
        "cloud": {
            "provider": "aws",
        },
        "experiments": [
            {
                "service": "chaos_mesh",
                "experiment": "chaos-mesh-pod-kill",
                "variables": {
                    "aws_region": "eu-central-1",
                    "eks_cluster": "cluster-1",
                    "namespace": "payments",
                    "pod": "payments-api-abc",
                },
            }
        ],
    }

    campaign = build_campaign(data)

    assert campaign.name == "chaos-mesh-test"
    assert len(campaign.experiments) == 1

    experiment = campaign.experiments[0]

    assert experiment.id == "chaos-mesh-pod-kill"
    assert experiment.service == "chaos_mesh"
    assert experiment.engine == "Chaos Mesh"
    assert experiment.name == "Pod Kill"

    assert experiment.json_file == str(
        ExperimentCatalog().definition_path("chaos_mesh", "pod-kill.json")
    )

    assert experiment.variables["eks_cluster"] == "cluster-1"
    assert experiment.variables["namespace"] == "payments"
    assert experiment.variables["pod"] == "payments-api-abc"
