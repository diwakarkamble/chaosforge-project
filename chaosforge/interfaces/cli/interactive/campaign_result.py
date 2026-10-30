from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import title
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.models import Campaign
from chaosforge.models.outcome import is_failure, is_success, is_warning_success


def show_campaign_result_menu(campaign: Campaign):

    success = len([e for e in campaign.experiments if is_success(e.status)])
    warnings = len([e for e in campaign.experiments if is_warning_success(e.status)])

    failed = len([e for e in campaign.experiments if is_failure(e.status)])

    while True:
        title("Campaign Result")

        console.print(f"[bold cyan]Campaign[/bold cyan] : {campaign.name}")

        console.print(
            f"[bold cyan]Total Experiments[/bold cyan] : {len(campaign.experiments)}"
        )

        console.print(f"[green]SUCCESS[/green] : {success}")

        console.print(f"[yellow]SUCCESS WITH WARNINGS[/yellow] : {warnings}")

        console.print(f"[red]FAILED[/red] : {failed}")

        for experiment in campaign.experiments:
            console.print(f"  - {experiment.name}: {experiment.status}")

        console.print()

        if failed:
            console.print("1. Retry Failed Experiments")

            console.print("2. Edit Failed Experiments")

        console.print("0. Return to Main Menu")

        console.print()

        choice = prompt("Enter Choice").strip()

        if choice == "0":
            return

        if choice == "1" and failed:
            return "retry"

        if choice == "2" and failed:
            return "edit"
