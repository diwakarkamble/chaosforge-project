from unittest.mock import patch

from chaosforge.interfaces.cli.interactive.ui.tree import show_grouped_tree, show_tree


def test_show_tree():
    items = [
        "Lambda",
        "DynamoDB",
        "RDS",
    ]

    with patch("chaosforge.interfaces.cli.interactive.ui.tree.console") as mock_console:
        show_tree(
            "AWS Services",
            "ChaosForge",
            items,
        )

    assert mock_console.print.call_count == 4


def test_show_tree_empty():
    with patch("chaosforge.interfaces.cli.interactive.ui.tree.console") as mock_console:
        show_tree(
            "AWS Services",
            "ChaosForge",
            [],
        )

    assert mock_console.print.call_count == 4


def test_show_grouped_tree():
    groups = {
        "Compute": [
            "Lambda",
            "ECS",
        ],
        "Storage": [
            "S3",
            "DynamoDB",
        ],
    }

    with patch("chaosforge.interfaces.cli.interactive.ui.tree.console") as mock_console:
        show_grouped_tree(
            "AWS Services",
            groups,
        )

    mock_console.print.assert_called_once()


def test_show_grouped_tree_empty():
    with patch("chaosforge.interfaces.cli.interactive.ui.tree.console") as mock_console:
        show_grouped_tree(
            "AWS Services",
            {},
        )

    mock_console.print.assert_called_once()
