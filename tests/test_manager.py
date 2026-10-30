import pytest

from chaosforge.application.campaigns import manager
from chaosforge.application.campaigns.duplicates import duplicate_experiment_indexes
from chaosforge.common.paths import ChaosForgePaths
from chaosforge.models import Campaign, Experiment
from chaosforge.storage.campaign_history import CampaignHistoryStore


@pytest.fixture(autouse=True)
def isolated_campaign_state(monkeypatch, tmp_path):
    campaign = Campaign()
    monkeypatch.setattr(manager, "campaign", campaign)
    monkeypatch.setattr(manager, "campaigns", {"aws": campaign})
    monkeypatch.setattr(
        manager, "history_store", CampaignHistoryStore(ChaosForgePaths(tmp_path))
    )


def setup_function():

    #
    # Start every test with an empty campaign
    #

    manager.clear()


def test_add_experiment():

    experiment = {"name": "Lambda Timeout"}

    manager.add(experiment)

    experiments = manager.list_all()

    assert len(experiments) == 1

    assert experiments[0]["name"] == "Lambda Timeout"


def test_add_rejects_an_identical_experiment_configuration():
    experiment = Experiment(
        "azure-redis-reboot",
        "azure_redis",
        "Reboot Redis",
        "reboot.json",
        {
            "subscription_id": "sub",
            "resource_group": "rg",
            "redis_name": "cache",
            "reboot_type": "AllNodes",
        },
        engine="Azure Chaos Studio",
        target_service="azure_redis",
    )
    manager.add(experiment, "azure")

    with pytest.raises(ValueError, match="identical experiment configuration"):
        manager.add(experiment, "azure")

    assert manager.list_all("azure") == [experiment]


def test_add_allows_the_same_experiment_for_a_different_target_or_inputs():
    first = Experiment("reboot", "azure_redis", "Reboot Redis", "reboot.json", {"redis_name": "cache-a"})
    second = Experiment("reboot", "azure_redis", "Reboot Redis", "reboot.json", {"redis_name": "cache-b"})

    manager.add(first, "azure")
    manager.add(second, "azure")

    assert manager.list_all("azure") == [first, second]


def test_duplicate_detection_ignores_legacy_entries_without_identity():
    assert duplicate_experiment_indexes([{"name": "Legacy"}, {"name": "Legacy"}]) == []


def test_remove_experiment():

    manager.add({"name": "One"})

    manager.add({"name": "Two"})

    manager.remove(0)

    experiments = manager.list_all()

    assert len(experiments) == 1

    assert experiments[0]["name"] == "Two"


def test_remove_invalid_index():

    manager.add({"name": "One"})

    manager.remove(10)

    experiments = manager.list_all()

    assert len(experiments) == 1


def test_clear_campaign():

    manager.add({"name": "One"})

    manager.add({"name": "Two"})

    manager.clear()

    assert manager.list_all() == []


def test_get_campaign():

    campaign = manager.get_campaign()

    assert campaign is manager.campaign


def test_get_valid_index():

    experiment = {"name": "Lambda Timeout"}

    manager.add(experiment)

    result = manager.get(0)

    assert result == experiment


def test_get_invalid_index():

    manager.add({"name": "Lambda Timeout"})

    assert manager.get(10) is None


def test_get_negative_index():

    manager.add({"name": "Lambda Timeout"})

    assert manager.get(-1) is None


def test_update_valid_index():

    original = {"name": "Lambda Timeout"}
    updated = {"name": "Lambda Memory"}

    manager.add(original)

    manager.update(0, updated)

    assert manager.get(0) == updated


def test_update_invalid_index():

    original = {"name": "Lambda Timeout"}

    manager.add(original)

    manager.update(10, {"name": "Should Not Exist"})

    assert manager.get(0) == original


def test_update_negative_index():

    original = {"name": "Lambda Timeout"}

    manager.add(original)

    manager.update(-1, {"name": "Should Not Exist"})

    assert manager.get(0) == original


def test_get_selected():

    first = {"name": "Lambda Timeout"}
    second = {"name": "Lambda Memory"}
    third = {"name": "Lambda CPU"}

    manager.add(first)
    manager.add(second)
    manager.add(third)

    result = manager.get_selected([0, 2])

    assert result == [first, third]


def test_get_selected_ignores_invalid_indexes():

    first = {"name": "Lambda Timeout"}
    second = {"name": "Lambda Memory"}

    manager.add(first)
    manager.add(second)

    result = manager.get_selected([-1, 0, 99, 1])

    assert result == [first, second]


def test_remove_negative_index():

    manager.add({"name": "Lambda Timeout"})

    manager.remove(-1)

    assert manager.list_all() == [{"name": "Lambda Timeout"}]
