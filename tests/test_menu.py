from unittest.mock import patch

import pytest

from chaosforge.interfaces.cli.interactive.menu import (
    experiment_menu,
    run_experiment_menu,
)
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu

#
# run_experiment_menu
#


@patch("chaosforge.interfaces.cli.interactive.menu.execute_experiment")
@patch("builtins.input")
def test_run_experiment_execute(
    mock_input,
    mock_execute,
):
    mock_input.side_effect = [
        "1",
        "0",
    ]

    experiments = [
        {
            "id": "exp1",
            "name": "Experiment 1",
        }
    ]

    run_experiment_menu(
        "Test",
        experiments,
    )

    mock_execute.assert_called_once_with("exp1")


@patch("builtins.input")
def test_run_experiment_back(
    mock_input,
):
    mock_input.return_value = "0"

    run_experiment_menu(
        "Test",
        [],
    )


@patch("builtins.input")
def test_run_experiment_main_menu(
    mock_input,
):
    mock_input.return_value = "m"

    with pytest.raises(BackToMainMenu):
        run_experiment_menu(
            "Test",
            [],
        )


@patch("chaosforge.interfaces.cli.interactive.menu.execute_experiment")
@patch("builtins.input")
def test_run_experiment_invalid_choice(
    mock_input,
    mock_execute,
):
    mock_input.side_effect = [
        "9",
        "",
        "0",
    ]

    run_experiment_menu(
        "Test",
        [
            {
                "id": "exp1",
                "name": "Experiment 1",
            }
        ],
    )

    mock_execute.assert_not_called()


#
# experiment_menu
#


@patch("chaosforge.interfaces.cli.interactive.menu.run_experiment_menu")
@patch("chaosforge.interfaces.cli.interactive.menu.get_experiments")
@patch("builtins.input")
def test_experiment_menu_chaos_toolkit(
    mock_input,
    mock_get,
    mock_run,
):
    mock_get.side_effect = [
        [
            {
                "id": "exp1",
                "name": "Memory",
            }
        ],
        [],
        [
            {
                "id": "exp1",
                "name": "Memory",
            }
        ],
        [],
    ]

    mock_input.side_effect = [
        "1",
        "0",
    ]

    experiment_menu("lambda")

    mock_run.assert_called_once_with(
        "Chaos Toolkit",
        [
            {
                "id": "exp1",
                "name": "Memory",
            }
        ],
    )


@patch("chaosforge.interfaces.cli.interactive.menu.run_experiment_menu")
@patch("chaosforge.interfaces.cli.interactive.menu.get_experiments")
@patch("builtins.input")
def test_experiment_menu_fis(
    mock_input,
    mock_get,
    mock_run,
):
    mock_get.side_effect = [
        [],
        [
            {
                "id": "fis1",
                "name": "Delay",
            }
        ],
        [],
        [
            {
                "id": "fis1",
                "name": "Delay",
            }
        ],
    ]

    mock_input.side_effect = [
        "1",
        "0",
    ]

    experiment_menu("lambda")

    mock_run.assert_called_once_with(
        "AWS Fault Injection Simulator",
        [
            {
                "id": "fis1",
                "name": "Delay",
            }
        ],
    )


@patch("chaosforge.interfaces.cli.interactive.menu.get_experiments")
@patch("builtins.input")
def test_experiment_menu_back(
    mock_input,
    mock_get,
):
    mock_get.side_effect = [
        [],
        [],
    ]

    mock_input.return_value = "0"

    experiment_menu("lambda")


@patch("chaosforge.interfaces.cli.interactive.menu.get_experiments")
@patch("builtins.input")
def test_experiment_menu_main_menu(
    mock_input,
    mock_get,
):
    mock_get.side_effect = [
        [],
        [],
    ]

    mock_input.return_value = "m"

    with pytest.raises(BackToMainMenu):
        experiment_menu("lambda")


@patch("chaosforge.interfaces.cli.interactive.menu.run_experiment_menu")
@patch("chaosforge.interfaces.cli.interactive.menu.get_experiments")
@patch("builtins.input")
def test_experiment_menu_invalid_choice(
    mock_input,
    mock_get,
    mock_run,
):
    mock_get.side_effect = [
        [],
        [
            {
                "id": "fis1",
                "name": "Delay",
            }
        ],
        [],
        [
            {
                "id": "fis1",
                "name": "Delay",
            }
        ],
    ]

    mock_input.side_effect = [
        "9",
        "",
        "0",
    ]

    experiment_menu("lambda")

    mock_run.assert_not_called()
