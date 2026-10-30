"""
Generic AWS Region Selector
"""

from typing import ClassVar

from rich.panel import Panel

from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.interfaces.cli.interactive.ui.status import error
from chaosforge.interfaces.cli.interactive.ui.tables import menu


class RegionSelector:
    REGIONS: ClassVar[list[tuple[str, str]]] = [
        ("ap-south-1", "Asia Pacific (Mumbai)"),
        ("eu-central-1", "Europe (Frankfurt)"),
        ("eu-west-1", "Europe (Ireland)"),
        ("us-east-1", "US East (N. Virginia)"),
        ("us-west-1", "US West (N. California)"),
        ("cn-north-1", "China North (Beijing)"),
        ("cn-northwest-1", "China Northwest (Ningxia)"),
    ]

    def select(self, navigation=False):

        #
        # Warning Notice
        #

        console.print()

        console.print(
            Panel.fit(
                "[bold red]⚠ Executing AWS SDK operations and AWS FIS experiments may incur charges in your AWS account.[/bold red]",
                title="Notice",
                border_style="red",
            ),
            justify="center",
        )

        console.print()

        #
        # Screen Title
        #

        console.print("[bold cyan]Select AWS Region[/bold cyan]")

        console.print()

        #
        # Region Menu
        #

        menu(
            "Supported AWS Regions",
            [
                (index, f"{location:<30} {region}")
                for index, (region, location) in enumerate(self.REGIONS, start=1)
            ]
            + [
                (8, "Other (Enter Region Manually)"),
                (0, "Back" if navigation else "Exit"),
                *([("M", "Main Menu")] if navigation else []),
            ],
        )

        while True:
            choice = prompt("Select Region").strip()

            #
            # Exit
            #

            if choice == "0":
                if navigation:
                    return None
                raise SystemExit

            if navigation and choice.lower() == "m":
                return "__main_menu__"

            #
            # Manual Region Entry
            #

            elif choice == "8":
                while True:
                    region = prompt("Enter AWS Region").strip().lower()

                    if region:
                        return region

                    error("Region cannot be empty")

            #
            # Predefined Regions
            #

            try:
                return self.REGIONS[int(choice) - 1][0]

            except (ValueError, IndexError):
                error("Invalid Selection")
