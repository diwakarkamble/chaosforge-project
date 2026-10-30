from contextlib import contextmanager

from rich.live import Live

from chaosforge.interfaces.cli.interactive.ui.console import console


@contextmanager
def live(renderable, refresh_per_second=4):

    with Live(
        renderable,
        console=console,
        refresh_per_second=refresh_per_second,
        transient=False,
        screen=False,
        auto_refresh=True,
    ) as live_display:
        yield live_display
