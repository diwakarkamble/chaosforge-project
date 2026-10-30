"""
Unit tests for small standalone helpers in actions/azure_aks_actions.py:
_get_or_create_chaos_rg, _http_chaos_teardown, and _reopen_session. See
tests/test_azure_aks_actions_iochaos_cleanup.py for the established
cleanup_experiment mocking convention reused here.
"""

import os
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor as azure_aks_actions


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ── _get_or_create_chaos_rg ─────────────────────────────────────────────────

def setup_function(_fn):
    azure_aks_actions._CHAOS_RG_CACHE.clear()


def test_get_or_create_chaos_rg_returns_cached_name_without_az_calls():
    azure_aks_actions._CHAOS_RG_CACHE["sub-123"] = "chaosforge-experiments-sub-123"
    with patch.object(azure_aks_actions.subprocess, "run") as mock_run:
        rg = azure_aks_actions._get_or_create_chaos_rg("sub-123", "eastus")
    assert rg == "chaosforge-experiments-sub-123"
    mock_run.assert_not_called()


def test_get_or_create_chaos_rg_uses_existing_group_when_show_succeeds():
    with patch.object(azure_aks_actions.subprocess, "run",
                      return_value=_cp(stdout="chaosforge-experiments-sub12345\n")) as mock_run:
        rg = azure_aks_actions._get_or_create_chaos_rg("sub12345678", "eastus")
    assert rg == "chaosforge-experiments-sub12345"
    assert mock_run.call_count == 1  # only "group show", no create needed
    assert azure_aks_actions._CHAOS_RG_CACHE["sub12345678"] == rg


def test_get_or_create_chaos_rg_creates_group_when_not_found():
    responses = [
        _cp(returncode=1, stdout="", stderr="not found"),  # group show fails
        _cp(returncode=0),                                  # group create succeeds
    ]
    with patch.object(azure_aks_actions.subprocess, "run", side_effect=responses) as mock_run:
        rg = azure_aks_actions._get_or_create_chaos_rg("sub12345678", "westus")
    assert rg == "chaosforge-experiments-sub12345"
    assert mock_run.call_count == 2
    create_call = mock_run.call_args_list[1]
    assert "create" in create_call.args[0]
    assert "westus" in create_call.args[0]


# ── _http_chaos_teardown ────────────────────────────────────────────────────

def test_http_chaos_teardown_restores_security_context_and_restarts():
    # orig_ape records the pre-chaos value of allowPrivilegeEscalation per
    # container; False/None means it must be restored to False now.
    dep = {
        "spec": {"template": {"spec": {"containers": [
            {"name": "app", "securityContext": {"allowPrivilegeEscalation": True}},
        ]}}}
    }
    import json as _json
    mock_kubectl = MagicMock(return_value=_cp(stdout=_json.dumps(dep)))
    fake_session = MagicMock()
    with patch.object(azure_aks_actions, "_kubectl", mock_kubectl), \
         patch.object(os, "unlink"):
        azure_aks_actions._http_chaos_teardown(
            "aks-http-delay", "ctx", "app-ns", "app-dep", {"app": False},
            session=fake_session,
        )
    patch_calls = [c for c in mock_kubectl.call_args_list if c.args[:2] == ("patch", "deployment")]
    restart_calls = [c for c in mock_kubectl.call_args_list if c.args[:3] == ("rollout", "restart", "deployment/app-dep")]
    label_calls = [c for c in mock_kubectl.call_args_list if c.args[:2] == ("label", "namespace")]
    assert len(patch_calls) == 1
    assert len(restart_calls) == 1
    assert len(label_calls) == 1
    fake_session.log_event.assert_any_call(
        "rollback", "securityContext restored and pods hardened: app-dep"
    )


def test_http_chaos_teardown_is_noop_when_namespace_or_deployment_missing():
    with patch.object(azure_aks_actions, "_kubectl") as mock_kubectl:
        azure_aks_actions._http_chaos_teardown(
            "aks-http-delay", "ctx", "", "app-dep", {},
        )
    mock_kubectl.assert_not_called()


def test_http_chaos_teardown_swallows_kubectl_get_failure():
    mock_kubectl = MagicMock(return_value=_cp(returncode=1, stderr="boom"))
    with patch.object(azure_aks_actions, "_kubectl", mock_kubectl), \
         patch.object(os, "unlink"):
        azure_aks_actions._http_chaos_teardown(
            "aks-http-delay", "ctx", "app-ns", "app-dep", {},
        )  # must not raise
    # Namespace label removal still attempted even though deployment lookup failed.
    label_calls = [c for c in mock_kubectl.call_args_list if c.args[:2] == ("label", "namespace")]
    assert len(label_calls) == 1


# ── _reopen_session ──────────────────────────────────────────────────────────

def test_reopen_session_returns_none_when_no_log_dir():
    result = azure_aks_actions._reopen_session("aks-pod-kill", {})
    assert result is None


def test_reopen_session_reattaches_when_log_dir_present(tmp_path):
    log_dir = tmp_path / "run-1"
    log_dir.mkdir()
    result = azure_aks_actions._reopen_session("aks-pod-kill", {"_log_dir": str(log_dir)})
    assert result is not None
    assert result.log_dir == str(log_dir)
    result._session_log.close()
