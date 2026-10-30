from rich.panel import Panel
from rich.table import Table

from chaosforge.application.services.cloud_identity import get_cloud_identity
from chaosforge.application.services.user_settings import format_timezone, get_timezone_id
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.session import context


def dashboard(region, campaign_name, experiment_count, aws_profile="default", cloud="aws"):

    if context.cloud == cloud and cloud in {"aws", "azure"}:
        context.cloud_identity = get_cloud_identity(cloud, region or "us-east-1")

    table = Table(show_header=False, box=None, expand=True, padding=(0, 4))

    table.add_column()
    table.add_column()

    is_azure = cloud == "azure"

    #
    # Row 1 — Region / Cloud label
    #
    if is_azure:
        cluster_label = context.aks_cluster_name or "Not configured"
        region_label = "☁  [bold cyan]Cloud[/bold cyan]\n[white]Microsoft Azure[/white]"
        profile_label = f"☸ [bold cyan]AKS Cluster[/bold cyan]\n[white]{cluster_label}[/white]"
    else:
        region_label = f"🌍 [bold cyan]Region[/bold cyan]\n[white]{region}[/white]"
        profile_label = f"👤 [bold cyan]Profile[/bold cyan]\n[white]{aws_profile}[/white]"

    table.add_row(region_label, profile_label)

    timezone_id = context.timezone_id or get_timezone_id()
    table.add_row(
        "🕒 [bold cyan]Timezone[/bold cyan]\n"
        f"[white]{format_timezone(timezone_id)}[/white]",
        "",
    )

    identity = context.cloud_identity or {"authenticated": False, "name": "Not logged in"}
    identity_status = "[bold green]Logged in[/bold green]" if identity["authenticated"] else "[bold yellow]Not logged in[/bold yellow]"
    table.add_row(
        f"🔐 [bold cyan]Identity[/bold cyan]\n[white]{identity['name']}[/white]",
        f"🛡 [bold cyan]Authentication[/bold cyan]\n{identity_status}",
    )

    #
    # Campaign status
    #
    table.add_row(
        f"📦 [bold cyan]Campaign[/bold cyan]\n[white]{campaign_name}[/white]",
        f"🧪 [bold cyan]Experiments[/bold cyan]\n[bold green]{experiment_count} Configured[/bold green]",
    )

    #
    # Row 3 — Engine
    #
    engine = "Chaos Studio + Chaos Toolkit" if is_azure else "Chaos Toolkit + AWS FIS"

    table.add_row(
        f"🔧 [bold cyan]Engine[/bold cyan]\n[white]{engine}[/white]",
        "🟢 [bold cyan]Status[/bold cyan]\n[bold green]Ready for Execution[/bold green]",
    )

    console.print(
        Panel(
            table,
            title="[bold bright_cyan]Mission Control[/bold bright_cyan]",
            border_style="bright_blue",
            padding=(0, 2),
            expand=True,
        )
    )
