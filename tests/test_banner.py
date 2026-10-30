from unittest.mock import patch

from chaosforge.interfaces.cli.interactive.ui.banner import print_banner


@patch("chaosforge.interfaces.cli.interactive.ui.banner.console")
def test_print_banner(mock_console):
    print_banner()

    mock_console.print.assert_called_once()
