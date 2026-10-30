from rich.layout import Layout

from chaosforge.interfaces.cli.interactive.ui.banner import print_banner
from chaosforge.interfaces.cli.interactive.ui.dashboard import dashboard


def create_layout(region, campaign_name, experiment_count, aws_profile="default"):

    layout = Layout()

    layout.split_column(
        Layout(name="banner", size=5),
        Layout(name="dashboard", size=6),
        Layout(name="body"),
    )

    return layout


def render_layout(
    region, campaign_name, experiment_count, body=None, aws_profile="default"
):

    print_banner()

    dashboard(
        region=region,
        campaign_name=campaign_name,
        experiment_count=experiment_count,
        aws_profile=aws_profile,
    )

    if body:
        body()
