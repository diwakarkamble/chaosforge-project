from rich.style import Style
from rich.theme import Theme

from chaosforge.interfaces.cli.interactive.ui.theme import chaos_theme


def test_theme_instance():
    assert isinstance(chaos_theme, Theme)


def test_theme_contains_expected_styles():
    expected_keys = {
        "title",
        "header",
        "panel",
        "success",
        "error",
        "warning",
        "info",
        "menu",
        "option",
        "highlight",
        "value",
        "muted",
        "pending",
        "running",
        "completed",
        "failed",
    }

    for key in expected_keys:
        assert key in chaos_theme.styles
        assert isinstance(chaos_theme.styles[key], Style)


def test_theme_contains_all_custom_keys():
    expected_keys = {
        "title",
        "header",
        "panel",
        "success",
        "error",
        "warning",
        "info",
        "menu",
        "option",
        "highlight",
        "value",
        "muted",
        "pending",
        "running",
        "completed",
        "failed",
    }

    assert expected_keys.issubset(set(chaos_theme.styles.keys()))
