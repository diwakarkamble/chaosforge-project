from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

from chaosforge.reporting.report_generator import generate_report

# ----------------------------------------------------------
# Success
# ----------------------------------------------------------


@patch("chaosforge.reporting.report_generator.show_report_summary")
@patch("chaosforge.reporting.report_generator.display_name")
@patch("chaosforge.reporting.report_generator.open", new_callable=mock_open)
@patch("chaosforge.reporting.report_generator.datetime")
@patch("chaosforge.reporting.report_generator.REPORTS_DIR")
def test_generate_report_success(
    mock_reports_dir,
    mock_datetime,
    mock_file,
    mock_display_name,
    mock_summary,
):

    mock_reports_dir.mkdir = MagicMock()
    mock_reports_dir.__truediv__.return_value = Path(
        "reports/campaign-report-20260730-120000.txt"
    )

    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now

    mock_display_name.return_value = "AWS Lambda"

    experiment = MagicMock()
    experiment.service = "lambda"
    experiment.name = "Memory Chaos"
    experiment.status = "SUCCESS"

    campaign = MagicMock()
    campaign.name = "Campaign"
    campaign.start_time = now
    campaign.end_time = now
    campaign.duration = 15.2
    campaign.experiments = [experiment]

    generate_report(campaign)

    report = "".join(call.args[0] for call in mock_file().write.call_args_list)

    assert "CHAOSFORGE EXECUTION REPORT" in report
    assert "ChaosForge Version" in report
    assert "Campaign Result" in report
    assert "SUCCESS" in report
    assert "Successful" in report
    assert "Failed" in report

    mock_summary.assert_called_once()


@patch("chaosforge.reporting.report_generator.show_report_summary")
@patch("chaosforge.reporting.report_generator.display_name")
@patch("chaosforge.reporting.report_generator.open", new_callable=mock_open)
@patch("chaosforge.reporting.report_generator.datetime")
@patch("chaosforge.reporting.report_generator.REPORTS_DIR")
def test_generate_report_includes_node_stress_impact_summary(
    mock_reports_dir,
    mock_datetime,
    mock_file,
    mock_display_name,
    mock_summary,
):

    mock_reports_dir.mkdir = MagicMock()
    mock_reports_dir.__truediv__.return_value = Path("report.txt")

    now = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now

    mock_display_name.return_value = "Azure Kubernetes Service (AKS)"

    experiment = MagicMock()
    experiment.service = "aks"
    experiment.name = "Node Memory Pressure"
    experiment.status = "SUCCESS"
    experiment.cli_output = """
During-experiment impact observed:
  Ready pods on target node: baseline 10/10  → worst 8/10
  ⚠ Ready workload pods dropped by 2 on target node during stress
  Worst DNS lookup time during fault: 120 ms

Node health:
  ✓ Node Ready: True
"""

    campaign = MagicMock()
    campaign.name = "Campaign"
    campaign.start_time = now
    campaign.end_time = now
    campaign.duration = 30.0
    campaign.experiments = [experiment]

    generate_report(campaign)

    report = "".join(call.args[0] for call in mock_file().write.call_args_list)

    assert "During-Experiment Impact Summary" in report
    assert "Ready pods on target node: baseline 10/10  → worst 8/10" in report
    assert "Worst DNS lookup time during fault: 120 ms" in report

    mock_summary.assert_called_once()


# ----------------------------------------------------------
# Partial Success
# ----------------------------------------------------------


@patch("chaosforge.reporting.report_generator.show_report_summary")
@patch("chaosforge.reporting.report_generator.display_name")
@patch("chaosforge.reporting.report_generator.open", new_callable=mock_open)
@patch("chaosforge.reporting.report_generator.datetime")
@patch("chaosforge.reporting.report_generator.REPORTS_DIR")
def test_generate_report_partial(
    mock_reports_dir,
    mock_datetime,
    mock_file,
    mock_display_name,
    mock_summary,
):

    mock_reports_dir.mkdir = MagicMock()
    mock_reports_dir.__truediv__.return_value = Path("report.txt")

    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now

    mock_display_name.side_effect = lambda service: service.title()

    exp1 = MagicMock()
    exp1.service = "lambda"
    exp1.name = "Memory"
    exp1.status = "SUCCESS"

    exp2 = MagicMock()
    exp2.service = "rds"
    exp2.name = "IOPS"
    exp2.status = "FAILED"

    campaign = MagicMock()
    campaign.name = "Campaign"
    campaign.start_time = now
    campaign.end_time = now
    campaign.duration = 22.5
    campaign.experiments = [exp1, exp2]

    generate_report(campaign)

    report = "".join(c.args[0] for c in mock_file().write.call_args_list)

    assert "Campaign Result" in report
    assert "PARTIAL SUCCESS" in report
    assert "Successful" in report
    assert "Failed" in report

    mock_summary.assert_called_once()


@patch("chaosforge.reporting.report_generator.show_report_summary")
@patch("chaosforge.reporting.report_generator.display_name")
@patch("chaosforge.reporting.report_generator.open", new_callable=mock_open)
@patch("chaosforge.reporting.report_generator.datetime")
@patch("chaosforge.reporting.report_generator.REPORTS_DIR")
def test_generate_report_counts_warning_success_without_failure(
    mock_reports_dir,
    mock_datetime,
    mock_file,
    mock_display_name,
    mock_summary,
):
    mock_reports_dir.mkdir = MagicMock()
    mock_reports_dir.__truediv__.return_value = Path("report.txt")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    mock_display_name.return_value = "Amazon EKS"
    experiment = SimpleNamespace(
        service="eks",
        name="Network Delay",
        status="SUCCESS_WITH_WARNINGS",
        error_message="",
        cli_output="",
    )
    campaign = MagicMock(
        name="Campaign",
        start_time=now,
        end_time=now,
        duration=4.0,
        experiments=[experiment],
    )

    generate_report(campaign)

    report = "".join(call.args[0] for call in mock_file().write.call_args_list)
    assert "Successful        : 1" in report
    assert "With Warnings     : 1" in report
    assert "Failed            : 0" in report
    assert "Campaign Result : SUCCESS_WITH_WARNINGS" in report
    mock_summary.assert_called_once()


# ----------------------------------------------------------
# Failed
# ----------------------------------------------------------


@patch("chaosforge.reporting.report_generator.show_report_summary")
@patch("chaosforge.reporting.report_generator.display_name")
@patch("chaosforge.reporting.report_generator.open", new_callable=mock_open)
@patch("chaosforge.reporting.report_generator.datetime")
@patch("chaosforge.reporting.report_generator.REPORTS_DIR")
def test_generate_report_failed(
    mock_reports_dir,
    mock_datetime,
    mock_file,
    mock_display_name,
    mock_summary,
):

    mock_reports_dir.mkdir = MagicMock()
    mock_reports_dir.__truediv__.return_value = Path("report.txt")

    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now

    mock_display_name.return_value = "AWS Lambda"

    experiment = MagicMock()
    experiment.service = "lambda"
    experiment.name = "Memory"
    experiment.status = "FAILED"

    campaign = MagicMock()
    campaign.name = "Campaign"
    campaign.start_time = now
    campaign.end_time = now
    campaign.duration = 4.0
    campaign.experiments = [experiment]

    generate_report(campaign)

    report = "".join(c.args[0] for c in mock_file().write.call_args_list)

    assert "Campaign Result" in report
    assert "FAILED" in report
    assert "Successful" in report
    assert "Failed" in report

    mock_summary.assert_called_once()


@patch("chaosforge.reporting.report_generator.show_report_summary")
@patch("chaosforge.reporting.report_generator.display_name")
@patch("chaosforge.reporting.report_generator.open", new_callable=mock_open)
@patch("chaosforge.reporting.report_generator.datetime")
@patch("chaosforge.reporting.report_generator.REPORTS_DIR")
def test_generate_report_includes_actionable_failure_details(
    mock_reports_dir,
    mock_datetime,
    mock_file,
    mock_display_name,
    _mock_summary,
):
    mock_reports_dir.mkdir = MagicMock()
    mock_reports_dir.__truediv__.return_value = Path("report.txt")
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    mock_display_name.return_value = "AWS Lambda"
    experiment = SimpleNamespace(
        service="lambda",
        name="Memory",
        status="FAILED",
        error_message="State file belongs to another target",
        cli_output="Action restore: failed\n",
    )
    campaign = MagicMock(
        name="Campaign",
        start_time=now,
        end_time=now,
        duration=4.0,
        experiments=[experiment],
    )

    generate_report(campaign)

    report = "".join(call.args[0] for call in mock_file().write.call_args_list)
    assert "Failure Details: State file belongs to another target" in report
    assert "Action restore: failed" in report


# ----------------------------------------------------------
# Empty Campaign
# ----------------------------------------------------------


@patch("chaosforge.reporting.report_generator.show_report_summary")
@patch("chaosforge.reporting.report_generator.display_name")
@patch("chaosforge.reporting.report_generator.open", new_callable=mock_open)
@patch("chaosforge.reporting.report_generator.datetime")
@patch("chaosforge.reporting.report_generator.REPORTS_DIR")
def test_generate_report_empty_campaign(
    mock_reports_dir,
    mock_datetime,
    mock_file,
    mock_display_name,
    mock_summary,
):

    mock_reports_dir.mkdir = MagicMock()
    mock_reports_dir.__truediv__.return_value = Path("report.txt")

    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now

    mock_display_name.return_value = "AWS Lambda"

    class Campaign:
        pass

    campaign = Campaign()
    campaign.name = "Campaign"
    campaign.start_time = now
    campaign.end_time = now
    campaign.duration = 0.0
    campaign.experiments = []

    generate_report(campaign)

    report = "".join(c.args[0] for c in mock_file().write.call_args_list)

    assert "Total Experiments" in report
    assert "Successful" in report
    assert "Failed" in report
    assert "Campaign Result" in report
    assert "SUCCESS" in report

    mock_summary.assert_called_once()
