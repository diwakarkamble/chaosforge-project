from rich.console import Console

from chaosforge.interfaces.cli.interactive.ui.console import console


def test_console_instance():
    assert isinstance(console, Console)


def test_console_uses_chaos_theme():
    style = console.get_style("success")

    assert style.bold is True
    assert style.color is not None


def test_console_options():
    assert console._highlight is False

    assert console.soft_wrap is True

    assert console.is_terminal is True


def test_console_uses_windows_safe_legacy_mode_when_needed():
    import os

    assert console.legacy_windows is (os.name == "nt")
