from pathlib import Path

import pytest

from chaosforge.application.services.campaign_yaml import CampaignYAMLService

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "campaigns"


@pytest.mark.parametrize(
    "example_path",
    sorted(EXAMPLES_DIR.glob("*.yaml")),
    ids=lambda path: path.name,
)
def test_campaign_example_is_valid_portable_yaml(example_path):
    review = CampaignYAMLService().inspect_bytes(example_path.read_bytes())

    assert review.valid, review.errors
    assert review.campaign.cloud_provider == "aws"
    assert review.campaign.experiments
    assert review.is_template is True


def test_multi_experiment_example_preserves_order():
    review = CampaignYAMLService().inspect_bytes(
        (EXAMPLES_DIR / "lambda-resilience.yaml").read_bytes()
    )

    assert [experiment.id for experiment in review.campaign.experiments] == [
        "lambda-memory",
        "lambda-timeout",
    ]
