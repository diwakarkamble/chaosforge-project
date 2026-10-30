from copy import deepcopy
from types import SimpleNamespace

from chaosforge.application.services.campaign_executor import CampaignExecutor


def test_stops_after_first_failure_when_continuation_is_disabled():
    first = SimpleNamespace(name="first", status="FAILED")
    second = SimpleNamespace(name="second", status="Pending")
    campaign = SimpleNamespace(
        experiments=[first, second],
        continue_on_failure=False,
        start_time=None,
        end_time=None,
        duration=None,
    )
    executed = []

    result = CampaignExecutor().execute(
        campaign,
        lambda experiment: executed.append(experiment),
    )

    assert executed == [first]
    assert result.failed == [first]
    assert result.skipped == [second]
    assert result.status == "PARTIAL"
    assert second.status == "SKIPPED"
    assert campaign.start_time is not None
    assert campaign.end_time is not None


def test_continues_after_failure_when_enabled():
    first = SimpleNamespace(name="first", status="FAILED")
    second = SimpleNamespace(name="second", status="SUCCESS")
    campaign = SimpleNamespace(
        experiments=[first, second],
        continue_on_failure=True,
        start_time=None,
        end_time=None,
        duration=None,
    )
    executed = []

    result = CampaignExecutor().execute(
        campaign,
        lambda experiment: executed.append(experiment),
    )

    assert executed == [first, second]
    assert result.failed == [first]
    assert result.skipped == []
    assert result.status == "FAILED"


def test_warning_success_keeps_campaign_successful_without_stopping():
    first = SimpleNamespace(name="first", status="SUCCESS_WITH_WARNINGS", variables={})
    second = SimpleNamespace(name="second", status="SUCCESS", variables={})
    campaign = SimpleNamespace(
        experiments=[first, second],
        continue_on_failure=False,
        start_time=None,
        end_time=None,
        duration=None,
    )

    result = CampaignExecutor().execute(campaign, lambda experiment: None)

    assert result.failed == []
    assert result.warnings == [first]
    assert result.skipped == []
    assert result.status == "SUCCESS_WITH_WARNINGS"


def test_restores_campaign_variables_after_successful_or_failed_engine_mutation():
    variables = {
        "bucket_name": "bucket",
        "aws_region": "eu-central-1",
        "policy_template": "readonly",
        "wait_seconds": 30,
        "nested": {"value": "original"},
    }
    expected_variables = deepcopy(variables)
    experiment = SimpleNamespace(name="policy", status="Pending", variables=variables)
    campaign = SimpleNamespace(
        experiments=[experiment],
        continue_on_failure=True,
        start_time=None,
        end_time=None,
        duration=None,
    )

    def run(current):
        current.variables.clear()
        current.variables["nested"] = {"value": "mutated"}
        current.status = "FAILED"

    CampaignExecutor().execute(campaign, run)

    assert experiment.variables == expected_variables
