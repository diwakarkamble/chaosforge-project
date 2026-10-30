import os

from chaosforge.interfaces.cli.interactive.menu import experiment_menu


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def dynamodb_menu():

    clear_screen()

    experiment_menu("dynamodb")
