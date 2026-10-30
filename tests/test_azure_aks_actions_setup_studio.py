"""
Unit tests for setup_studio (Phase 1 orchestration) in
actions/azure_aks_actions.py. Covers the dry-run path (Chaos Mesh network
experiment), the node-kubectl path (Studio target registration skipped), and
the selector-scope hard-block abort path.
"""

from unittest.mock import MagicMock, patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    executor as m,
)


def _base_mocks():
    """Common patches needed for any setup_studio call — avoids real Azure
    CLI calls, interactive confirmation prompts, and real kubectl/session I/O."""
    return [
        patch.object(m, "ValidationSession", return_value=MagicMock(log_dir="/tmp/fake-log-dir")),
        patch.object(m, "_resolve_azure_details", return_value=("sub-1", "rg-1", "cluster-1")),
        patch.object(m, "_get_or_create_chaos_rg", return_value="chaos-rg-1"),
        patch.object(m, "_confirm_destructive_action", return_value=None),
        patch.object(m, "check_protected_namespace", return_value=None),
        patch.object(m, "run_parallel_steady_state", return_value=True),
        patch.object(m, "_kubectl", return_value=MagicMock(returncode=0, stdout="", stderr="")),
    ]


def test_dry_run_skips_studio_target_registration_for_chaos_mesh_experiment():
    mocks = _base_mocks()
    for p in mocks:
        p.start()
    try:
        with patch.object(m, "_setup_studio_target") as mock_setup_target, \
             patch.object(m, "_build_spec") as mock_build_spec, \
             patch.object(m, "_precreate_studio_experiment") as mock_precreate:
            m.setup_studio(
                "aks-network-delay", "ctx", "ns", "dep",
                label_key="app", label_val="x", dry_run="true",
            )
        mock_setup_target.assert_not_called()
        mock_build_spec.assert_not_called()
        mock_precreate.assert_not_called()
    finally:
        for p in mocks:
            p.stop()


def test_live_run_registers_studio_target_and_precreates_experiment():
    mocks = _base_mocks()
    for p in mocks:
        p.start()
    try:
        with patch.object(m, "_setup_studio_target") as mock_setup_target, \
             patch.object(m, "_build_spec", return_value=({}, "{}", "PodChaos")) as mock_build_spec, \
             patch.object(m, "_precreate_studio_experiment") as mock_precreate, \
             patch.object(m, "_safe_name", return_value="exp-name-123"):
            m.setup_studio(
                "aks-network-delay", "ctx", "ns", "dep",
                label_key="app", label_val="x", dry_run="false",
            )
        mock_setup_target.assert_called_once()
        mock_build_spec.assert_called_once()
        mock_precreate.assert_called_once()
    finally:
        for p in mocks:
            p.stop()


def test_node_kubectl_experiment_skips_studio_target_registration_even_when_live():
    mocks = _base_mocks()
    for p in mocks:
        p.start()
    try:
        with patch.object(m, "_prechecks_node_drain", return_value=(True, {})), \
             patch.object(m, "_setup_studio_target") as mock_setup_target, \
             patch.object(m, "_build_spec") as mock_build_spec:
            m.setup_studio(
                "aks-node-drain", "ctx", "", "", target_node="node-1", dry_run="false",
            )
        mock_setup_target.assert_not_called()
        mock_build_spec.assert_not_called()
    finally:
        for p in mocks:
            p.stop()


def test_node_kubectl_experiment_skips_workload_steady_state_checks():
    mocks = _base_mocks()
    for p in mocks:
        p.start()
    try:
        with patch.object(m, "_prechecks_node_drain", return_value=(True, {})):
            m.setup_studio(
                "aks-node-drain", "ctx", "", "", target_node="node-1", dry_run="false",
            )
        m.run_parallel_steady_state.assert_not_called()
    finally:
        for p in mocks:
            p.stop()


def test_selector_scope_hard_block_aborts_setup_before_studio_registration():
    mocks = _base_mocks()
    for p in mocks:
        p.start()
    try:
        with patch.object(m, "validate_and_resolve_selector", return_value={
                "ok": False, "hard_block": True,
                "warning": "Label selector also matches sibling Deployment 'other-dep'",
             }), \
             patch.object(m, "_setup_studio_target") as mock_setup_target:
            try:
                m.setup_studio(
                    "aks-network-delay", "ctx", "ns", "dep",
                    label_key="app", label_val="x", dry_run="false",
                )
                assert False, "expected RuntimeError to be raised"
            except RuntimeError as exc:
                assert "sibling Deployment" in str(exc)
        mock_setup_target.assert_not_called()
    finally:
        for p in mocks:
            p.stop()
