from types import SimpleNamespace
from unittest.mock import patch

from rich.table import Table
from rich.text import Text

from chaosforge.interfaces.cli.interactive.ui.tables import (
    campaign,
    key_value,
    menu,
)


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_menu(mock_print):
    menu(
        "Main Menu",
        [
            ("1", "Option One"),
            ("2", "Option Two"),
        ],
    )

    mock_print.assert_called_once()

    table = mock_print.call_args.args[0]

    assert isinstance(table, Table)

    assert table.title == "[bold bright_cyan]Main Menu[/bold bright_cyan]"
    assert len(table.columns) == 1
    assert table.columns[0].header == "Option"

    assert len(table.rows) == 2
    assert Text.from_markup(table.columns[0]._cells[0]).plain == "  1. Option One"
    assert Text.from_markup(table.columns[0]._cells[1]).plain == "  2. Option Two"

    rendered = table.__rich_console__(
        console=None,
        options=None,
    )

    assert rendered is not None


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_menu_aligns_labels_after_single_and_double_digit_options(mock_print):
    menu("", [(1, "One"), (10, "Ten")])

    table = mock_print.call_args.args[0]
    assert Text.from_markup(table.columns[0]._cells[0]).plain == "   1. One"
    assert Text.from_markup(table.columns[0]._cells[1]).plain == "  10. Ten"


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_key_value(mock_print):
    key_value(
        "Configuration",
        {
            "Region": "eu-central-1",
            "Engine": "Chaos Toolkit",
        },
    )

    mock_print.assert_called_once()

    table = mock_print.call_args.args[0]

    assert isinstance(table, Table)

    assert table.title == "[bold bright_cyan]Configuration[/bold bright_cyan]"


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_campaign_pending(mock_print):
    experiments = [
        SimpleNamespace(
            service="lambda",
            engine="Chaos Toolkit",
            name="Memory",
            status="Pending",
            variables={},
        )
    ]

    campaign(experiments)

    mock_print.assert_called_once()

    table = mock_print.call_args.args[0]

    assert isinstance(table, Table)


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_campaign_running(mock_print):
    experiments = [
        SimpleNamespace(
            service="lambda",
            engine="AWS FIS",
            name="Delay",
            status="Running",
            variables={},
        )
    ]

    campaign(experiments)

    mock_print.assert_called_once()


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_campaign_success(mock_print):
    experiments = [
        SimpleNamespace(
            service="dynamodb",
            engine="Chaos Toolkit",
            name="Capacity",
            status="Success",
            variables={},
        )
    ]

    campaign(experiments)

    mock_print.assert_called_once()


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_campaign_failed(mock_print):
    experiments = [
        SimpleNamespace(
            service="rds",
            engine="Chaos Toolkit",
            name="IOPS",
            status="Failed",
            variables={},
        )
    ]

    campaign(experiments)

    mock_print.assert_called_once()


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_campaign_unknown_status_and_service(mock_print):
    experiments = [
        SimpleNamespace(
            service="custom",
            engine="Custom",
            name="Experiment",
            status="Unknown",
            variables={},
        )
    ]

    campaign(experiments)

    mock_print.assert_called_once()


@patch("chaosforge.interfaces.cli.interactive.ui.tables.console.print")
def test_campaign_all_service_names(mock_print):
    experiments = [
        SimpleNamespace(service="lambda", engine="E", name="N", status="Pending", variables={}),
        SimpleNamespace(service="dynamodb", engine="E", name="N", status="Pending", variables={}),
        SimpleNamespace(service="rds", engine="E", name="N", status="Pending", variables={}),
        SimpleNamespace(service="elasticache", engine="E", name="N", status="Pending", variables={}),
        SimpleNamespace(service="sns", engine="E", name="N", status="Pending", variables={}),
        SimpleNamespace(service="fis", engine="E", name="N", status="Pending", variables={}),
    ]

    campaign(experiments)

    mock_print.assert_called_once()
