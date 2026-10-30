from unittest.mock import patch

from chaosforge.interfaces.cli.interactive.region_selector import RegionSelector

# ----------------------------------------------------------
# Valid Selection
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.region_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.region_selector.console")
@patch("chaosforge.interfaces.cli.interactive.region_selector.prompt")
def test_select_region_success(
    mock_prompt,
    mock_console,
    mock_menu,
):

    mock_prompt.return_value = "1"

    selector = RegionSelector()

    region = selector.select()

    assert region == "ap-south-1"

    mock_menu.assert_called_once()


# ----------------------------------------------------------
# Invalid then Valid
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.region_selector.error")
@patch("chaosforge.interfaces.cli.interactive.region_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.region_selector.console")
@patch("chaosforge.interfaces.cli.interactive.region_selector.prompt")
def test_select_region_invalid_then_valid(
    mock_prompt,
    mock_console,
    mock_menu,
    mock_error,
):

    mock_prompt.side_effect = [
        "abc",
        "3",
    ]

    selector = RegionSelector()

    region = selector.select()

    assert region == "eu-west-1"

    mock_error.assert_called_once_with("Invalid Selection")


# ----------------------------------------------------------
# Invalid Index then Valid
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.region_selector.error")
@patch("chaosforge.interfaces.cli.interactive.region_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.region_selector.console")
@patch("chaosforge.interfaces.cli.interactive.region_selector.prompt")
def test_select_region_index_error(
    mock_prompt,
    mock_console,
    mock_menu,
    mock_error,
):

    mock_prompt.side_effect = [
        "100",
        "7",
    ]

    selector = RegionSelector()

    region = selector.select()

    assert region == "cn-northwest-1"

    mock_error.assert_called_once_with("Invalid Selection")


# ----------------------------------------------------------
# Manual Region Entry
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.region_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.region_selector.console")
@patch("chaosforge.interfaces.cli.interactive.region_selector.prompt")
def test_select_region_manual(
    mock_prompt,
    mock_console,
    mock_menu,
):

    mock_prompt.side_effect = [
        "8",
        "ap-south-2",
    ]

    selector = RegionSelector()

    region = selector.select()

    assert region == "ap-south-2"


# ----------------------------------------------------------
# Exit
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.region_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.region_selector.console")
@patch("chaosforge.interfaces.cli.interactive.region_selector.prompt")
def test_select_region_exit(
    mock_prompt,
    mock_console,
    mock_menu,
):

    mock_prompt.return_value = "0"

    selector = RegionSelector()

    try:
        selector.select()
        assert False, "Expected SystemExit"
    except SystemExit:
        pass


@patch("chaosforge.interfaces.cli.interactive.region_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.region_selector.console")
@patch("chaosforge.interfaces.cli.interactive.region_selector.prompt")
def test_settings_region_selector_supports_back_and_main_menu(
    mock_prompt,
    mock_console,
    mock_menu,
):
    selector = RegionSelector()

    mock_prompt.return_value = "0"
    assert selector.select(navigation=True) is None

    mock_prompt.return_value = "m"
    assert selector.select(navigation=True) == "__main_menu__"
    assert ("M", "Main Menu") in mock_menu.call_args.args[1]

@patch("chaosforge.interfaces.cli.interactive.region_selector.error")
@patch("chaosforge.interfaces.cli.interactive.region_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.region_selector.console")
@patch("chaosforge.interfaces.cli.interactive.region_selector.prompt")
def test_select_manual_region_rejects_empty_then_accepts(
    mock_prompt,
    mock_console,
    mock_menu,
    mock_error,
):
    mock_prompt.side_effect = [
        "8",
        "",
        "ap-south-1",
    ]

    selector = RegionSelector()

    result = selector.select()

    assert result == "ap-south-1"
    mock_error.assert_called_once_with(
        "Region cannot be empty"
    )
