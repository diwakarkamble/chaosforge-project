from contextlib import contextmanager

from chaosforge.interfaces.cli.interactive.ui.console import console


@contextmanager
def spinner(message):

    with console.status(f"[bold cyan]{message}[/bold cyan]", spinner="dots"):
        yield
