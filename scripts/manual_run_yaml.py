"""Manually execute a YAML campaign only in an approved test environment."""

from chaosforge.application.campaigns.yaml_builder import build_campaign
from chaosforge.application.campaigns.yaml_loader import load_yaml
from chaosforge.engines.chaos_toolkit.runner import ExperimentRunner

if __name__ == "__main__":
    data = load_yaml("examples/campaigns/lambda-memory.yaml")
    campaign = build_campaign(data)
    ExperimentRunner().execute_campaign(campaign)
