"""
Unit tests for run_experiment (Phase 2 orchestration) in
actions/azure_aks_actions.py. Covers: setup-not-complete guard, dry-run
early return, node-drain routing, VMSS zone-failure routing, and Chaos Mesh
Studio routing (default path).
"""

from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    executor as m,
)


def test_raises_when_setup_did_not_complete():
    with patch.object(m, "_load_state", return_value={"_setup_complete": False}):
        with pytest.raises(RuntimeError, match="setup_studio did not complete"):
            m.run_experiment("aks-network-delay", "ctx", "ns", "dep")


def test_dry_run_prints_preview_and_returns_without_injecting_fault():
    state = {"_setup_complete": True, "dry_run": True, "aks_name": "cluster-1"}
    with patch.object(m, "_load_state", return_value=state), \
         patch.object(m, "_reopen_session", return_value=None), \
         patch.object(m, "_print_dry_run_preview") as mock_preview, \
         patch.object(m, "_run_node_drain") as mock_drain, \
         patch.object(m, "_run_studio_experiment") as mock_studio:
        m.run_experiment("aks-network-delay", "ctx", "ns", "dep", dry_run="true")
    mock_preview.assert_called_once()
    mock_drain.assert_not_called()
    mock_studio.assert_not_called()


def test_precheck_failures_prompt_for_operator_override_before_injecting():
    state = {
        "_setup_complete": True, "dry_run": False,
        "_precheck_failures": "Replica floor check failed",
        "target_node": "node-1",
    }
    with patch.object(m, "_load_state", return_value=state), \
         patch.object(m, "_reopen_session", return_value=None), \
         patch.object(m, "_prompt_precheck_override") as mock_prompt, \
         patch.object(m, "_run_node_drain") as mock_drain:
        m.run_experiment("aks-node-drain", "ctx", "ns", "dep")
    mock_prompt.assert_called_once_with("aks-node-drain", "Replica floor check failed")
    mock_drain.assert_called_once()


def test_node_drain_routes_to_run_node_drain_and_returns_early():
    state = {"_setup_complete": True, "dry_run": False, "target_node": "node-1"}
    with patch.object(m, "_load_state", return_value=state), \
         patch.object(m, "_reopen_session", return_value=MagicMock()), \
         patch.object(m, "_run_node_drain") as mock_drain, \
         patch.object(m, "_build_spec") as mock_build_spec:
        m.run_experiment("aks-node-drain", "ctx", "ns", "dep")
    mock_drain.assert_called_once()
    mock_build_spec.assert_not_called()


def test_vmss_zone_failure_routes_multi_target_to_run_zone_failure():
    state = {
        "_setup_complete": True, "dry_run": False,
        "target_node": "node-1,node-2", "aks_name": "cluster-1",
        "subscription_id": "sub-1", "resource_group": "rg-1",
        "vmss_targets": [{"node": "node-1", "vmss_name": "vmss-a", "instance_id": "0"}],
        "node_rg": "node-rg-1",
    }
    with patch.object(m, "_load_state", return_value=state), \
         patch.object(m, "_reopen_session", return_value=MagicMock()), \
         patch.object(m, "_build_spec", return_value=({}, "{}", "VmssShutdown")), \
         patch.object(m, "_safe_name", return_value="exp-vmss-1"), \
         patch.object(m, "_run_zone_failure") as mock_zone_failure, \
         patch.object(m, "_run_vmss_experiment") as mock_vmss_single:
        m.run_experiment("aks-node-zone-failure", "ctx", "", "", target_node="node-1,node-2")
    mock_zone_failure.assert_called_once()
    mock_vmss_single.assert_not_called()


def test_vmss_raises_when_no_capability_urn_for_kind():
    state = {"_setup_complete": True, "dry_run": False, "target_node": "node-1"}
    with patch.object(m, "_load_state", return_value=state), \
         patch.object(m, "_reopen_session", return_value=None), \
         patch.object(m, "_build_spec", return_value=({}, "{}", "UnknownKind")):
        with pytest.raises(RuntimeError, match="No VMSS capability URN"):
            m.run_experiment("aks-node-notready", "ctx", "", "", target_node="node-1")


def test_chaos_mesh_studio_default_path_uses_precreated_spec_from_setup():
    state = {
        "_setup_complete": True, "dry_run": False,
        "subscription_id": "sub-1", "resource_group": "rg-1", "chaos_rg": "chaos-rg-1",
        "aks_name": "cluster-1",
        "studio_experiment_name": "exp-precreated",
        "_json_spec": '{"precreated": true}',
        "_capability_urn": "urn:csci:microsoft:podchaos:2.1",
        "_experiment_pre_created": True,
    }
    with patch.object(m, "_load_state", return_value=state), \
         patch.object(m, "_reopen_session", return_value=MagicMock()), \
         patch.object(m, "_build_spec", return_value=({}, "{}", "PodChaos")), \
         patch.object(m, "_run_studio_experiment") as mock_run_studio:
        m.run_experiment("aks-network-delay", "ctx", "ns", "dep")
    mock_run_studio.assert_called_once()
    args = mock_run_studio.call_args.args
    assert args[0] == "exp-precreated"
    assert args[1] == '{"precreated": true}'
    assert args[2] == "urn:csci:microsoft:podchaos:2.1"


def test_chaos_mesh_unsupported_kind_applies_direct():
    state = {"_setup_complete": True, "dry_run": False}
    with patch.object(m, "_load_state", return_value=state), \
         patch.object(m, "_reopen_session", return_value=None), \
         patch.object(m, "_build_spec", return_value=({"some": "spec"}, "{}", "UnsupportedKind")), \
         patch.object(m, "_apply_direct") as mock_apply_direct, \
         patch.object(m, "_run_studio_experiment") as mock_run_studio:
        m.run_experiment("aks-network-delay", "ctx", "ns", "dep")
    mock_apply_direct.assert_called_once()
    mock_run_studio.assert_not_called()
