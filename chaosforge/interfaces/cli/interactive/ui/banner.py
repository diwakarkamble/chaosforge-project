from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from chaosforge.interfaces.cli.interactive.ui.console import console

VERSION = "1.0"


def print_banner():
    banner = Group(
        Align.center(Text("CHAOSFORGE PLATFORM", style="bold bright_cyan")),
        Align.center(
            Text("Forging Resilient Systems Through Controlled Chaos", style="white")
        ),
    )

    console.print(
        Panel(
            banner,
            title="[bold white]Chaos Engineering Platform[/bold white]",
            subtitle=f"[bright_black]{VERSION}[/bright_black]",
            border_style="bright_blue",
            padding=(1, 2),
            expand=True,
        )
    )
