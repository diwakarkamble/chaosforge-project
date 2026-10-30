from unittest.mock import patch

import pytest

from chaosforge.interfaces.cli.interactive.menu_flat import experiment_menu
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu


@patch("chaosforge.interfaces.cli.interactive.menu_flat.execute_experiment")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.prompt")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.menu")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.section")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.console.print")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.get_experiments")
def test_configuration_experiment(
    mock_get,
    mock_catalog,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
    mock_execute,
):
    mock_get.return_value = [
        {
            "id": "lambda-memory",
            "name": "Memory",
        }
    ]

    mock_catalog.return_value.get_menu_items.return_value = []

    mock_prompt.side_effect = ["1", "0"]

    experiment_menu("lambda")

    mock_execute.assert_called_once_with(
        "lambda-memory",
        prefill=None,
    )


@patch("chaosforge.interfaces.cli.interactive.menu_flat.execute_experiment")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.prompt")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.menu")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.section")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.console.print")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.get_experiments")
def test_fis_experiment(
    mock_get,
    mock_catalog,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
    mock_execute,
):
    mock_get.return_value = []

    mock_catalog.return_value.get_menu_items.return_value = [
        {
            "title": "Delay (AWS FIS)",
            "prefill": {
                "service_id": "lambda",
            },
        }
    ]

    mock_prompt.side_effect = ["1", "0"]

    experiment_menu("lambda")

    mock_execute.assert_called_once_with(
        "fis-create-experiment",
        prefill={"service_id": "lambda"},
    )


@patch("chaosforge.interfaces.cli.interactive.menu_flat.prompt")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.menu")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.section")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.console.print")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.get_experiments")
def test_back(
    mock_get,
    mock_catalog,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
):
    mock_get.return_value = []

    mock_catalog.return_value.get_menu_items.return_value = []

    mock_prompt.return_value = "0"

    experiment_menu("lambda")


@patch("chaosforge.interfaces.cli.interactive.menu_flat.prompt")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.menu")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.section")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.console.print")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.get_experiments")
def test_main_menu(
    mock_get,
    mock_catalog,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
):
    mock_get.return_value = []

    mock_catalog.return_value.get_menu_items.return_value = []

    mock_prompt.return_value = "m"

    with pytest.raises(BackToMainMenu):
        experiment_menu("lambda")


@patch("chaosforge.interfaces.cli.interactive.menu_flat.error")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.prompt")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.menu")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.section")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.console.print")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.get_experiments")
def test_invalid_selection(
    mock_get,
    mock_catalog,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
    mock_error,
):
    mock_get.return_value = []

    mock_catalog.return_value.get_menu_items.return_value = []

    mock_prompt.side_effect = [
        "9",
        "",
        "0",
    ]

    experiment_menu("lambda")

    mock_error.assert_called_once_with("Invalid Selection")


@patch("chaosforge.interfaces.cli.interactive.menu_flat.execute_experiment")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.prompt")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.menu")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.section")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.console.print")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.get_experiments")
def test_fis_experiment_ec2_with_experiment_id(
    mock_get,
    mock_catalog,
    mock_print,
    mock_section,
    mock_menu,
    mock_prompt,
    mock_execute,
):
    mock_get.return_value = []

    mock_catalog.return_value.get_menu_items.return_value = [
        {
            "title": "Delay (AWS FIS)",
            "prefill": {
                "service_id": "ec2",
                "experiment_id": "fis-delay",
            },
        }
    ]

    #
    # Option 1 = FIS experiment
    #

    mock_prompt.side_effect = [
        "1",
        "0",
    ]

    experiment_menu("lambda")

    mock_execute.assert_called_once_with(
        "fis-create-experiment",
        prefill={
            "service_id": "ec2",
            "experiment_id": "fis-delay",
        },
    )


@patch("chaosforge.interfaces.cli.interactive.menu_flat.execute_experiment")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.prompt", side_effect=["0"])
@patch("chaosforge.interfaces.cli.interactive.menu_flat.menu")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.section")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.console.print")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.menu_flat.get_experiments")
def test_experiment_menu_uses_inline_engine_labels_without_sectioned_rows(
    mock_get,
    mock_catalog,
    _mock_print,
    _mock_section,
    mock_menu,
    _mock_prompt,
    _mock_execute,
):
    mock_get.side_effect = [
        [{"id": "custom", "name": "Custom Experiment"}],
        [{"id": "mesh", "name": "Mesh Experiment", "engine": "Chaos Mesh"}],
    ]
    mock_catalog.return_value.get_menu_items.return_value = [
        {"title": "FIS Experiment (AWS FIS)", "experiment_id": "fis", "prefill": {}}
    ]

    experiment_menu("eks")

    rows = mock_menu.call_args_list[0].args[1]
    assert [row[0] for row in rows] == [1, 2, 3, 0, "M"]
    assert "[Chaos Toolkit]" in rows[0][1]
    assert "[FIS]" in rows[1][1]
    assert "[Chaos Mesh]" in rows[2][1]
