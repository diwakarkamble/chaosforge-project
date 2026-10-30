from chaosforge.application.campaigns.factory import AZURE_SERVICES, create_experiment
from chaosforge.application.campaigns.legacy_storage import (
    delete_campaign,
    list_campaigns,
    load_campaign,
    save_campaign,
)
from chaosforge.application.campaigns.manager import (
    add,
    clear,
    create_draft,
    delete_draft,
    get,
    get_campaign,
    list_all,
    list_drafts,
    open_draft,
    remove,
    set_chaos_mesh_version_decisions,
    update,
)
from chaosforge.application.services.lifecycle_execution import LifecycleExecutionService
from chaosforge.interfaces.web.config import AWS_REGION

lifecycle_service = LifecycleExecutionService()
runner = lifecycle_service
web_runner = lifecycle_service


def get_selected_experiments(indices, cloud=None):

    campaign = get_campaign(cloud) if cloud else get_campaign()

    return [
        campaign.experiments[i] for i in indices if 0 <= i < len(campaign.experiments)
    ]


def add_experiment(metadata, selected_experiment, variables, cloud=None):
    """
    Create an Experiment object and
    add it to the active campaign.
    """

    experiment = create_experiment(
        metadata["service"],
        selected_experiment,
        variables,
        default_region=AWS_REGION,
    )

    print("=" * 60)
    print("ADDING EXPERIMENT:", experiment.name)
    print("SERVICE:", experiment.service)
    print("=" * 60)

    selected_cloud = cloud or ("azure" if metadata["service"] in AZURE_SERVICES else "aws")
    if cloud:
        add(experiment, selected_cloud)
    else:
        add(experiment)

    campaign = get_campaign(selected_cloud)
    campaign.cloud_provider = selected_cloud

    total_campaign = get_campaign(selected_cloud)
    print("TOTAL EXPERIMENTS:", len(total_campaign.experiments))

    return experiment


def get_current_campaign(cloud=None):

    return get_campaign(cloud) if cloud else get_campaign()


def get_experiments(cloud=None):

    return list_all(cloud) if cloud else list_all()


def get_experiment(index, cloud=None):

    return get(index, cloud) if cloud else get(index)


def update_experiment(index, experiment, cloud=None):

    if cloud:
        update(index, experiment, cloud)
    else:
        update(index, experiment)


def remove_experiment(index, cloud=None):

    if cloud:
        remove(index, cloud)
    else:
        remove(index)


def clear_current_campaign(cloud=None):

    if cloud:
        clear(cloud)
    else:
        clear()


#
# ------------------------------------------------------------------
# CLI Execution
# ------------------------------------------------------------------
#
def execute_current_campaign():

    campaign = get_campaign()

    if not campaign.experiments:
        raise ValueError("Campaign is empty.")

    lifecycle_service.execute_campaign(campaign)

    return campaign


#
# ------------------------------------------------------------------
# Web Execution
# ------------------------------------------------------------------
#
def execute_current_campaign_web():

    campaign = get_campaign()

    if not campaign.experiments:
        raise ValueError("Campaign is empty.")

    lifecycle_service.execute_campaign(campaign)

    return campaign


#
# ------------------------------------------------------------------
# Campaign Storage
# ------------------------------------------------------------------
#


def save_current_campaign(name):

    save_campaign(name)


def load_saved_campaign(name):

    return load_campaign(name)


def list_saved_campaigns():

    return list_campaigns()


def delete_saved_campaign(name):

    delete_campaign(name)


def create_campaign_draft(name, cloud):
    return create_draft(name, cloud)


def open_campaign_draft(campaign_id, cloud):
    return open_draft(campaign_id, cloud)


def list_campaign_drafts(cloud):
    return list_drafts(cloud)


def delete_campaign_draft(campaign_id, cloud):
    delete_draft(campaign_id, cloud)


def save_chaos_mesh_version_decisions(decisions, cloud=None):
    return set_chaos_mesh_version_decisions(decisions, cloud)
