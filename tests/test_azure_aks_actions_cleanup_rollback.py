"""
Extends the cleanup_experiment mocking convention established in
tests/test_azure_aks_actions_iochaos_cleanup.py to cover the node-drain and
node-taint rollback branches. Post-check helpers for these experiment types
(_postchecks_node_drain/_postchecks_node_taint) are mocked out here since
they are covered separately.
"""

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor as azure_aks_actions


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_cleanup_experiment_uncordons_node_on_drain_rollback():
    fake_session = MagicMock()
    fake_session.run_checks.return_value = {}
    mock_kubectl = MagicMock(return_value=_cp())

    with patch.object(azure_aks_actions, "_kubectl", mock_kubectl), \
         patch.object(azure_aks_actions, "_load_state", return_value={"target_node": "node-a"}), \
         patch.object(azure_aks_actions, "_reopen_session", return_value=fake_session), \
         patch.object(azure_aks_actions, "_postchecks_node_drain") as mock_postchecks:
        azure_aks_actions.cleanup_experiment(
            "aks-node-drain", "ctx", "", "", target_node="node-a",
        )

    uncordon_calls = [c for c in mock_kubectl.call_args_list if c.args[:2] == ("uncordon", "node-a")]
    assert len(uncordon_calls) == 1
    mock_postchecks.assert_called_once()
    assert mock_postchecks.call_args.args[0] == "node-a"


def test_cleanup_experiment_removes_taint_on_taint_rollback():
    fake_session = MagicMock()
    fake_session.run_checks.return_value = {}
    mock_kubectl = MagicMock(return_value=_cp())

    with patch.object(azure_aks_actions, "_kubectl", mock_kubectl), \
         patch.object(azure_aks_actions, "_load_state", return_value={"target_node": "node-a"}), \
         patch.object(azure_aks_actions, "_reopen_session", return_value=fake_session), \
         patch.object(azure_aks_actions, "_postchecks_node_taint"):
        azure_aks_actions.cleanup_experiment(
            "aks-node-taint", "ctx", "", "", target_node="node-a",
        )

    taint_calls = [
        c for c in mock_kubectl.call_args_list
        if c.args[:2] == ("taint", "nodes") and "chaos=test:NoExecute-" in c.args
    ]
    assert len(taint_calls) == 1


def test_cleanup_experiment_dry_run_skips_rollback_and_deletes_state():
    fake_session = MagicMock()
    with patch.object(azure_aks_actions, "_kubectl") as mock_kubectl, \
         patch.object(azure_aks_actions, "_load_state", return_value={"dry_run": "true"}), \
         patch.object(azure_aks_actions, "_reopen_session", return_value=fake_session), \
         patch.object(azure_aks_actions.os.path, "exists", return_value=True), \
         patch.object(azure_aks_actions.os, "unlink") as mock_unlink:
        azure_aks_actions.cleanup_experiment("aks-pod-kill", "ctx", "ns", "dep")

    mock_kubectl.assert_not_called()
    fake_session.stop.assert_called_once()
    mock_unlink.assert_called_once()


def test_cleanup_experiment_raises_when_post_checks_fail():
    fake_session = MagicMock()
    fake_session.run_checks.return_value = {"Pod Recovery": {"passed": False, "detail": "still terminating"}}
    mock_kubectl = MagicMock(return_value=_cp())

    with patch.object(azure_aks_actions, "_kubectl", mock_kubectl), \
         patch.object(azure_aks_actions, "_load_state", return_value={"_setup_complete": True}), \
         patch.object(azure_aks_actions, "_reopen_session", return_value=fake_session), \
         patch.object(azure_aks_actions, "build_post_experiment_checks", return_value={}):
        try:
            azure_aks_actions.cleanup_experiment("aks-pod-kill", "ctx", "app-ns", "app-dep")
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "Pod Recovery" in str(exc)
