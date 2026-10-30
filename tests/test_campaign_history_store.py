import json

from chaosforge.common.paths import ChaosForgePaths
from chaosforge.models import Experiment
from chaosforge.storage.campaign_history import CampaignHistoryStore


def _store(tmp_path):
    return CampaignHistoryStore(ChaosForgePaths(tmp_path))


def test_drafts_are_cloud_scoped_unique_and_persist_mutations(tmp_path):
    store = _store(tmp_path)
    aws = store.create_draft("aws", "Recovery")
    azure = store.create_draft("azure", "Recovery")
    aws.experiments.append(Experiment("restart", "lambda", "Restart", "restart.json", {}))
    store.save_draft(aws)

    assert [item["name"] for item in store.list_drafts("aws")] == ["Recovery"]
    assert store.load_draft("aws", aws.campaign_id).experiments[0].name == "Restart"
    assert store.list_drafts("azure")[0]["id"] == azure.campaign_id


def test_draft_round_trips_history_reset_boundary(tmp_path):
    store = _store(tmp_path)
    campaign = store.create_draft("aws", "Reset")
    campaign.history_reset_at = "2026-10-29T12:00:00+00:00"
    store.save_draft(campaign)

    assert store.load_draft("aws", campaign.campaign_id).history_reset_at == (
        "2026-10-29T12:00:00+00:00"
    )


def test_draft_round_trips_local_chaos_mesh_version_decisions(tmp_path):
    store = _store(tmp_path)
    campaign = store.create_draft("aws", "Versions")
    campaign.chaos_mesh_version_decisions = {
        "eu-central-1:cluster": {
            "action": "continue",
            "installed_version": "2.8.4",
            "target_version": "2.8.7",
        }
    }
    store.save_draft(campaign)

    assert store.load_draft(
        "aws", campaign.campaign_id
    ).chaos_mesh_version_decisions == campaign.chaos_mesh_version_decisions


def test_active_draft_id_is_persisted_per_cloud(tmp_path):
    store = _store(tmp_path)
    aws = store.create_draft("aws", "AWS")
    azure = store.create_draft("azure", "Azure")
    store.set_active_draft("aws", aws.campaign_id)
    store.set_active_draft("azure", azure.campaign_id)

    assert store.active_draft_id("aws") == aws.campaign_id
    assert store.active_draft_id("azure") == azure.campaign_id
    store.delete_draft("aws", aws.campaign_id)
    assert store.active_draft_id("aws") is None


def test_draft_name_must_be_unique_within_cloud(tmp_path):
    store = _store(tmp_path)
    store.create_draft("aws", "Recovery")

    try:
        store.create_draft("aws", "recovery")
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate draft was accepted")


def test_draft_listing_hides_malformed_persisted_experiments(tmp_path):
    store = _store(tmp_path)
    draft = store.create_draft("aws", "Malformed")
    path = store._draft_path("aws", draft.campaign_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["experiments"] = [{"id": "", "service": "", "name": "Placeholder"}]
    path.write_text(json.dumps(data), encoding="utf-8")

    assert store.list_drafts("aws") == []


def test_execution_is_an_immutable_campaign_snapshot(tmp_path):
    store = _store(tmp_path)
    campaign = store.create_draft("azure", "Redis recovery")
    campaign.experiments.append(Experiment("reboot", "azure_redis", "Reboot", "reboot.json", {"cache": "a"}))
    store.save_draft(campaign)
    execution_id = store.start_execution(campaign, "yaml-cli")
    campaign.experiments[0].variables["cache"] = "b"
    store.finish_execution(execution_id, campaign, "SUCCESS", logs=["finished"], report_path="report.txt")

    record = store.load_execution(execution_id)
    assert record["source"] == "yaml-cli"
    assert record["chaosforge_version"]
    assert record["campaign_snapshot"]["experiments"][0]["variables"]["cache"] == "a"
    assert record["experiments"][0]["variables"]["cache"] == "b"
    assert store.list_executions("azure")[0]["id"] == execution_id


def test_delete_draft_does_not_delete_its_execution_history(tmp_path):
    store = _store(tmp_path)
    campaign = store.create_draft("aws", "Checkout")
    execution_id = store.start_execution(campaign, "interactive-cli")
    store.finish_execution(execution_id, campaign, "FAILED")
    store.delete_draft("aws", campaign.campaign_id)

    assert store.list_drafts("aws") == []
    assert store.load_execution(execution_id)["status"] == "FAILED"


def test_store_rejects_invalid_inputs_and_round_trips_optional_execution_fields(tmp_path):
    store = _store(tmp_path)
    assert store.list_executions("aws") == []
    for cloud, name in (("gcp", "name"), ("aws", "")):
        try:
            store.create_draft(cloud, name)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid draft was accepted")
    campaign = store.create_draft("aws", "Valid")
    campaign.campaign_id = None
    try:
        store.save_draft(campaign)
    except ValueError:
        pass
    else:
        raise AssertionError("draft without an ID was accepted")
    malformed = store.create_draft("aws", "Malformed")
    malformed.experiments.append(Experiment("", "", "Placeholder", "", {}))
    try:
        store.save_draft(malformed)
    except ValueError as exc:
        assert "without an ID or service" in str(exc)
    else:
        raise AssertionError("invalid experiment was persisted")
    campaign = store.create_draft("aws", "Execution")
    try:
        store.start_execution(campaign, "unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid execution source was accepted")
    execution_id = store.start_execution(campaign, "web")
    record = store.finish_execution(execution_id, campaign, "SUCCESS")
    assert record["report_path"] is None
    assert store.list_executions("azure") == []
    for bad_id in ("", "../bad"):
        try:
            store.load_execution(bad_id)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid execution ID was accepted")
    try:
        store.load_draft("aws", "../bad")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid draft ID was accepted")

    campaign = store.create_draft("aws", "Errors")
    experiment = Experiment("id", "lambda", "Name", "file", {})
    experiment.error_message = "failure"
    experiment.cli_output = "output"
    campaign.experiments.append(experiment)
    store.save_draft(campaign)
    assert store.load_draft("aws", campaign.campaign_id).experiments[0].error_message == "failure"
    store.create_draft("azure", "Existing")
    duplicate = store.create_draft("azure", "Errors")
    duplicate.name = "Existing"
    try:
        store.save_draft(duplicate)
    except ValueError:
        pass
    else:
        raise AssertionError("renamed duplicate draft was accepted")
