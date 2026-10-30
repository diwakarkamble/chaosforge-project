import re
from datetime import datetime, timezone

from chaosforge.application.discovery import display_name
from chaosforge.application.services.user_settings import get_timezone_id
from chaosforge.common.paths import repository_paths
from chaosforge.common.version import chaosforge_version
from chaosforge.interfaces.cli.interactive.ui.report import show_report_summary
from chaosforge.reporting.time_utils import format_report_time

REPORTS_DIR = repository_paths().reports


def _format_label(name):
    """
    Convert variable name into a readable label.
    """
    return name.replace("_", " ").title()


# Matches all ANSI/VT100 escape sequences: ESC[...m, ESC[2K, ESC[?25l, etc.
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b\[[?][0-9;]*[A-Za-z]')


def _clean_cli_output(raw: str) -> str:
    """
    Strip ANSI colour/cursor codes and collapse the live-spinner frames
    that Rich emits during progress bars (hundreds of [2K-terminated lines)
    into a single summary line so the report stays readable.
    """
    # 1. Strip all ANSI escape sequences
    text = _ANSI_RE.sub('', raw)

    cleaned_lines = []
    prev_was_spinner = False

    for line in text.splitlines():
        stripped = line.strip()

        # Rich Live progress bar: lines ending in \r or containing [2K after
        # stripping ANSI — now they just look like repeated "⚡  ░░░ Xm Ys remaining"
        # Detect spinner lines: contain the progress characters or are very long
        # repeated status lines from the drain/taint/pod-kill progress bar.
        is_spinner = (
            # Progress bar lines: "⚡  ███░░░  1m 40s remaining | pods: 3/3 Running"
            ('remaining' in stripped and len(stripped) > 40)
            # Drain/taint waiting spinner: "⚡  Draining node X..." repeated many times
            or (stripped.startswith('⚡') and stripped.endswith('...') and len(stripped) > 10)
            # Pod kill progress: "⚡  Starting experiment..."
            or (stripped.startswith('⚡') and 'experiment' in stripped.lower() and stripped.endswith('...'))
            # Cursor control leftovers
            or stripped.startswith('[?25')
            or stripped == '[1A'
        )

        if is_spinner:
            if not prev_was_spinner:
                cleaned_lines.append('  [live progress — see validation logs for full timeline]')
            prev_was_spinner = True
            continue

        prev_was_spinner = False

        # Skip blank lines that are artefacts of stripping (keep intentional blanks)
        if stripped == '' and cleaned_lines and cleaned_lines[-1] == '':
            continue

        cleaned_lines.append(line.rstrip())

    return '\n'.join(cleaned_lines)


def _extract_impact_summary(cleaned_cli_output: str) -> list[str]:
    """
    Extract the during-experiment impact block for node CPU/memory stress runs so
    the campaign report surfaces it prominently ahead of the full CLI transcript.
    """
    if not cleaned_cli_output:
        return []

    lines = cleaned_cli_output.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == "During-experiment impact observed:":
            start = idx + 1
            break

    if start is None:
        return []

    summary = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            if summary:
                break
            continue
        if stripped in {
            "Node health:",
            "Node health (post-experiment):",
            "Pod restart delta:",
            "Deployment readiness:",
            "Pod Health Comparison:",
        }:
            break
        summary.append(line.rstrip())

    return summary

def generate_report(campaign, *, show_summary=True):
    """
    Generate ChaosForge Campaign Execution Report.
    """

    REPORTS_DIR.mkdir(exist_ok=True)

    configured_timezone = getattr(campaign, "report_timezone", None)
    timezone_id = (
        configured_timezone
        if isinstance(configured_timezone, str) and configured_timezone
        else get_timezone_id()
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    report_file = REPORTS_DIR / f"campaign-report-{timestamp}.txt"

    lines = []

    #
    # ============================================================
    # Header
    # ============================================================
    #

    lines.append("=" * 70)
    lines.append("                 CHAOSFORGE EXECUTION REPORT")
    lines.append("=" * 70)

    lines.append(f"Campaign : {campaign.name}")
    lines.append(f"ChaosForge Version : {chaosforge_version()}")

    if hasattr(campaign, "start_time"):
        lines.append(f"Started  : {format_report_time(campaign.start_time, timezone_id)}")

    if hasattr(campaign, "end_time"):
        lines.append(f"Finished : {format_report_time(campaign.end_time, timezone_id)}")

    if hasattr(campaign, "duration"):
        lines.append(f"Total Duration : {campaign.duration:.1f} sec")

    lines.append("")
    lines.append("-" * 70)

    #
    # Table Header
    #
    lines.append(f"{'No':<4}{'Service':<25}{'Experiment':<35}{'Execution Status'}")

    lines.append("-" * 70)

    success = 0
    warnings = 0
    failed = 0
    skipped = 0

    #
    # Experiment Results
    #
    for index, experiment in enumerate(campaign.experiments, start=1):
        status = experiment.status.upper()

        service = display_name(experiment.service.lower())

        lines.append(f"{index:<4}{service:<25}{experiment.name:<35}{status}")

        if status == "SUCCESS":
            success += 1
        elif status == "SUCCESS_WITH_WARNINGS":
            success += 1
            warnings += 1
        elif status == "SKIPPED":
            skipped += 1
        else:
            failed += 1

    lines.append("-" * 70)

    # Detailed CLI output per experiment (pre/during/post checks + full run log)
    lines.append("")
    lines.append("=" * 70)
    lines.append("  EXPERIMENT EXECUTION DETAILS")
    lines.append("=" * 70)

    for index, experiment in enumerate(campaign.experiments, start=1):
        lines.append("")
        lines.append(f"[{index}] {experiment.name}  —  {experiment.status.upper()}")
        lines.append("-" * 70)
        raw_error_message = getattr(experiment, "error_message", "")
        error_message = raw_error_message.strip() if isinstance(raw_error_message, str) else ""
        if error_message:
            lines.append(f"Failure Details: {error_message}")
            lines.append("")
        cli_output = getattr(experiment, "cli_output", None)
        if isinstance(cli_output, str) and cli_output:
            cleaned_output = _clean_cli_output(cli_output)
            impact_summary = _extract_impact_summary(cleaned_output)
            if impact_summary:
                lines.append("During-Experiment Impact Summary")
                lines.append("~" * 35)
                lines.extend(impact_summary)
                lines.append("")
            lines.append(cleaned_output)
        else:
            lines.append("  (no CLI output captured)")
        lines.append("")

    lines.append(f"Total Experiments : {len(campaign.experiments)}")

    lines.append(f"Successful        : {success}")

    lines.append(f"With Warnings     : {warnings}")

    lines.append(f"Failed            : {failed}")

    lines.append(f"Skipped           : {skipped}")

    if failed == 0:
        overall = "SUCCESS_WITH_WARNINGS" if warnings else "SUCCESS"
    elif success == 0:
        overall = "FAILED"
    else:
        overall = "PARTIAL SUCCESS"

    lines.append("")
    lines.append("=" * 70)
    lines.append(f"Campaign Result : {overall}")
    lines.append("=" * 70)

    lines.append("")
    lines.append("Post-Execution Validation Checklist")
    lines.append("-" * 70)

    lines.append("Chaos experiment execution has completed.")

    lines.append("")

    lines.append(
        "Use the following execution window when reviewing monitoring and application telemetry:"
    )

    lines.append("")

    if hasattr(campaign, "start_time"):
        lines.append(f"Start Time : {format_report_time(campaign.start_time, timezone_id)}")

    if hasattr(campaign, "end_time"):
        lines.append(f"Finish Time: {format_report_time(campaign.end_time, timezone_id)}")

    lines.append("")

    lines.append("→ Review Datadog Metrics")
    lines.append("→ Review CloudWatch Metrics")
    lines.append("→ Review CloudWatch Logs")
    lines.append("→ Review Application Logs")
    lines.append("→ Review Application Traces")
    lines.append("→ Verify Monitoring Dashboards")
    lines.append("→ Validate Application Behaviour")
    lines.append("→ Confirm Service Recovery")
    lines.append("→ Analyze Blast Radius")

    report = "\n".join(lines)

    #
    # Save Report
    #
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    #
    # Show Rich Summary
    #
    if show_summary:
        show_report_summary(campaign, success, failed, overall, report_file)

    return report_file
