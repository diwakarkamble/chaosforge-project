from rich.rule import Rule

from chaosforge.interfaces.cli.interactive.ui.console import console


def title(text):

    console.print()

    console.print(
        Rule(
            f"[bold bright_cyan]{text.upper()}[/bold bright_cyan]", style="bright_blue"
        )
    )

    console.print()


def section(text):

    console.print()

    console.print(Rule(f"[bold yellow]{text}[/bold yellow]", style="bright_black"))

    console.print()
