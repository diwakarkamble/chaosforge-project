from chaosforge.application.metadata import get_experiments
from chaosforge.application.services.registry import execute_experiment
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu


def run_experiment_menu(title, experiments):
    """
    Display experiment list and execute selected experiment.
    """

    while True:
        print()
        print("=" * 70)
        print(f"                     {title}")
        print("=" * 70)
        print()

        menu_mapping = {}

        option = 1

        for exp in experiments:
            print(f"{option}. {exp['name']}")

            menu_mapping[str(option)] = exp

            option += 1

        print()
        print("-" * 70)
        print("0. Back")
        print("M. Main Menu")
        print()

        choice = input("Select Experiment : ").strip().lower()

        if choice == "0":
            return

        if choice == "m":
            raise BackToMainMenu

        experiment = menu_mapping.get(choice)

        if experiment is None:
            print("\nInvalid Choice")

            input("\nPress Enter...")

            continue

        execute_experiment(experiment["id"])


def experiment_menu(service):

    while True:
        #
        # Load Service Chaos Toolkit experiments
        #

        chaos_experiments = get_experiments(service)

        #
        # Load Shared AWS FIS experiments
        #

        fis_experiments = get_experiments("fis")

        print()
        print("=" * 70)
        print(f"                     {service.upper()}")
        print("=" * 70)
        print()

        option_map = {}

        option = 1

        #
        # Chaos Toolkit
        #

        if chaos_experiments:
            print(f"{option}. Chaos Toolkit")

            option_map[str(option)] = ("Chaos Toolkit", chaos_experiments)

            option += 1

        #
        # AWS FIS
        #

        if fis_experiments:
            print(f"{option}. AWS FIS")

            option_map[str(option)] = ("AWS Fault Injection Simulator", fis_experiments)

            option += 1

        print("0. Back")
        print("M. Main Menu")
        print()

        choice = input("Enter Choice : ").strip().lower()

        if choice == "0":
            return

        if choice == "m":
            raise BackToMainMenu

        if choice not in option_map:
            print("\nInvalid Choice")

            input("\nPress Enter...")

            continue

        title, experiments = option_map[choice]

        run_experiment_menu(title, experiments)
