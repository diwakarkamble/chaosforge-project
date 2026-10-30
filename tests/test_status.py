from unittest.mock import patch

from chaosforge.interfaces.cli.interactive.ui.status import (
    completed,
    error,
    failed,
    info,
    pending,
    running,
    success,
    warning,
)


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_success(mock_print):
    success("Done")

    mock_print.assert_called_once_with("✔ Done", style="success")


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_error(mock_print):
    error("Failed")

    mock_print.assert_called_once_with("✖ Failed", style="error")


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_warning(mock_print):
    warning("Warning")

    mock_print.assert_called_once_with("⚠ Warning", style="warning")


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_info(mock_print):
    info("Information")

    mock_print.assert_called_once_with("ℹ Information", style="info")


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_pending(mock_print):
    pending("Pending")

    mock_print.assert_called_once_with("◉ Pending", style="pending")


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_running(mock_print):
    running("Running")

    mock_print.assert_called_once_with("⟳ Running", style="running")


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_completed(mock_print):
    completed("Completed")

    mock_print.assert_called_once_with("✔ Completed", style="completed")


@patch("chaosforge.interfaces.cli.interactive.ui.status.console.print")
def test_failed(mock_print):
    failed("Failed")

    mock_print.assert_called_once_with("✖ Failed", style="failed")
