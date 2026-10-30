from unittest.mock import MagicMock, patch

from rich.layout import Layout

from chaosforge.interfaces.cli.interactive.ui.layout import (
    create_layout,
    render_layout,
)


def test_create_layout():
    layout = create_layout(
        region="eu-central-1",
        campaign_name="Campaign",
        experiment_count=5,
    )

    assert isinstance(layout, Layout)

    assert layout.get("banner").name == "banner"
    assert layout.get("dashboard").name == "dashboard"
    assert layout.get("body").name == "body"


@patch("chaosforge.interfaces.cli.interactive.ui.layout.dashboard")
@patch("chaosforge.interfaces.cli.interactive.ui.layout.print_banner")
def test_render_layout_without_body(
    mock_banner,
    mock_dashboard,
):
    render_layout(
        region="eu-central-1",
        campaign_name="Campaign",
        experiment_count=5,
    )

    mock_banner.assert_called_once()

    mock_dashboard.assert_called_once_with(
        region="eu-central-1",
        campaign_name="Campaign",
        experiment_count=5,
        aws_profile="default",
    )


@patch("chaosforge.interfaces.cli.interactive.ui.layout.dashboard")
@patch("chaosforge.interfaces.cli.interactive.ui.layout.print_banner")
def test_render_layout_with_body(
    mock_banner,
    mock_dashboard,
):
    body = MagicMock()

    render_layout(
        region="eu-central-1",
        campaign_name="Campaign",
        experiment_count=5,
        body=body,
        aws_profile="prod",
    )

    mock_banner.assert_called_once()

    mock_dashboard.assert_called_once_with(
        region="eu-central-1",
        campaign_name="Campaign",
        experiment_count=5,
        aws_profile="prod",
    )

    body.assert_called_once()
