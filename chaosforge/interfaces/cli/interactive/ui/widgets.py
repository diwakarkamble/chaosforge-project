from rich.align import Align
from rich.columns import Columns
from rich.panel import Panel

from chaosforge.interfaces.cli.interactive.ui.console import console


def info_box(title, message):

    console.print(
        Panel(
            Align.left(message),
            title=f"[bold cyan]{title}[/bold cyan]",
            border_style="bright_blue",
            expand=True,
        )
    )


def success_box(title, message):

    console.print(
        Panel(
            Align.left(message),
            title=f"[bold green]{title}[/bold green]",
            border_style="green",
            expand=True,
        )
    )


def warning_box(title, message):

    console.print(
        Panel(
            Align.left(message),
            title=f"[bold yellow]{title}[/bold yellow]",
            border_style="yellow",
            expand=True,
        )
    )


def error_box(title, message):

    console.print(
        Panel(
            Align.left(message),
            title=f"[bold red]{title}[/bold red]",
            border_style="red",
            expand=True,
        )
    )


def stat_cards(stats):

    cards = []

    for title, value in stats.items():
        cards.append(
            Panel(
                Align.center(f"[bold white]{value}[/bold white]"),
                title=f"[cyan]{title}[/cyan]",
                border_style="bright_blue",
                width=22,
            )
        )

    console.print(Columns(cards, expand=True))


def feature_card(title, description, color="bright_blue"):

    console.print(
        Panel(
            description, title=f"[bold]{title}[/bold]", border_style=color, expand=True
        )
    )
