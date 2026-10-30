from chaosforge.application.experiment_presentation import present_experiment, rich_engine_label
from chaosforge.application.metadata import get_experiments
from chaosforge.application.services.registry import execute_experiment
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import section
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.interfaces.cli.interactive.ui.status import error
from chaosforge.interfaces.cli.interactive.ui.tables import menu
from chaosforge.providers.aws.fis.catalog import FISCatalog


def experiment_menu(service):

    catalog = FISCatalog()

    while True:
        chaos_experiments = get_experiments(service)

        console.print()

        section(f"AWS {service.title()}")

        menu_mapping = {}

        option = 1

        experiment_rows = []

        for experiment in chaos_experiments:
            presented = present_experiment(service, experiment)
            experiment_rows.append((option, _labelled_name(presented)))
            menu_mapping[str(option)] = {"id": experiment["id"], "prefill": None}
            option += 1

        fis_options = catalog.get_menu_items(service)
        for item in fis_options:
            presented = present_experiment(
                "fis",
                {
                    "id": item.get("experiment_id", item["title"]),
                    "name": item["title"].replace(" (AWS FIS)", ""),
                },
            )
            experiment_rows.append((option, _labelled_name(presented)))
            menu_mapping[str(option)] = {"id": "fis-create-experiment", "prefill": item["prefill"]}
            option += 1

        if service.lower() == "eks":
            chaos_mesh_experiments = get_experiments(
                "chaos_mesh"
            )
            for experiment in chaos_mesh_experiments:
                presented = present_experiment("chaos_mesh", experiment)
                experiment_rows.append((option, _labelled_name(presented)))
                menu_mapping[str(option)] = {"id": experiment["id"], "prefill": None}
                option += 1

        if experiment_rows:
            console.print()
        menu("", experiment_rows + [(0, "Back"), ("M", "Main Menu")])

        choice = prompt("Select Experiment").strip().lower()

        if choice == "0":
            return

        if choice == "m":
            raise BackToMainMenu

        experiment = menu_mapping.get(choice)

        if experiment is None:
            error("Invalid Selection")

            prompt("Press Enter")

            continue

        execute_experiment(
            experiment["id"],
            prefill=experiment["prefill"],
        )


def _labelled_name(experiment):
    return f"{experiment['name']} {rich_engine_label(experiment)}"
