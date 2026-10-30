from unittest.mock import MagicMock, patch

from rich.panel import Panel

from chaosforge.interfaces.cli.interactive.ui.execution import (
    show_campaign_complete,
    show_campaign_start,
    show_experiment,
)

# ----------------------------------------------------------
# Campaign Start
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.execution.console")
def test_show_campaign_start(mock_console):

    campaign = MagicMock()

    campaign.name = "Chaos Campaign"

    campaign.experiments = [MagicMock(), MagicMock()]

    show_campaign_start(campaign)

    assert mock_console.print.call_count == 2

    panel = mock_console.print.call_args.args[0]

    assert isinstance(panel, Panel)

    assert panel.title == "[bold bright_cyan]Mission Execution[/bold bright_cyan]"

    assert panel.border_style == "bright_blue"


# ----------------------------------------------------------
# Show Experiment
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.execution.console")
def test_show_experiment(mock_console):

    experiment = MagicMock()

    experiment.service = "AWS Lambda"

    experiment.name = "Memory Chaos"

    show_experiment(2, 5, experiment)

    assert mock_console.print.call_count == 2

    panel = mock_console.print.call_args.args[0]

    assert isinstance(panel, Panel)

    assert panel.title == "[bold bright_cyan]Executing Experiment[/bold bright_cyan]"

    assert panel.border_style == "bright_blue"


# ----------------------------------------------------------
# Campaign Complete - Mixed Results
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.execution.console")
def test_show_campaign_complete(mock_console):

    campaign = MagicMock()

    campaign.name = "Chaos Campaign"

    campaign.duration = 12.34

    campaign.experiments = [
        MagicMock(status="SUCCESS"),
        MagicMock(status="FAILED"),
        MagicMock(status="SUCCESS"),
    ]

    show_campaign_complete(campaign)

    assert mock_console.print.call_count == 2

    panel = mock_console.print.call_args.args[0]

    assert isinstance(panel, Panel)

    assert panel.title == "[bold green]MISSION COMPLETED[/bold green]"

    assert panel.border_style == "green"


# ----------------------------------------------------------
# Campaign Complete - All Success
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.execution.console")
def test_show_campaign_complete_all_success(mock_console):

    campaign = MagicMock()

    campaign.name = "Campaign"

    campaign.duration = 5.00

    campaign.experiments = [
        MagicMock(status="SUCCESS"),
        MagicMock(status="SUCCESS"),
    ]

    show_campaign_complete(campaign)

    assert mock_console.print.call_count == 2


# ----------------------------------------------------------
# Campaign Complete - Case Insensitive
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.execution.console")
def test_show_campaign_complete_case_insensitive(mock_console):

    campaign = MagicMock()

    campaign.name = "Campaign"

    campaign.duration = 9.5

    campaign.experiments = [
        MagicMock(status="success"),
        MagicMock(status="Success"),
        MagicMock(status="SUCCESS"),
    ]

    show_campaign_complete(campaign)

    assert mock_console.print.call_count == 2


# ----------------------------------------------------------
# Campaign Complete - All Failed
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.execution.console")
def test_show_campaign_complete_all_failed(mock_console):

    campaign = MagicMock()

    campaign.name = "Campaign"

    campaign.duration = 3.21

    campaign.experiments = [
        MagicMock(status="FAILED"),
        MagicMock(status="FAILED"),
    ]

    show_campaign_complete(campaign)

    assert mock_console.print.call_count == 2
