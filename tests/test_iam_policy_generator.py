from unittest.mock import MagicMock, patch

from chaosforge.application.iam import iam_actions
from chaosforge.interfaces.cli.interactive.iam_policy_generator import (
    confirm_required_policies,
    display_required_policies,
)


@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.console")
@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.permission_reports")
def test_display_required_policies_delegates_to_shared_report(mock_reports, mock_console):
    campaign = MagicMock()
    mock_reports.render_terminal.return_value = "# Permission Report"

    display_required_policies(campaign)

    mock_reports.render_terminal.assert_called_once_with(campaign)
    mock_console.print.assert_called_once_with("# Permission Report")


# ----------------------------------------------------------
# Continue
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.prompt")
def test_confirm_required_policies_yes(
    mock_prompt,
):

    campaign = MagicMock()

    mock_prompt.return_value = "y"

    assert confirm_required_policies(campaign) is True


# ----------------------------------------------------------
# Cancel
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.prompt")
def test_confirm_required_policies_no(
    mock_prompt,
):

    campaign = MagicMock()

    mock_prompt.return_value = "n"

    assert confirm_required_policies(campaign) is False


# ----------------------------------------------------------
# View Policy
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.pause")
@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.display_required_policies")
@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.prompt")
def test_confirm_required_policies_view(
    mock_prompt,
    mock_display,
    mock_pause,
):

    campaign = MagicMock()

    mock_prompt.side_effect = [
        "v",
        "y",
    ]

    assert confirm_required_policies(campaign) is True

    mock_display.assert_called_once_with(campaign)

    mock_pause.assert_called_once()


# ----------------------------------------------------------
# Invalid then Continue
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.warning")
@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.pause")
@patch("chaosforge.interfaces.cli.interactive.iam_policy_generator.prompt")
def test_confirm_required_policies_invalid(
    mock_prompt,
    mock_pause,
    mock_warning,
):

    campaign = MagicMock()

    mock_prompt.side_effect = [
        "abc",
        "y",
    ]

    assert confirm_required_policies(campaign) is True

    mock_warning.assert_called_once_with("Invalid Selection")

    mock_pause.assert_called_once()


def test_cli_and_web_share_all_iam_action_categories():
    metadata = {
        "iam": {
            "read": ["ecs:DescribeServices"],
            "modify": ["ecs:UpdateService"],
            "delete": ["fis:DeleteExperimentTemplate"],
            "additional": ["iam:PassRole"],
        }
    }

    assert iam_actions(metadata) == [
        "ecs:DescribeServices",
        "ecs:UpdateService",
        "fis:DeleteExperimentTemplate",
        "iam:PassRole",
    ]
