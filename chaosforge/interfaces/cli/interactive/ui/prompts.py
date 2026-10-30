from chaosforge.interfaces.cli.interactive.ui.console import console


def prompt(text):

    return console.input(
        f"\n[bold bright_cyan]❯[/bold bright_cyan] [bold white]{text}[/bold white]: "
    )


def confirm(text):

    return (
        console.input(
            f"\n[bold yellow]❯[/bold yellow] "
            f"[bold white]{text}[/bold white] "
            f"[bright_black](Y/N)[/bright_black]: "
        )
        .strip()
        .lower()
    )


def pause():

    console.input(
        "\n[bright_black]────────────────────────────────────────[/bright_black]\n"
        "[bright_black]Press Enter to continue...[/bright_black]"
    )
