from unittest.mock import patch

from chaosforge.interfaces.cli.interactive.ui.progress import create_progress


def test_create_progress():
    with patch("chaosforge.interfaces.cli.interactive.ui.progress.Progress") as mock_progress:
        result = create_progress()

    mock_progress.assert_called_once()
    assert result == mock_progress.return_value
