from rich.box import ROUNDED
from rich.panel import Panel
from rich.table import Table

from chaosforge.interfaces.cli.interactive.ui.console import console


def render_main_menu(rows):

    table = Table(show_header=False, box=None, expand=True, padding=(0, 2))

    table.add_column(width=5, justify="left", style="bold bright_cyan")

    table.add_column(style="white")

    for number, text in rows:
        table.add_row(f"[bold bright_cyan]{number}[/bold bright_cyan]", text)

    console.print()

    console.print(
        Panel(
            table,
            title="[bold bright_cyan]Main Menu[/bold bright_cyan]",
            border_style="bright_blue",
            box=ROUNDED,
            padding=(0, 2),
            expand=True,
        )
    )

    console.print()
