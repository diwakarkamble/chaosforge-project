import json
import os

from chaosforge.application.campaigns.manager import (
    clear,
    get_campaign,
)
from chaosforge.common.paths import repository_paths
from chaosforge.models.experiment import Experiment

#
# Campaign storage folder
#
CAMPAIGN_FOLDER = str(repository_paths().campaigns)

os.makedirs(CAMPAIGN_FOLDER, exist_ok=True)


def save_campaign(name):
    """
    Save the current campaign as JSON.
    """

    campaign = get_campaign()

    data = {
        "name": name,
        "continue_on_failure": getattr(
            campaign,
            "continue_on_failure",
            False,
        ),
        "cloud_provider": getattr(
            campaign,
            "cloud_provider",
            "aws",
        ),
        "experiments": [],
    }

    for experiment in campaign.experiments:
        data["experiments"].append(
            {
                "id": experiment.id,
                "service": experiment.service,
                "name": experiment.name,
                "json_file": experiment.json_file,
                "variables": experiment.variables,
            }
        )

    file_path = os.path.join(
        CAMPAIGN_FOLDER,
        f"{name}.campaign.json",
    )

    with open(file_path, "w", encoding="utf-8") as fp:
        json.dump(
            data,
            fp,
            indent=4,
        )


def load_campaign(name):
    """
    Load a campaign from disk.
    """

    file_path = os.path.join(
        CAMPAIGN_FOLDER,
        f"{name}.campaign.json",
    )

    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    with open(file_path, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    campaign = get_campaign()

    clear()

    campaign.continue_on_failure = data.get(
        "continue_on_failure",
        False,
    )

    campaign.cloud_provider = data.get(
        "cloud_provider",
        "aws",
    )

    for item in data.get("experiments", []):
        experiment = Experiment(
            id=item["id"],
            service=item["service"],
            name=item["name"],
            json_file=item["json_file"],
            variables=item["variables"],
        )

        campaign.experiments.append(experiment)

    return campaign


def list_campaigns():
    """
    Return all saved campaigns.
    """

    campaigns = []

    for file in os.listdir(CAMPAIGN_FOLDER):
        if not file.endswith(".campaign.json"):
            continue

        file_path = os.path.join(
            CAMPAIGN_FOLDER,
            file,
        )

        #
        # Read campaign
        #
        with open(
            file_path,
            "r",
            encoding="utf-8",
        ) as fp:
            data = json.load(fp)

        campaigns.append(
            {
                "name": data.get(
                    "name",
                    file.replace(".campaign.json", ""),
                ),
                "experiments": len(data.get("experiments", [])),
                "modified": os.path.getmtime(file_path),
            }
        )

    campaigns.sort(
        key=lambda x: x["modified"],
        reverse=True,
    )

    return campaigns


def delete_campaign(name):
    """
    Delete a saved campaign.
    """

    file_path = os.path.join(
        CAMPAIGN_FOLDER,
        f"{name}.campaign.json",
    )

    if os.path.exists(file_path):
        os.remove(file_path)
