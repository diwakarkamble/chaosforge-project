from rich.panel import Panel
from rich.table import Table

from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.models.outcome import is_failure, is_success, is_warning_success


def show_campaign_start(campaign):

    table = Table(show_header=False, box=None, expand=True, padding=(0, 2))

    table.add_column(style="bold cyan", width=18)
    table.add_column(style="white")

    table.add_row("Campaign", campaign.name)
    table.add_row("Experiments", str(len(campaign.experiments)))
    table.add_row("Status", "[bold green]READY[/bold green]")

    console.print()

    console.print(
        Panel(
            table,
            title="[bold bright_cyan]Mission Execution[/bold bright_cyan]",
            border_style="bright_blue",
            expand=True,
        )
    )


def show_experiment(index, total, experiment):

    table = Table(show_header=False, box=None, expand=True, padding=(0, 2))

    table.add_column(style="bold cyan", width=18)
    table.add_column(style="white")

    table.add_row("Progress", f"{index} of {total}")
    table.add_row("Service", experiment.service)
    table.add_row("Experiment", experiment.name)
    table.add_row("Status", "[yellow]RUNNING[/yellow]")

    console.print()

    console.print(
        Panel(
            table,
            title="[bold bright_cyan]Executing Experiment[/bold bright_cyan]",
            border_style="bright_blue",
            expand=True,
        )
    )


def show_campaign_complete(campaign):

    success = sum(1 for experiment in campaign.experiments if is_success(experiment.status))
    warnings = sum(
        1 for experiment in campaign.experiments if is_warning_success(experiment.status)
    )

    failed = sum(1 for experiment in campaign.experiments if is_failure(experiment.status))

    table = Table(show_header=False, box=None, expand=True, padding=(0, 2))

    table.add_column(style="bold cyan", width=18)
    table.add_column(style="white")

    table.add_row("Campaign", campaign.name)
    table.add_row("Successful", f"[green]{success}[/green]")
    table.add_row("With Warnings", f"[yellow]{warnings}[/yellow]")
    table.add_row("Failed", f"[red]{failed}[/red]")
    table.add_row("Total Duration", f"{campaign.duration:.2f} sec")

    console.print()

    console.print(
        Panel(
            table,
            title="[bold green]MISSION COMPLETED[/bold green]",
            border_style="green",
            expand=True,
        )
    )
