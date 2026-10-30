from unittest.mock import patch

import pytest

from chaosforge.interfaces.cli.interactive.azure_aks_menu import aks_experiment_menu
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu


@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.prompt")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.menu")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.section")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.console.print")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_service.add_aks_experiment")
@patch("chaosforge.application.metadata.get_experiments")
def test_aks_menu_selects_valid_experiment(
    mock_get_experiments,
    mock_add_experiment,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
):
    mock_get_experiments.return_value = [
        {"id": "aks-pod-kill", "name": "Pod Kill"},
        {"id": "aks-network-delay", "name": "Network Delay"},
    ]
    mock_prompt.side_effect = ["2", "0"]

    aks_experiment_menu()

    mock_add_experiment.assert_called_once_with("aks-network-delay")
    rows = mock_menu.call_args.args[1]
    assert [row[0] for row in rows] == [1, 2, 0, "M"]
    assert all("[Chaos Studio]" in row[1] for row in rows[:2])


@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.prompt")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.menu")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.section")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.console.print")
@patch("chaosforge.application.metadata.get_experiments", return_value=[])
def test_aks_menu_back(
    mock_get_experiments,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
):
    mock_prompt.return_value = "0"

    aks_experiment_menu()


@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.prompt")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.menu")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.section")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.console.print")
@patch("chaosforge.application.metadata.get_experiments", return_value=[])
def test_aks_menu_main_menu(
    mock_get_experiments,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
):
    mock_prompt.return_value = "m"

    with pytest.raises(BackToMainMenu):
        aks_experiment_menu()


@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.error")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.prompt")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.menu")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.section")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_menu.console.print")
@patch("chaosforge.interfaces.cli.interactive.azure_aks_service.add_aks_experiment")
@patch("chaosforge.application.metadata.get_experiments")
def test_aks_menu_reprompts_on_invalid_selection(
    mock_get_experiments,
    mock_add_experiment,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
    mock_error,
):
    mock_get_experiments.return_value = [{"id": "aks-pod-kill", "name": "Pod Kill"}]
    mock_prompt.side_effect = ["9", "", "0"]

    aks_experiment_menu()

    mock_error.assert_called_once_with("Invalid Selection")
    mock_add_experiment.assert_not_called()
