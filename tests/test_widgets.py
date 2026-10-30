from unittest.mock import patch

from chaosforge.interfaces.cli.interactive.ui.widgets import (
    error_box,
    feature_card,
    info_box,
    stat_cards,
    success_box,
    warning_box,
)


def test_info_box():
    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        info_box("Info", "Test message")

    mock_console.print.assert_called_once()


def test_success_box():
    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        success_box("Success", "Operation completed")

    mock_console.print.assert_called_once()


def test_warning_box():
    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        warning_box("Warning", "Something needs attention")

    mock_console.print.assert_called_once()


def test_error_box():
    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        error_box("Error", "Operation failed")

    mock_console.print.assert_called_once()


def test_stat_cards():
    stats = {
        "Experiments": 10,
        "Success": 8,
        "Failed": 2,
    }

    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        stat_cards(stats)

    mock_console.print.assert_called_once()


def test_stat_cards_empty():
    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        stat_cards({})

    mock_console.print.assert_called_once()


def test_feature_card():
    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        feature_card(
            "AWS FIS",
            "AWS Fault Injection Service",
        )

    mock_console.print.assert_called_once()


def test_feature_card_custom_color():
    with patch("chaosforge.interfaces.cli.interactive.ui.widgets.console") as mock_console:
        feature_card(
            "Lambda",
            "Lambda chaos experiments",
            color="red",
        )

    mock_console.print.assert_called_once()
