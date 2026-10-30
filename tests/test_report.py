from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from chaosforge.interfaces.cli.interactive.ui.report import show_report_summary


def create_campaign():

    campaign = MagicMock()

    campaign.name = "Chaos Campaign"

    campaign.duration = 12.5

    campaign.start_time = datetime(2026, 7, 30, tzinfo=timezone.utc)

    campaign.end_time = datetime(2026, 7, 30, 0, 10, tzinfo=timezone.utc)

    campaign.experiments = [MagicMock(), MagicMock()]

    return campaign


# ==========================================================
# SUCCESS
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.ui.report.console")
def test_show_report_summary_success(mock_console):

    campaign = create_campaign()

    show_report_summary(
        campaign,
        success=2,
        failed=0,
        overall="SUCCESS",
        report_file=Path("report.txt"),
    )

    assert mock_console.print.call_count >= 5


# ==========================================================
# FAILED
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.ui.report.console")
def test_show_report_summary_failed(mock_console):

    campaign = create_campaign()

    show_report_summary(
        campaign,
        success=0,
        failed=2,
        overall="FAILED",
        report_file=Path("report.txt"),
    )

    assert mock_console.print.call_count >= 5


# ==========================================================
# PARTIAL SUCCESS
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.ui.report.console")
def test_show_report_summary_partial(mock_console):

    campaign = create_campaign()

    show_report_summary(
        campaign,
        success=1,
        failed=1,
        overall="PARTIAL SUCCESS",
        report_file=Path("report.txt"),
    )

    assert mock_console.print.call_count >= 5
