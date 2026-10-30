from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from chaosforge.application.services.user_settings import get_timezone_id
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.reporting.time_utils import format_report_time


def show_report_summary(campaign, success, failed, overall, report_file):
    timezone_id = get_timezone_id()

    table = Table(show_header=False, box=None, expand=True, padding=(0, 2))

    table.add_column(style="bold bright_cyan", width=20)

    table.add_column(style="white")

    table.add_row("Campaign", campaign.name)
    table.add_row("Experiments", str(len(campaign.experiments)))
    table.add_row("Successful", f"[green]{success}[/green]")
    table.add_row("Failed", f"[red]{failed}[/red]")
    table.add_row("Total Duration", f"{campaign.duration:.1f} sec")

    if overall == "SUCCESS":
        result = "[bold green]✔ SUCCESS[/bold green]"
        border = "green"
    elif overall == "FAILED":
        result = "[bold red]✖ FAILED[/bold red]"
        border = "red"
    else:
        result = "[bold yellow]⚠ PARTIAL SUCCESS[/bold yellow]"
        border = "yellow"

    table.add_row("Overall Result", result)
    table.add_row("Report", f"[cyan]{report_file}[/cyan]")

    console.print()

    console.print(
        Panel(
            table,
            title="[bold green]Mission Summary[/bold green]",
            border_style=border,
            padding=(1, 2),
            expand=True,
        )
    )

    console.print()

    guidance = Text()
    guidance.append(
        "Use the following execution window when reviewing:\n\n", style="bold yellow"
    )

    guidance.append(
        f"Start Time : {format_report_time(campaign.start_time, timezone_id)}\n", style="cyan"
    )

    guidance.append(
        f"Finish Time: {format_report_time(campaign.end_time, timezone_id)}\n\n", style="cyan"
    )

    guidance.append("Recommended Validation\n", style="bold green")

    checks = [
        "Review Datadog Metrics",
        "Review CloudWatch Metrics",
        "Review CloudWatch Logs",
        "Review Application Logs",
        "Review Application Traces",
        "Verify Monitoring Dashboards",
        "Validate Application Behaviour",
        "Confirm Service Recovery",
        "Analyze Blast Radius",
    ]

    for item in checks:
        guidance.append(f"→ {item}\n", style="white")

    console.print(
        Panel(
            guidance,
            title="[bold yellow]⚠ Operational Guidance[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
            expand=True,
        )
    )

    console.print()

    console.print(
        f"[bold green]✔ Report saved:[/bold green] [cyan]{report_file}[/cyan]"
    )

    console.print()
