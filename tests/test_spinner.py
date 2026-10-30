from unittest.mock import MagicMock, patch

from chaosforge.interfaces.cli.interactive.ui.spinner import spinner


@patch("chaosforge.interfaces.cli.interactive.ui.spinner.console.status")
def test_spinner(mock_status):
    mock_context = MagicMock()

    mock_status.return_value = mock_context

    with spinner("Loading..."):
        pass

    mock_status.assert_called_once_with(
        "[bold cyan]Loading...[/bold cyan]", spinner="dots"
    )

    mock_context.__enter__.assert_called_once()

    mock_context.__exit__.assert_called_once()
