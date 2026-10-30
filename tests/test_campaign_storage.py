import json
from unittest.mock import patch

import pytest

from chaosforge.application.campaigns.legacy_storage import (
    delete_campaign,
    list_campaigns,
    load_campaign,
    save_campaign,
)
from chaosforge.common.paths import repository_paths
from chaosforge.models import Experiment


def test_save_campaign():
    experiment = Experiment(
        id="exp-1",
        service="s3",
        name="S3 Versioning Chaos",
        json_file="chaosforge/providers/aws/components/s3/experiments/toolkit/definitions/s3-versioning-chaos.json",
        variables={"bucket_name": "test-bucket"},
    )

    mock_campaign = type("Campaign", (), {})()
    mock_campaign.experiments = [experiment]

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.get_campaign",
            return_value=mock_campaign,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ) as mock_open,
    ):
        save_campaign("demo")

    mock_open.assert_called_once_with(
        str(repository_paths().campaigns / "demo.campaign.json"),
        "w",
        encoding="utf-8",
    )

    file_handle = mock_open.return_value.__enter__.return_value

    file_handle.write.assert_called()


def test_save_campaign_with_no_experiments():
    mock_campaign = type("Campaign", (), {})()
    mock_campaign.experiments = []

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.get_campaign",
            return_value=mock_campaign,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ) as mock_open,
    ):
        save_campaign("empty")

    file_handle = mock_open.return_value.__enter__.return_value
    file_handle.write.assert_called()


def test_load_campaign():
    campaign_data = {
        "name": "demo",
        "experiments": [
            {
                "id": "exp-1",
                "service": "s3",
                "name": "S3 Versioning Chaos",
                "json_file": ("chaosforge/providers/aws/components/s3/experiments/toolkit/definitions/s3-versioning-chaos.json"),
                "variables": {
                    "bucket_name": "test-bucket",
                },
            }
        ],
    }

    mock_campaign = type("Campaign", (), {})()
    mock_campaign.experiments = []

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.exists",
            return_value=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ) as mock_open,
        patch(
            "chaosforge.application.campaigns.legacy_storage.json.load",
            return_value=campaign_data,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.get_campaign",
            return_value=mock_campaign,
        ),
        patch("chaosforge.application.campaigns.legacy_storage.clear") as mock_clear,
    ):
        mock_file = mock_open.return_value.__enter__.return_value
        mock_file.read.return_value = json.dumps(campaign_data)

        result = load_campaign("demo")

    mock_clear.assert_called_once()

    assert result is mock_campaign
    assert len(result.experiments) == 1

    experiment = result.experiments[0]

    assert isinstance(experiment, Experiment)
    assert experiment.id == "exp-1"
    assert experiment.service == "s3"
    assert experiment.name == "S3 Versioning Chaos"
    assert experiment.json_file == "chaosforge/providers/aws/components/s3/experiments/toolkit/definitions/s3-versioning-chaos.json"
    assert experiment.variables == {
        "bucket_name": "test-bucket",
    }


def test_load_campaign_without_experiments():
    campaign_data = {
        "name": "empty",
    }

    mock_campaign = type("Campaign", (), {})()
    mock_campaign.experiments = []

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.exists",
            return_value=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.json.load",
            return_value=campaign_data,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.get_campaign",
            return_value=mock_campaign,
        ),
        patch("chaosforge.application.campaigns.legacy_storage.clear") as mock_clear,
    ):
        result = load_campaign("empty")

    mock_clear.assert_called_once()
    assert result is mock_campaign
    assert result.experiments == []


def test_load_campaign_not_found():
    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.exists",
            return_value=False,
        ),
        pytest.raises(FileNotFoundError),
    ):
        load_campaign("missing")


def test_list_campaigns():
    campaign_one = {
        "name": "campaign-one",
        "experiments": [
            {"id": "1"},
            {"id": "2"},
        ],
    }

    campaign_two = {
        "experiments": [
            {"id": "3"},
        ],
    }

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.listdir",
            return_value=[
                "campaign-one.campaign.json",
                "campaign-two.campaign.json",
                "README.txt",
            ],
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ) as mock_open,
        patch(
            "chaosforge.application.campaigns.legacy_storage.json.load",
            side_effect=[
                campaign_one,
                campaign_two,
            ],
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.getmtime",
            side_effect=[100, 200],
        ),
    ):
        result = list_campaigns()

    assert len(result) == 2

    assert result[0]["name"] == "campaign-two"
    assert result[0]["experiments"] == 1
    assert result[0]["modified"] == 200

    assert result[1]["name"] == "campaign-one"
    assert result[1]["experiments"] == 2
    assert result[1]["modified"] == 100

    assert mock_open.call_count == 2


def test_list_campaigns_default_name():
    campaign_data = {
        "experiments": [],
    }

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.listdir",
            return_value=[
                "my-campaign.campaign.json",
            ],
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.json.load",
            return_value=campaign_data,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.getmtime",
            return_value=123,
        ),
    ):
        result = list_campaigns()

    assert result == [
        {
            "name": "my-campaign",
            "experiments": 0,
            "modified": 123,
        }
    ]


def test_list_campaigns_empty():
    with patch(
        "chaosforge.application.campaigns.legacy_storage.os.listdir",
        return_value=[
            "README.txt",
            "notes.json",
        ],
    ):
        result = list_campaigns()

    assert result == []


def test_delete_campaign_existing():
    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.exists",
            return_value=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.remove",
        ) as mock_remove,
    ):
        delete_campaign("demo")

    mock_remove.assert_called_once_with(
        str(repository_paths().campaigns / "demo.campaign.json")
    )


def test_delete_campaign_missing():
    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.exists",
            return_value=False,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.remove",
        ) as mock_remove,
    ):
        delete_campaign("missing")

    mock_remove.assert_not_called()


def test_save_campaign_preserves_campaign_settings():
    mock_campaign = type("Campaign", (), {})()
    mock_campaign.experiments = []
    mock_campaign.continue_on_failure = True
    mock_campaign.cloud_provider = "aws"

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.get_campaign",
            return_value=mock_campaign,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ) as mock_open,
    ):
        save_campaign("settings-test")

    file_handle = (
        mock_open.return_value.__enter__.return_value
    )

    written_json = "".join(
        call.args[0]
        for call in file_handle.write.call_args_list
    )

    data = json.loads(written_json)

    assert data["continue_on_failure"] is True
    assert data["cloud_provider"] == "aws"


def test_load_campaign_restores_campaign_settings():
    campaign_data = {
        "name": "settings-test",
        "continue_on_failure": True,
        "cloud_provider": "aws",
        "experiments": [],
    }

    mock_campaign = type("Campaign", (), {})()
    mock_campaign.experiments = []

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.exists",
            return_value=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.json.load",
            return_value=campaign_data,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.get_campaign",
            return_value=mock_campaign,
        ),
        patch("chaosforge.application.campaigns.legacy_storage.clear"),
    ):
        result = load_campaign("settings-test")

    assert result.continue_on_failure is True
    assert result.cloud_provider == "aws"

def test_load_campaign_defaults_new_settings_for_old_campaign():
    campaign_data = {
        "name": "old-campaign",
        "experiments": [],
    }

    mock_campaign = type("Campaign", (), {})()
    mock_campaign.experiments = []

    with (
        patch(
            "chaosforge.application.campaigns.legacy_storage.os.path.exists",
            return_value=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.open",
            create=True,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.json.load",
            return_value=campaign_data,
        ),
        patch(
            "chaosforge.application.campaigns.legacy_storage.get_campaign",
            return_value=mock_campaign,
        ),
        patch("chaosforge.application.campaigns.legacy_storage.clear"),
    ):
        result = load_campaign("old-campaign")

    assert result.continue_on_failure is False
    assert result.cloud_provider == "aws"
