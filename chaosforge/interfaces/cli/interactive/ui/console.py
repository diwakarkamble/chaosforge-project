import os

from rich.console import Console

from chaosforge.common.console_encoding import configure_windows_output
from chaosforge.interfaces.cli.interactive.ui.theme import chaos_theme

configure_windows_output()

console = Console(
    theme=chaos_theme,
    highlight=False,
    soft_wrap=True,
    force_terminal=True,
    legacy_windows=os.name == "nt",
)
