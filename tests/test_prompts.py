from unittest.mock import patch

from chaosforge.interfaces.cli.interactive.ui.prompts import (
    confirm,
    pause,
    prompt,
)


@patch("chaosforge.interfaces.cli.interactive.ui.prompts.console.input")
def test_prompt(mock_input):
    mock_input.return_value = "eu-central-1"

    result = prompt("AWS Region")

    assert result == "eu-central-1"

    mock_input.assert_called_once_with(
        "\n[bold bright_cyan]❯[/bold bright_cyan] [bold white]AWS Region[/bold white]: "
    )


@patch("chaosforge.interfaces.cli.interactive.ui.prompts.console.input")
def test_confirm_yes(mock_input):
    mock_input.return_value = " Y "

    result = confirm("Continue")

    assert result == "y"

    mock_input.assert_called_once_with(
        "\n[bold yellow]❯[/bold yellow] "
        "[bold white]Continue[/bold white] "
        "[bright_black](Y/N)[/bright_black]: "
    )


@patch("chaosforge.interfaces.cli.interactive.ui.prompts.console.input")
def test_confirm_no(mock_input):
    mock_input.return_value = "N"

    result = confirm("Continue")

    assert result == "n"


@patch("chaosforge.interfaces.cli.interactive.ui.prompts.console.input")
def test_pause(mock_input):
    pause()

    mock_input.assert_called_once_with(
        "\n[bright_black]────────────────────────────────────────[/bright_black]\n"
        "[bright_black]Press Enter to continue...[/bright_black]"
    )
