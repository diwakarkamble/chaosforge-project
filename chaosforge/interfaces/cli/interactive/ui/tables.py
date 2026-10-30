from rich.box import SIMPLE
from rich.table import Table

from chaosforge.interfaces.cli.interactive.ui.console import console


def menu(title, rows):
    rows = list(rows)

    table = Table(
        title=f"[bold bright_cyan]{title}[/bold bright_cyan]",
        title_style="bold bright_cyan",
        border_style="bright_blue",
        box=SIMPLE,
        show_header=True,
        header_style="bold bright_cyan",
        show_lines=False,
        expand=True,
        pad_edge=True,
    )

    table.add_column("Option", style="bold white", ratio=1)

    option_width = max((len(str(number).rstrip(".")) for number, _ in rows), default=1)
    for number, text in rows:
        num_str = str(number).rstrip(".")
        table.add_row(
            f"  [bold bright_cyan]{num_str.rjust(option_width)}.[/bold bright_cyan] {text}"
        )

    console.print(table)


def menu_categorized(title, groups):
    """Renders ALL categories in a single table with one "Option" header,
    shown only once. Each category name appears as its own (unselectable)
    row, followed by its indented numbered items.

    groups: list of (category_name, [(number, text), ...])
    """

    table = Table(
        title=f"[bold bright_cyan]{title}[/bold bright_cyan]" if title else None,
        title_style="bold bright_cyan",
        border_style="bright_blue",
        box=SIMPLE,
        show_header=True,
        header_style="bold bright_cyan",
        show_lines=False,
        expand=True,
        pad_edge=True,
    )

    table.add_column("Option", style="bold white", ratio=1)

    groups = [(category_name, list(rows)) for category_name, rows in groups]
    option_width = max(
        (len(str(number).rstrip(".")) for _, rows in groups for number, _ in rows),
        default=1,
    )

    for index, (category_name, rows) in enumerate(groups):
        if not rows:
            continue

        if index > 0:
            table.add_row("")

        table.add_row(f"[bold yellow]{category_name}[/bold yellow]")

        for number, text in rows:
            table.add_row(
                f"  [bold bright_cyan]{str(number).rstrip('.').rjust(option_width)}.[/bold bright_cyan] {text}"
            )

    console.print(table)


def key_value(title, data):

    table = Table(
        title=f"[bold bright_cyan]{title}[/bold bright_cyan]",
        border_style="bright_blue",
        box=SIMPLE,
        show_header=False,
        expand=True,
    )

    table.add_column(width=20, style="bold bright_cyan", ratio=0)

    table.add_column(style="white", ratio=1)

    for key, value in data.items():
        table.add_row(key, str(value))

    console.print(table)


def campaign(experiments):

    SERVICE_NAMES = {
        "lambda": "AWS Lambda",
        "dynamodb": "Amazon DynamoDB",
        "rds": "Amazon RDS",
        "elasticache": "Amazon ElastiCache",
        "sns": "Amazon SNS",
        "fis": "AWS Lambda",  # Temporary until we fix FIS creation
    }

    table = Table(
        title="[bold bright_cyan]Campaign Summary[/bold bright_cyan]",
        border_style="bright_blue",
        box=SIMPLE,
        expand=True,
        show_lines=False,
        header_style="bold bright_cyan",
    )

    table.add_column("#", width=5, justify="center", style="bold bright_cyan", ratio=0)

    table.add_column("Service", width=22, style="bold bright_cyan", ratio=0)

    table.add_column("Engine", width=18, style="bold green", ratio=0)

    # Only column without a fixed width — absorbs all the leftover expand width.
    table.add_column("Experiment", min_width=35, style="bold white", ratio=1)

    table.add_column("Status", width=18, justify="center", ratio=0)
    table.add_column("Safety", width=14, justify="center", ratio=0)

    for index, experiment in enumerate(experiments, start=1):
        status = experiment.status.lower()

        if status == "pending":
            status = "[yellow]🟡 Pending[/yellow]"

        elif status == "running":
            status = "[cyan]🔄 Running[/cyan]"

        elif status == "success":
            status = "[green]✅ Success[/green]"

        elif status == "failed":
            status = "[red]❌ Failed[/red]"

        else:
            status = experiment.status

        service_name = SERVICE_NAMES.get(experiment.service.lower(), experiment.service)
        dry_run_val = experiment.variables.get("dry_run", "")
        is_dry_run = str(dry_run_val).strip().lower() in ("true", "1", "yes", "y")
        exp_name = experiment.name
        if is_dry_run:
            exp_name += "  [dim yellow][DRY RUN][/dim yellow]"

        table.add_row(
            f"[bold bright_cyan]{index}[/bold bright_cyan]",
            f"[bold]{service_name}[/bold]",
            experiment.engine,
            exp_name,
            status,
            "[green]REVERSIBLE[/green]"
            if getattr(experiment, "reversibility", "reversible") == "reversible"
            else "[red]IRREVERSIBLE[/red]",
        )

    console.print(table)
