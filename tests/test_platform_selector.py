from unittest.mock import patch

import pytest

from chaosforge.interfaces.cli.interactive.platform_selector import PlatformSelector


def test_select_aws():
    selector = PlatformSelector()

    with patch(
        "chaosforge.interfaces.cli.interactive.platform_selector.prompt",
        return_value="1",
    ):
        result = selector.select()

    assert result == "aws"


def test_select_azure():
    selector = PlatformSelector()

    with (
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.prompt",
            side_effect=["2"],
        ),
        patch.object(
            selector,
            "_load_cached_azure_context",
        ) as mock_load_cache,
    ):
        result = selector.select()

    mock_load_cache.assert_called_once()
    assert result == "azure"


def test_removed_gcp_option_is_rejected():
    selector = PlatformSelector()

    with (
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.prompt",
            side_effect=["3", "1"],
        ),
        patch("chaosforge.interfaces.cli.interactive.platform_selector.error") as mock_error,
    ):
        result = selector.select()

    mock_error.assert_called_once_with("Invalid Choice")
    assert result == "aws"


def test_select_invalid_choice():
    selector = PlatformSelector()

    with (
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.prompt",
            side_effect=["invalid", "1"],
        ),
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.error",
        ) as mock_error,
    ):
        result = selector.select()

    mock_error.assert_called_once_with("Invalid Choice")
    assert result == "aws"


def test_select_exit():
    selector = PlatformSelector()

    with (
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.prompt",
            return_value="0",
        ),
        pytest.raises(SystemExit),
    ):
        selector.select()


def test_show_coming_soon():
    selector = PlatformSelector()

    with (
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.title",
        ) as mock_title,
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.console",
        ) as mock_console,
        patch(
            "chaosforge.interfaces.cli.interactive.platform_selector.prompt",
            return_value="",
        ) as mock_prompt,
    ):
        selector.show_coming_soon("Microsoft Azure")

    mock_title.assert_called_once_with("Microsoft Azure")
    mock_prompt.assert_called_once_with("Press Enter to return")
    assert mock_console.print.called
