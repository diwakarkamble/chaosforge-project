from unittest.mock import ANY, MagicMock, patch

import pytest

from chaosforge.application.services.campaign_service import (
    add_experiment,
    clear_current_campaign,
    delete_saved_campaign,
    execute_current_campaign,
    execute_current_campaign_web,
    get_current_campaign,
    get_experiment,
    get_experiments,
    get_selected_experiments,
    list_saved_campaigns,
    load_saved_campaign,
    remove_experiment,
    save_current_campaign,
    update_experiment,
)

# ----------------------------------------------------------
# Add Experiment
# ----------------------------------------------------------


@patch("builtins.print")
@patch("chaosforge.application.services.campaign_service.add")
@patch("chaosforge.application.services.campaign_service.create_experiment")
def test_add_experiment(mock_create_experiment, mock_add, mock_print):

    metadata = {
        "service": "lambda",
    }

    selected = {
        "id": "memory",
        "name": "Memory Chaos",
        "json": "memory.json",
    }

    variables = {
        "memory": "1024",
    }

    experiment = MagicMock()

    mock_create_experiment.return_value = experiment

    result = add_experiment(
        metadata,
        selected,
        variables,
    )

    assert result == experiment

    mock_create_experiment.assert_called_once_with(
        "lambda",
        selected,
        variables,
        default_region=ANY,
    )

    mock_add.assert_called_once_with(experiment)

    assert mock_create_experiment.call_args.kwargs["default_region"] is not None
    assert "1024" not in "\n".join(
        " ".join(map(str, call.args)) for call in mock_print.call_args_list
    )


# ----------------------------------------------------------
# AWS Region Already Present
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.add")
@patch("chaosforge.application.services.campaign_service.create_experiment")
def test_add_experiment_existing_region(mock_create_experiment, mock_add):

    metadata = {
        "service": "lambda",
    }

    selected = {
        "id": "memory",
        "name": "Memory",
        "json": "memory.json",
    }

    variables = {
        "aws_region": "us-east-1",
    }
    mock_create_experiment.return_value = MagicMock()

    add_experiment(
        metadata,
        selected,
        variables,
    )

    assert variables["aws_region"] == "us-east-1"
    assert mock_create_experiment.call_args.args[2]["aws_region"] == "us-east-1"


# ----------------------------------------------------------
# Get Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.get_campaign")
def test_get_current_campaign(mock_get):

    campaign = MagicMock()

    mock_get.return_value = campaign

    assert get_current_campaign() == campaign


# ----------------------------------------------------------
# Get Experiments
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.list_all")
def test_get_experiments(mock_list):

    mock_list.return_value = ["exp1", "exp2"]

    assert get_experiments() == ["exp1", "exp2"]


# ----------------------------------------------------------
# Remove Experiment
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.remove")
def test_remove_experiment(mock_remove):

    remove_experiment(2)

    mock_remove.assert_called_once_with(2)


# ----------------------------------------------------------
# Clear Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.clear")
def test_clear_current_campaign(mock_clear):

    clear_current_campaign()

    mock_clear.assert_called_once()


# ----------------------------------------------------------
# Execute Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.runner.execute_campaign")
@patch("chaosforge.application.services.campaign_service.get_campaign")
def test_execute_current_campaign(
    mock_get_campaign,
    mock_execute,
):

    campaign = MagicMock()

    campaign.experiments = [MagicMock()]

    mock_get_campaign.return_value = campaign

    result = execute_current_campaign()

    assert result == campaign

    mock_execute.assert_called_once_with(campaign)


# ----------------------------------------------------------
# Execute Empty Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.get_campaign")
def test_execute_current_campaign_empty(mock_get_campaign):

    campaign = MagicMock()

    campaign.experiments = []

    mock_get_campaign.return_value = campaign

    with pytest.raises(ValueError, match="Campaign is empty."):
        execute_current_campaign()


# ----------------------------------------------------------
# Selected Experiments
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.get_campaign")
def test_get_selected_experiments(mock_get_campaign):

    experiment_1 = MagicMock()
    experiment_2 = MagicMock()
    experiment_3 = MagicMock()

    campaign = MagicMock()
    campaign.experiments = [
        experiment_1,
        experiment_2,
        experiment_3,
    ]

    mock_get_campaign.return_value = campaign

    result = get_selected_experiments(
        [-1, 0, 2, 99],
    )

    assert result == [
        experiment_1,
        experiment_3,
    ]

    mock_get_campaign.assert_called_once()


# ----------------------------------------------------------
# Get Experiment
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.get")
def test_get_experiment(mock_get):

    experiment = MagicMock()
    mock_get.return_value = experiment

    result = get_experiment(3)

    assert result == experiment
    mock_get.assert_called_once_with(3)


# ----------------------------------------------------------
# Update Experiment
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.update")
def test_update_experiment(mock_update):

    experiment = MagicMock()

    update_experiment(
        1,
        experiment,
    )

    mock_update.assert_called_once_with(
        1,
        experiment,
    )


# ----------------------------------------------------------
# Execute Web Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.web_runner.execute_campaign")
@patch("chaosforge.application.services.campaign_service.get_campaign")
def test_execute_current_campaign_web(
    mock_get_campaign,
    mock_execute,
):

    campaign = MagicMock()
    campaign.experiments = [MagicMock()]

    mock_get_campaign.return_value = campaign

    result = execute_current_campaign_web()

    assert result == campaign

    mock_execute.assert_called_once_with(campaign)


# ----------------------------------------------------------
# Execute Empty Web Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.get_campaign")
def test_execute_current_campaign_web_empty(
    mock_get_campaign,
):

    campaign = MagicMock()
    campaign.experiments = []

    mock_get_campaign.return_value = campaign

    with pytest.raises(
        ValueError,
        match="Campaign is empty.",
    ):
        execute_current_campaign_web()


# ----------------------------------------------------------
# Save Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.save_campaign")
def test_save_current_campaign(mock_save):

    save_current_campaign("my-campaign")

    mock_save.assert_called_once_with(
        "my-campaign",
    )


# ----------------------------------------------------------
# Load Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.load_campaign")
def test_load_saved_campaign(mock_load):

    campaign = MagicMock()
    mock_load.return_value = campaign

    result = load_saved_campaign("my-campaign")

    assert result == campaign

    mock_load.assert_called_once_with(
        "my-campaign",
    )


# ----------------------------------------------------------
# List Saved Campaigns
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.list_campaigns")
def test_list_saved_campaigns(mock_list):

    campaigns = [
        "campaign-1",
        "campaign-2",
    ]

    mock_list.return_value = campaigns

    result = list_saved_campaigns()

    assert result == campaigns

    mock_list.assert_called_once()


# ----------------------------------------------------------
# Delete Saved Campaign
# ----------------------------------------------------------


@patch("chaosforge.application.services.campaign_service.delete_campaign")
def test_delete_saved_campaign(mock_delete):

    delete_saved_campaign("my-campaign")

    mock_delete.assert_called_once_with(
        "my-campaign",
    )
