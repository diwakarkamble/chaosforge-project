"""
Unit tests for the pure pre-flight/cluster-health check functions in
actions/aks_safety_checks.py — check_protected_namespace,
check_deployment_replica_floor, check_pdb_allows_disruption,
check_chaos_mesh_running, check_nodes_ready, check_system_pods_running,
_get_pods_for_deployment, _snapshot_pod_health, check_app_stability,
probe_aks_target_healthy, and verify_rollback_health. All only need
`_kubectl` mocking — no threading, Azure SDK, or Live UI involved.
"""

import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety as m,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ── check_protected_namespace ────────────────────────────────────────────────

def test_check_protected_namespace_raises_for_kube_system():
    with pytest.raises(RuntimeError, match="protected"):
        m.check_protected_namespace("kube-system")


def test_check_protected_namespace_allows_normal_namespace():
    m.check_protected_namespace("my-app-ns")  # should not raise


# ── check_deployment_replica_floor ──────────────────────────────────────────

def test_replica_floor_passes_when_deployment_has_enough_ready_replicas():
    dep = {"spec": {"replicas": 3}, "status": {"readyReplicas": 3}}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        m.check_deployment_replica_floor("ctx", "ns", "dep", min_replicas=2)  # no raise


def test_replica_floor_raises_when_desired_below_minimum():
    dep = {"spec": {"replicas": 1}, "status": {"readyReplicas": 1}}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        with pytest.raises(RuntimeError, match="desired replica"):
            m.check_deployment_replica_floor("ctx", "ns", "dep", min_replicas=2)


def test_replica_floor_raises_when_ready_below_minimum():
    dep = {"spec": {"replicas": 3}, "status": {"readyReplicas": 1}}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        with pytest.raises(RuntimeError, match="ready replica"):
            m.check_deployment_replica_floor("ctx", "ns", "dep", min_replicas=2)


def test_replica_floor_falls_back_to_standalone_pod_when_not_a_deployment():
    pod = {"status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "deployment"):
            return _cp(returncode=1, stderr="not found")
        if args[:2] == ("get", "pod"):
            return _cp(stdout=json.dumps(pod))
        return _cp()

    with patch.object(m, "_kubectl", side_effect=_kubectl_router):
        with pytest.raises(RuntimeError, match="standalone pod"):
            m.check_deployment_replica_floor("ctx", "ns", "pod-a", min_replicas=2)


def test_replica_floor_falls_back_to_owning_deployment_when_pod_gone():
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2}}

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "deployment") and "owner-dep" in args:
            return _cp(stdout=json.dumps(dep))
        if args[:2] == ("get", "deployment"):
            return _cp(returncode=1, stderr="not found")
        if args[:2] == ("get", "pod"):
            return _cp(returncode=1, stderr="not found")
        return _cp()

    with patch.object(m, "_kubectl", side_effect=_kubectl_router):
        m.check_deployment_replica_floor(
            "ctx", "ns", "deleted-pod", min_replicas=2, owning_deployment="owner-dep",
        )  # should not raise — falls back cleanly


def test_replica_floor_raises_when_neither_deployment_nor_pod_found():
    with patch.object(m, "_kubectl", return_value=_cp(returncode=1, stderr="not found")):
        with pytest.raises(RuntimeError, match="Could not find"):
            m.check_deployment_replica_floor("ctx", "ns", "ghost", min_replicas=2)


# ── check_pdb_allows_disruption ─────────────────────────────────────────────

def test_pdb_check_noop_when_no_label_selector_given():
    with patch.object(m, "_kubectl") as mock_kubectl:
        m.check_pdb_allows_disruption("ctx", "ns", "", "")
    mock_kubectl.assert_not_called()


def test_pdb_check_raises_when_matching_pdb_allows_zero_disruptions():
    pdbs = {"items": [{
        "metadata": {"name": "my-pdb"},
        "spec": {"selector": {"matchLabels": {"app": "x"}}},
        "status": {"disruptionsAllowed": 0, "currentHealthy": 1, "desiredHealthy": 2},
    }]}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(pdbs))):
        with pytest.raises(RuntimeError, match="allows 0 disruptions"):
            m.check_pdb_allows_disruption("ctx", "ns", "app", "x")


def test_pdb_check_passes_when_no_matching_pdb():
    pdbs = {"items": [{
        "metadata": {"name": "other-pdb"},
        "spec": {"selector": {"matchLabels": {"app": "other"}}},
        "status": {"disruptionsAllowed": 0},
    }]}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(pdbs))):
        m.check_pdb_allows_disruption("ctx", "ns", "app", "x")  # no raise


# ── check_chaos_mesh_running ─────────────────────────────────────────────────

def test_chaos_mesh_running_passes_when_controller_ready():
    pods = {"items": [{
        "metadata": {"name": "chaos-controller-1"},
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
    }]}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(pods))):
        m.check_chaos_mesh_running("ctx")  # no raise


def test_chaos_mesh_running_raises_when_no_ready_controller_in_either_namespace():
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps({"items": []}))):
        with pytest.raises(RuntimeError, match="Chaos Mesh controller-manager"):
            m.check_chaos_mesh_running("ctx")


def test_chaos_mesh_running_falls_back_to_chaos_mesh_namespace():
    # The fallback to the "chaos-mesh" namespace only triggers when the first
    # query outright fails (non-zero returncode) — an empty-but-successful
    # result does NOT trigger it.
    def _kubectl_router(*args, **kwargs):
        if "chaos-testing" in args:
            return _cp(returncode=1, stderr="not found")
        pods = {"items": [{
            "metadata": {"name": "cm-1"},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        }]}
        return _cp(stdout=json.dumps(pods))

    with patch.object(m, "_kubectl", side_effect=_kubectl_router):
        m.check_chaos_mesh_running("ctx")  # no raise — found in fallback namespace


# ── check_nodes_ready ─────────────────────────────────────────────────────────

def test_check_nodes_ready_excludes_control_plane_taints():
    nodes = {"items": [
        {"spec": {"taints": [{"key": "node-role.kubernetes.io/control-plane"}]},
         "status": {"conditions": [{"type": "Ready", "status": "True"}]}},
        {"spec": {}, "status": {"conditions": [{"type": "Ready", "status": "True"}]}},
    ]}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(nodes))):
        m.check_nodes_ready("ctx", min_ready=1)  # no raise — 1 worker node ready


def test_check_nodes_ready_raises_when_not_enough_ready_workers():
    nodes = {"items": [{"spec": {}, "status": {"conditions": [{"type": "Ready", "status": "False"}]}}]}
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps(nodes))):
        with pytest.raises(RuntimeError, match="worker node"):
            m.check_nodes_ready("ctx", min_ready=1)


def test_check_nodes_ready_raises_when_kubectl_fails():
    with patch.object(m, "_kubectl", return_value=_cp(returncode=1, stderr="connection refused")):
        with pytest.raises(RuntimeError, match="Could not list nodes"):
            m.check_nodes_ready("ctx")


# ── check_system_pods_running ─────────────────────────────────────────────────

def test_system_pods_running_passes_when_coredns_ready():
    coredns_pods = {"items": [{
        "metadata": {"name": "coredns-1"},
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
    }]}

    def _kubectl_router(*args, **kwargs):
        if "k8s-app=kube-dns" in args:
            return _cp(stdout=json.dumps(coredns_pods))
        return _cp(stdout=json.dumps({"items": []}))

    with patch.object(m, "_kubectl", side_effect=_kubectl_router):
        m.check_system_pods_running("ctx")  # no raise (kube-proxy absence is non-fatal)


def test_system_pods_running_raises_when_coredns_missing():
    with patch.object(m, "_kubectl", return_value=_cp(stdout=json.dumps({"items": []}))):
        with pytest.raises(RuntimeError, match="No CoreDNS pods found"):
            m.check_system_pods_running("ctx")


def test_system_pods_running_raises_when_coredns_not_ready():
    coredns_pods = {"items": [{
        "metadata": {"name": "coredns-1"},
        "status": {"phase": "Pending", "conditions": []},
    }]}

    def _kubectl_router(*args, **kwargs):
        if "k8s-app=kube-dns" in args:
            return _cp(stdout=json.dumps(coredns_pods))
        return _cp(stdout=json.dumps({"items": []}))

    with patch.object(m, "_kubectl", side_effect=_kubectl_router):
        with pytest.raises(RuntimeError, match="not Ready in kube-system"):
            m.check_system_pods_running("ctx")


# ── _get_pods_for_deployment / _snapshot_pod_health ─────────────────────────

def test_get_pods_for_deployment_resolves_via_label_selector():
    dep = {"spec": {"selector": {"matchLabels": {"app": "x"}}}}
    pods = {"items": [{"metadata": {"name": "p1"}}]}

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "deployment"):
            return _cp(stdout=json.dumps(dep))
        if args[:2] == ("get", "pods"):
            return _cp(stdout=json.dumps(pods))
        return _cp()

    with patch.object(m, "_kubectl", side_effect=_kubectl_router):
        result = m._get_pods_for_deployment("ctx", "ns", "dep")
    assert result == [{"metadata": {"name": "p1"}}]


def test_get_pods_for_deployment_falls_back_to_owning_deployment():
    def _kubectl_router(*args, **kwargs):
        if "owner-dep" in args and args[:2] == ("get", "deployment"):
            dep = {"spec": {"selector": {"matchLabels": {"app": "x"}}}}
            return _cp(stdout=json.dumps(dep))
        if args[:2] == ("get", "pods") and "app=x" in args:
            return _cp(stdout=json.dumps({"items": [{"metadata": {"name": "p1"}}]}))
        return _cp(returncode=1, stderr="not found")

    with patch.object(m, "_kubectl", side_effect=_kubectl_router):
        result = m._get_pods_for_deployment("ctx", "ns", "gone-pod", owning_deployment="owner-dep")
    assert result == [{"metadata": {"name": "p1"}}]


def test_snapshot_pod_health_captures_restarts_and_waiting_reason():
    pods = [{
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "False"}],
            "containerStatuses": [{"restartCount": 4, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}],
        },
    }]
    snap = m._snapshot_pod_health(pods)
    assert snap["p1"]["ready"] is False
    assert snap["p1"]["restarts"] == 4
    assert snap["p1"]["waiting_reason"] == "CrashLoopBackOff"


# ── check_app_stability ──────────────────────────────────────────────────────

def test_check_app_stability_healthy_when_all_ready_no_restarts():
    pods = [{
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"restartCount": 0, "state": {"running": {}}}],
        },
    }]
    with patch.object(m, "_get_pods_for_deployment", return_value=pods):
        healthy, detail = m.check_app_stability("ctx", "ns", "dep", stability_secs=0)
    assert healthy is True
    assert detail == "HEALTHY"


def test_check_app_stability_unhealthy_when_no_pods_found():
    with patch.object(m, "_get_pods_for_deployment", return_value=[]):
        healthy, detail = m.check_app_stability("ctx", "ns", "dep", stability_secs=0)
    assert healthy is False
    assert "No pods found" in detail


def test_check_app_stability_detects_crashloop():
    pods = [{
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "False"}],
            "containerStatuses": [{"restartCount": 5, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}],
        },
    }]
    with patch.object(m, "_get_pods_for_deployment", return_value=pods):
        healthy, detail = m.check_app_stability("ctx", "ns", "dep", stability_secs=0)
    assert healthy is False
    assert "CrashLoopBackOff" in detail


def test_check_app_stability_waits_full_window_when_restarts_detected():
    pods0 = [{
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"restartCount": 1, "state": {"running": {}}}],
        },
    }]
    pods1 = [{
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"restartCount": 3, "state": {"running": {}}}],
        },
    }]
    with patch.object(m, "_get_pods_for_deployment", side_effect=[pods0, pods1]), \
         patch.object(m.time, "sleep", lambda *_a, **_k: None):
        healthy, detail = m.check_app_stability("ctx", "ns", "dep", stability_secs=30)
    assert healthy is False
    assert "Restarts increasing" in detail


# ── probe_aks_target_healthy ─────────────────────────────────────────────────

def test_probe_aks_target_healthy_checks_cluster_when_no_namespace():
    with patch.object(m, "check_nodes_ready", return_value=None), \
         patch.object(m, "check_system_pods_running", return_value=None):
        assert m.probe_aks_target_healthy("ctx") is True


def test_probe_aks_target_healthy_false_when_cluster_check_fails():
    with patch.object(m, "check_nodes_ready", side_effect=RuntimeError("no nodes ready")):
        assert m.probe_aks_target_healthy("ctx") is False


def test_probe_aks_target_healthy_false_when_replica_floor_fails():
    with patch.object(m, "check_deployment_replica_floor", side_effect=RuntimeError("not enough replicas")):
        assert m.probe_aks_target_healthy("ctx", "ns", "dep") is False


def test_probe_aks_target_healthy_delegates_to_app_stability():
    with patch.object(m, "check_deployment_replica_floor", return_value=None), \
         patch.object(m, "check_app_stability", return_value=(True, "HEALTHY")):
        assert m.probe_aks_target_healthy("ctx", "ns", "dep") is True


# ── verify_rollback_health ───────────────────────────────────────────────────

def test_verify_rollback_health_skips_on_dry_run():
    assert m.verify_rollback_health("ctx", "ns", "dep", dry_run="true") is True


def test_verify_rollback_health_raises_when_target_still_unhealthy():
    with patch.object(m, "check_app_stability", return_value=(False, "CrashLoopBackOff: p1")):
        with pytest.raises(RuntimeError, match="still not healthy"):
            m.verify_rollback_health("ctx", "ns", "dep")


def test_verify_rollback_health_passes_when_target_healthy():
    with patch.object(m, "check_app_stability", return_value=(True, "HEALTHY")):
        assert m.verify_rollback_health("ctx", "ns", "dep") is True


def test_verify_rollback_health_raises_on_cluster_level_failure():
    with patch.object(m, "check_nodes_ready", side_effect=RuntimeError("nodes not ready")):
        with pytest.raises(RuntimeError, match="manual intervention required"):
            m.verify_rollback_health("ctx")
