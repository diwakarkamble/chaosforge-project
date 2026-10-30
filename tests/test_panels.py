from unittest.mock import patch

from rich.rule import Rule

from chaosforge.interfaces.cli.interactive.ui.panels import (
    section,
    title,
)


@patch("chaosforge.interfaces.cli.interactive.ui.panels.console.print")
def test_title(mock_print):
    title("ChaosForge")

    assert mock_print.call_count == 3

    mock_print.assert_any_call()

    rule = mock_print.call_args_list[1].args[0]

    assert isinstance(rule, Rule)

    assert rule.style == "bright_blue"

    assert "CHAOSFORGE" in str(rule.title)


@patch("chaosforge.interfaces.cli.interactive.ui.panels.console.print")
def test_section(mock_print):
    section("AWS Lambda")

    assert mock_print.call_count == 3

    mock_print.assert_any_call()

    rule = mock_print.call_args_list[1].args[0]

    assert isinstance(rule, Rule)

    assert rule.style == "bright_black"

    assert "AWS Lambda" in str(rule.title)
