from chaosforge.application.campaigns.duplicates import experiment_fingerprint
from chaosforge.application.campaigns.factory import AZURE_SERVICES
from chaosforge.models.campaign import Campaign
from chaosforge.storage.campaign_history import CampaignHistoryStore

campaign = Campaign()
campaigns = {"aws": campaign}
history_store = CampaignHistoryStore()


def _cloud(cloud):
    return cloud if cloud in {"aws", "azure"} else "aws"


def _campaign(cloud=None):
    cloud = _cloud(cloud)
    if cloud not in campaigns:
        campaigns[cloud] = Campaign(cloud_provider=cloud)
    campaign = campaigns[cloud]
    if campaign.campaign_id is None:
        campaign_id = history_store.active_draft_id(cloud)
        if campaign_id:
            try:
                return replace_campaign(history_store.load_draft(cloud, campaign_id), cloud)
            except (FileNotFoundError, ValueError):
                history_store.clear_active_draft(cloud)
    return campaign


def _save_if_draft(campaign):
    if campaign.campaign_id:
        history_store.save_draft(campaign)


def create_draft(name, cloud):
    source = history_store.create_draft(_cloud(cloud), name)
    campaign = replace_campaign(source, cloud)
    history_store.set_active_draft(cloud, campaign.campaign_id)
    return campaign


def open_draft(campaign_id, cloud):
    campaign = replace_campaign(history_store.load_draft(_cloud(cloud), campaign_id), cloud)
    history_store.set_active_draft(cloud, campaign.campaign_id)
    return campaign


def list_drafts(cloud):
    return history_store.list_drafts(_cloud(cloud))


def set_chaos_mesh_version_decisions(decisions, cloud=None):
    campaign = _campaign(cloud)
    campaign.chaos_mesh_version_decisions = dict(decisions)
    _save_if_draft(campaign)
    return campaign


def delete_draft(campaign_id, cloud):
    history_store.delete_draft(_cloud(cloud), campaign_id)
    active = _campaign(cloud)
    if active.campaign_id == campaign_id:
        active.name = "Default Campaign"
        active.experiments.clear()
        active.campaign_id = None
        active.created_at = None
        active.updated_at = None


def add(experiment, cloud=None):

    cloud = cloud or (
        "azure" if getattr(experiment, "service", "") in AZURE_SERVICES else "aws"
    )
    campaign = _campaign(cloud)
    fingerprint = experiment_fingerprint(experiment)
    if fingerprint and any(
        experiment_fingerprint(existing) == fingerprint
        for existing in campaign.experiments
    ):
        raise ValueError(
            "Campaign already contains an identical experiment configuration. "
            "Edit the existing experiment or change its target or inputs."
        )
    campaign.experiments.append(experiment)
    _save_if_draft(campaign)


def remove(index, cloud=None):

    campaign = _campaign(cloud)
    if 0 <= index < len(campaign.experiments):
        campaign.experiments.pop(index)
        _save_if_draft(campaign)


def list_all(cloud=None):

    return _campaign(cloud).experiments


def clear(cloud=None):

    campaign = _campaign(cloud)
    campaign.experiments.clear()
    campaign.history_reset_at = history_store._now()
    campaign.chaos_mesh_version_decisions.clear()
    _save_if_draft(campaign)


def get_campaign(cloud=None):

    return _campaign(cloud)


def replace_campaign(source, cloud=None):
    cloud = _cloud(cloud or source.cloud_provider)
    if cloud not in campaigns:
        campaigns[cloud] = Campaign(cloud_provider=cloud)
    campaign = campaigns[cloud]
    campaign.name = source.name
    campaign.continue_on_failure = source.continue_on_failure
    campaign.irreversible_operations_acknowledged = getattr(
        source, "irreversible_operations_acknowledged", False
    )
    campaign.cloud_provider = source.cloud_provider
    campaign.experiments = list(source.experiments)
    campaign.report_timezone = getattr(source, "report_timezone", None)
    # Replacing with an unsaved campaign must not inherit the current draft ID.
    # Otherwise a YAML review or other transient campaign can overwrite a persisted draft.
    campaign.campaign_id = getattr(source, "campaign_id", None)
    campaign.created_at = getattr(source, "created_at", None)
    campaign.updated_at = getattr(source, "updated_at", None)
    campaign.history_reset_at = getattr(source, "history_reset_at", None)
    campaign.chaos_mesh_version_decisions = dict(
        getattr(source, "chaos_mesh_version_decisions", {})
    )
    if campaign.campaign_id is None:
        history_store.clear_active_draft(cloud)
    _save_if_draft(campaign)
    return campaign


# ---------------------------------------
# NEW
# ---------------------------------------


def get(index, cloud=None):

    campaign = _campaign(cloud)
    if 0 <= index < len(campaign.experiments):
        return campaign.experiments[index]

    return None


def update(index, experiment, cloud=None):

    cloud = cloud or (
        "azure" if getattr(experiment, "service", "") in AZURE_SERVICES else "aws"
    )
    campaign = _campaign(cloud)
    if 0 <= index < len(campaign.experiments):
        campaign.experiments[index] = experiment
        _save_if_draft(campaign)


def get_selected(indices, cloud=None):

    campaign = _campaign(cloud)
    experiments = []

    for index in indices:
        if 0 <= index < len(campaign.experiments):
            experiments.append(campaign.experiments[index])

    return experiments
