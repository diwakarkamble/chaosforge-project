from unittest.mock import MagicMock, patch

from chaosforge.interfaces.cli.interactive.campaign_result import (
    show_campaign_result_menu,
)

# ----------------------------------------------------------
# Return to Main Menu
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.campaign_result.prompt")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.title")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.console")
def test_campaign_result_return(
    mock_console,
    mock_title,
    mock_prompt,
):

    campaign = MagicMock()

    campaign.name = "Test Campaign"

    success = MagicMock(status="SUCCESS")

    failed = MagicMock(status="FAILED")

    campaign.experiments = [success, failed]

    mock_prompt.return_value = "0"

    assert show_campaign_result_menu(campaign) is None


# ----------------------------------------------------------
# Retry Failed
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.campaign_result.prompt")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.title")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.console")
def test_campaign_result_retry(
    mock_console,
    mock_title,
    mock_prompt,
):

    campaign = MagicMock()

    campaign.name = "Campaign"

    campaign.experiments = [
        MagicMock(status="SUCCESS"),
        MagicMock(status="FAILED"),
    ]

    mock_prompt.return_value = "1"

    assert show_campaign_result_menu(campaign) == "retry"


# ----------------------------------------------------------
# Edit Failed
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.campaign_result.prompt")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.title")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.console")
def test_campaign_result_edit(
    mock_console,
    mock_title,
    mock_prompt,
):

    campaign = MagicMock()

    campaign.name = "Campaign"

    campaign.experiments = [
        MagicMock(status="FAILED"),
    ]

    mock_prompt.return_value = "2"

    assert show_campaign_result_menu(campaign) == "edit"


# ----------------------------------------------------------
# No Failed Experiments
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.campaign_result.prompt")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.title")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.console")
def test_campaign_result_no_failed(
    mock_console,
    mock_title,
    mock_prompt,
):

    campaign = MagicMock()

    campaign.name = "Campaign"

    campaign.experiments = [
        MagicMock(status="SUCCESS"),
        MagicMock(status="SUCCESS"),
    ]

    # Invalid choice first, then exit
    mock_prompt.side_effect = [
        "1",
        "0",
    ]

    assert show_campaign_result_menu(campaign) is None


# ----------------------------------------------------------
# Invalid Choice then Exit
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.campaign_result.prompt")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.title")
@patch("chaosforge.interfaces.cli.interactive.campaign_result.console")
def test_campaign_result_invalid_choice(
    mock_console,
    mock_title,
    mock_prompt,
):

    campaign = MagicMock()

    campaign.name = "Campaign"

    campaign.experiments = [
        MagicMock(status="SUCCESS"),
        MagicMock(status="FAILED"),
    ]

    mock_prompt.side_effect = [
        "99",
        "0",
    ]

    assert show_campaign_result_menu(campaign) is None
