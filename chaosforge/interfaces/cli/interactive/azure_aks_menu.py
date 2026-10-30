"""Interactive Azure AKS experiment selection."""

from chaosforge.application.experiment_presentation import present_experiment, rich_engine_label
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import section
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.interfaces.cli.interactive.ui.status import error
from chaosforge.interfaces.cli.interactive.ui.tables import menu


def aks_experiment_menu():
    from chaosforge.application.metadata import get_experiments
    from chaosforge.interfaces.cli.interactive.azure_aks_service import (
        add_aks_experiment,
    )

    while True:
        experiments = get_experiments("aks")

        console.print()
        section("Azure AKS Chaos")
        console.print()

        menu_mapping = {}
        option = 1
        rows = []
        for metadata in experiments:
            presented = present_experiment("aks", metadata)
            rows.append((option, f"{metadata['name']} {rich_engine_label(presented)}"))
            menu_mapping[str(option)] = metadata["id"]
            option += 1

        menu("", rows + [(0, "Back"), ("M", "Main Menu")])
        console.print()

        choice = prompt("Select Experiment").strip().lower()

        if choice == "0":
            return

        if choice == "m":
            raise BackToMainMenu

        exp_id = menu_mapping.get(choice)

        if exp_id is None:
            error("Invalid Selection")
            prompt("Press Enter")
            continue

        add_aks_experiment(exp_id)
