from chaosforge.common.paths import ChaosForgePaths
from chaosforge.models import Campaign, Experiment
from chaosforge.storage.campaigns import CampaignStore


def test_campaign_store_round_trip_preserves_execution_fields(tmp_path):
    store = CampaignStore(ChaosForgePaths(tmp_path))
    campaign = Campaign(name="mixed", continue_on_failure=True, cloud_provider="aws")
    campaign.experiments.append(
        Experiment(
            id="chaos-mesh-pod-kill",
            service="chaos_mesh",
            name="Pod Kill",
            json_file="definition.json",
            variables={"eks_cluster": "cluster-a"},
            engine="Chaos Mesh",
            target_service="eks",
        )
    )

    path = store.save(campaign)
    loaded = store.load("mixed")

    assert path == tmp_path / "runtime" / "campaigns" / "mixed.campaign.json"
    assert loaded.name == "mixed"
    assert loaded.continue_on_failure is True
    assert loaded.experiments[0].engine == "Chaos Mesh"
    assert loaded.experiments[0].target_service == "eks"


def test_campaign_store_rejects_path_traversal(tmp_path):
    store = CampaignStore(ChaosForgePaths(tmp_path))

    try:
        store.load("../outside")
    except ValueError as exc:
        assert "Invalid campaign name" in str(exc)
    else:
        raise AssertionError("Campaign traversal path was accepted")
