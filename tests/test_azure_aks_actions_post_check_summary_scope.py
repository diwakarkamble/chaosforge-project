"""
Regression test for a real bug found via a live campaign report
(campaign-report-20260921-112938.txt): when Phase 6 post-checks fail for a
Disk I/O (IOChaos) experiment, the CLI printed a "Network chaos outcome"
heading and a completely empty "What was measured" before/during/after
table.

Root cause: cleanup_experiment()'s shared post-check-failure branch called
_print_network_outcome()/_print_net_impact_summary() unconditionally for
*any* experiment type in the combined Pod/Stress/Network/Time/HTTP/DNS/IO
chaos set whenever a post-check failed — not just for the 6 true
NETWORK_CHAOS_EXPERIMENTS these printers actually know how to build rows
for. For every other experiment type (IOChaos included), the row-building
logic in _print_net_impact_summary() has no matching branch, so the table
renders with headers only and zero rows, under a mislabeled "Network chaos
outcome" heading.

The fix scopes both printer calls to experiment_id in
NETWORK_CHAOS_EXPERIMENTS, while the RuntimeError that records the post-check
failure (and keeps the failure visible in the report) is still raised for
every experiment type either way.
"""

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor as azure_aks_actions


def _run_cleanup_with_one_failing_post_check(experiment_id):
    fake_session_instance = MagicMock()
    fake_session_instance.run_checks.return_value = {
        "Some Post Check": {"passed": False},
    }

    with patch.object(
        azure_aks_actions, "_kubectl",
        return_value=CompletedProcess([], 0, stdout="", stderr=""),
    ), patch.object(azure_aks_actions, "_load_state", return_value={"_setup_complete": True}), \
       patch.object(azure_aks_actions, "_reopen_session", return_value=None), \
       patch.object(azure_aks_actions, "ValidationSession",
                     return_value=fake_session_instance), \
       patch.object(azure_aks_actions, "build_post_experiment_checks",
                     return_value={}), \
       patch.object(azure_aks_actions, "_print_network_outcome") as mock_outcome, \
       patch.object(azure_aks_actions, "_print_net_impact_summary") as mock_summary:
        try:
            azure_aks_actions.cleanup_experiment(
                experiment_id, "ctx", "app-ns", "pvc-app",
                volume_path="/data",
            )
        except RuntimeError as exc:
            assert "Post-experiment checks failed" in str(exc)
        else:
            raise AssertionError(
                "cleanup_experiment should re-raise the post-check RuntimeError"
            )

    return mock_outcome, mock_summary


def test_io_chaos_post_check_failure_does_not_print_the_network_only_summary():
    mock_outcome, mock_summary = _run_cleanup_with_one_failing_post_check(
        "aks-io-latency"
    )

    mock_outcome.assert_not_called()
    mock_summary.assert_not_called()


def test_network_chaos_post_check_failure_still_prints_its_own_summary():
    mock_outcome, mock_summary = _run_cleanup_with_one_failing_post_check(
        "aks-packet-loss"
    )

    mock_outcome.assert_called_once()
    mock_summary.assert_called_once()
