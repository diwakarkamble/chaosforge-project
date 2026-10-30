from unittest.mock import patch

from rich.console import Console
from rich.panel import Panel

from chaosforge.interfaces.cli.interactive.ui import dashboard as dashboard_module
from chaosforge.interfaces.cli.interactive.ui.dashboard import dashboard

# ----------------------------------------------------------
# Default Profile
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.dashboard.console")
def test_dashboard_default_profile(mock_console):

    dashboard(
        region="eu-central-1",
        campaign_name="Chaos Campaign",
        experiment_count=5,
    )

    mock_console.print.assert_called_once()

    panel = mock_console.print.call_args.args[0]

    assert isinstance(panel, Panel)

    assert panel.title == "[bold bright_cyan]Mission Control[/bold bright_cyan]"

    assert panel.border_style == "bright_blue"
    assert len(panel.renderable.rows) == 5


# ----------------------------------------------------------
# Custom Profile
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.dashboard.console")
def test_dashboard_custom_profile(mock_console):

    dashboard(
        region="us-east-1",
        campaign_name="Production",
        experiment_count=10,
        aws_profile="prod",
    )

    panel = mock_console.print.call_args.args[0]

    assert isinstance(panel, Panel)


# ----------------------------------------------------------
# Zero Experiments
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.dashboard.console")
def test_dashboard_zero_experiments(mock_console):

    dashboard(
        region="ap-south-1",
        campaign_name="Empty Campaign",
        experiment_count=0,
    )

    mock_console.print.assert_called_once()


# ----------------------------------------------------------
# Empty Strings
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.dashboard.console")
def test_dashboard_empty_values(mock_console):

    dashboard(
        region="",
        campaign_name="",
        experiment_count=0,
        aws_profile="",
    )

    mock_console.print.assert_called_once()


# ----------------------------------------------------------
# Large Experiment Count
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.ui.dashboard.console")
def test_dashboard_large_experiment_count(mock_console):

    dashboard(
        region="eu-west-1",
        campaign_name="Stress Test",
        experiment_count=999,
    )

    panel = mock_console.print.call_args.args[0]

    assert isinstance(panel, Panel)


def test_azure_dashboard_lists_both_execution_engines(monkeypatch):
    console = Console(record=True, width=100)
    monkeypatch.setattr(dashboard_module, "console", console)

    dashboard(
        region="azure",
        campaign_name="Redis",
        experiment_count=1,
        cloud="azure",
    )

    assert "Chaos Studio + Chaos Toolkit" in console.export_text()
