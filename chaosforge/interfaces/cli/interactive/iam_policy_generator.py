from rich.console import Console

from chaosforge.application.services.permissions import PermissionReportService
from chaosforge.interfaces.cli.interactive.ui.prompts import pause, prompt
from chaosforge.interfaces.cli.interactive.ui.status import warning

console = Console()
permission_reports = PermissionReportService()


def display_required_policies(campaign):
    """Compatibility wrapper around the shared permission report service."""
    console.print(permission_reports.render_terminal(campaign))


def confirm_required_policies(campaign):
    """
    Ensure the required IAM Policy has been attached
    before executing the campaign.
    """

    while True:
        console.print()

        console.print(
            "[bold yellow]Before executing this campaign, ensure the generated permission plan has been applied.[/bold yellow]"
        )

        console.print()

        console.print(
            "[bold cyan]Have you reviewed the required permissions?[/bold cyan]"
        )

        console.print()

        console.print("[green]Y[/green]  Yes, Continue")

        console.print("[yellow]V[/yellow]  View Permission Report Again")

        console.print("[red]N[/red]  No, Cancel Execution")

        console.print()

        choice = prompt("Choice").strip().lower()

        #
        # Continue
        #

        if choice == "y":
            return True

        #
        # Cancel
        #

        elif choice == "n":
            return False

        #
        # View IAM Policy
        #

        elif choice == "v":
            display_required_policies(campaign)

            pause()

        #
        # Invalid Selection
        #

        else:
            warning("Invalid Selection")

            pause()
