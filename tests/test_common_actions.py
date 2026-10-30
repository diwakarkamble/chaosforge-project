from unittest.mock import patch

from chaosforge.providers.aws.common_actions import wait_for_duration


@patch("chaosforge.providers.aws.common_actions.print")
@patch("chaosforge.providers.aws.common_actions.time.sleep")
def test_wait_for_duration(mock_sleep, mock_print):
    wait_for_duration(5)

    mock_sleep.assert_called_once_with(5.0)

    mock_print.assert_any_call("Waiting for 5.0 seconds...")

    mock_print.assert_any_call("Wait completed.")


@patch("chaosforge.providers.aws.common_actions.print")
@patch("chaosforge.providers.aws.common_actions.time.sleep")
def test_wait_for_duration_string(mock_sleep, mock_print):
    wait_for_duration("2.5")

    mock_sleep.assert_called_once_with(2.5)

    mock_print.assert_any_call("Waiting for 2.5 seconds...")

    mock_print.assert_any_call("Wait completed.")
