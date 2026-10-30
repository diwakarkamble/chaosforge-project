"""
Direct unit tests for standalone helper/check functions in
actions/aks_safety_checks.py (separate from tests/test_aks_target_reporting.py,
which owns targeting/reporting-focused tests). Covers: check_protected_namespace,
check_deployment_replica_floor, check_pdb_allows_disruption,
check_chaos_mesh_running, check_nodes_ready, check_system_pods_running,
_get_pods_for_deployment, _snapshot_pod_health, _is_true, and
_label_selector_matches.
"""

import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety as aks_safety_checks,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ── _is_true ──────────────────────────────────────────────────────────────

def test_is_true_recognizes_truthy_and_falsy():
    assert aks_safety_checks._is_true("true") is True
    assert aks_safety_checks._is_true("YES") is True
    assert aks_safety_checks._is_true("false") is False
    assert aks_safety_checks._is_true("") is False


# ── check_protected_namespace ─────────────────────────────────────────────

def test_check_protected_namespace_raises_for_kube_system():
    with pytest.raises(RuntimeError, match="protected"):
        aks_safety_checks.check_protected_namespace("kube-system")


def test_check_protected_namespace_passes_for_normal_namespace():
    aks_safety_checks.check_protected_namespace("my-app-ns")  # should not raise


def test_check_protected_namespace_passes_for_empty():
    aks_safety_checks.check_protected_namespace("")  # should not raise


# ── check_deployment_replica_floor ────────────────────────────────────────

def test_replica_floor_passes_for_healthy_deployment():
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2}}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        aks_safety_checks.check_deployment_replica_floor("ctx", "ns", "dep-a")  # no raise


def test_replica_floor_raises_when_desired_below_minimum():
    dep = {"spec": {"replicas": 1}, "status": {"readyReplicas": 1}}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        with pytest.raises(RuntimeError, match="desired replica"):
            aks_safety_checks.check_deployment_replica_floor("ctx", "ns", "dep-a", min_replicas=2)


def test_replica_floor_raises_when_ready_below_minimum():
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 1}}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        with pytest.raises(RuntimeError, match="ready replica"):
            aks_safety_checks.check_deployment_replica_floor("ctx", "ns", "dep-a", min_replicas=2)


def test_replica_floor_falls_back_to_standalone_pod():
    pod = {"status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}
    responses = [_cp(returncode=1, stderr="not found"), _cp(stdout=json.dumps(pod))]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        with pytest.raises(RuntimeError, match="standalone pod"):
            aks_safety_checks.check_deployment_replica_floor("ctx", "ns", "pod-a", min_replicas=2)


def test_replica_floor_falls_back_to_owning_deployment_when_pod_gone():
    owning_dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2}}
    responses = [
        _cp(returncode=1, stderr="not found"),   # deployment lookup for pod name fails
        _cp(returncode=1, stderr="not found"),   # pod lookup also fails (pod is gone)
        _cp(stdout=json.dumps(owning_dep)),      # recursive call resolves owning deployment
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        aks_safety_checks.check_deployment_replica_floor(
            "ctx", "ns", "old-pod-name", owning_deployment="owning-dep",
        )  # should not raise


# ── check_pdb_allows_disruption ───────────────────────────────────────────

def test_pdb_check_passes_without_label_key_or_val():
    aks_safety_checks.check_pdb_allows_disruption("ctx", "ns", "", "")  # no raise


def test_pdb_check_raises_when_zero_disruptions_allowed():
    pdbs = {"items": [{
        "metadata": {"name": "pdb-a"},
        "spec": {"selector": {"matchLabels": {"app": "x"}}},
        "status": {"disruptionsAllowed": 0, "currentHealthy": 1, "desiredHealthy": 2},
    }]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pdbs))):
        with pytest.raises(RuntimeError, match="allows 0 disruptions"):
            aks_safety_checks.check_pdb_allows_disruption("ctx", "ns", "app", "x")


def test_pdb_check_passes_when_no_matching_pdb():
    pdbs = {"items": [{
        "metadata": {"name": "pdb-a"},
        "spec": {"selector": {"matchLabels": {"app": "other"}}},
        "status": {"disruptionsAllowed": 0},
    }]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pdbs))):
        aks_safety_checks.check_pdb_allows_disruption("ctx", "ns", "app", "x")  # no raise


# ── check_chaos_mesh_running ───────────────────────────────────────────────

def test_chaos_mesh_running_passes_when_controller_ready():
    pods = {"items": [{
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        "metadata": {"name": "chaos-controller-1"},
    }]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pods))):
        aks_safety_checks.check_chaos_mesh_running("ctx")  # no raise


def test_chaos_mesh_running_raises_when_not_ready():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout='{"items": []}')):
        with pytest.raises(RuntimeError, match="not running or not ready"):
            aks_safety_checks.check_chaos_mesh_running("ctx")


# ── check_nodes_ready ──────────────────────────────────────────────────────

def test_check_nodes_ready_passes_with_enough_ready_workers():
    nodes = {"items": [
        {"spec": {}, "status": {"conditions": [{"type": "Ready", "status": "True"}]}},
    ]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(nodes))):
        aks_safety_checks.check_nodes_ready("ctx", min_ready=1)  # no raise


def test_check_nodes_ready_excludes_control_plane_nodes():
    nodes = {"items": [
        {"spec": {"taints": [{"key": "node-role.kubernetes.io/control-plane"}]},
         "status": {"conditions": [{"type": "Ready", "status": "True"}]}},
    ]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(nodes))):
        with pytest.raises(RuntimeError, match="worker node"):
            aks_safety_checks.check_nodes_ready("ctx", min_ready=1)


def test_check_nodes_ready_raises_on_kubectl_failure():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(returncode=1, stderr="down")):
        with pytest.raises(RuntimeError, match="Could not list nodes"):
            aks_safety_checks.check_nodes_ready("ctx")


# ── check_system_pods_running ──────────────────────────────────────────────

def test_system_pods_running_passes_when_coredns_ready():
    coredns_pods = {"items": [{
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}
    }]}
    kube_proxy_empty = {"items": []}
    responses = [_cp(stdout=json.dumps(coredns_pods))] + [_cp(stdout=json.dumps(kube_proxy_empty))] * 2
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        aks_safety_checks.check_system_pods_running("ctx")  # no raise (kube-proxy is best-effort)


def test_system_pods_running_raises_when_coredns_missing():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout='{"items": []}')):
        with pytest.raises(RuntimeError, match="No CoreDNS pods found"):
            aks_safety_checks.check_system_pods_running("ctx")


# ── _get_pods_for_deployment ───────────────────────────────────────────────

def test_get_pods_for_deployment_via_label_selector():
    dep = {"spec": {"selector": {"matchLabels": {"app": "x"}}}}
    pods = {"items": [{"metadata": {"name": "p1"}}]}
    responses = [_cp(stdout=json.dumps(dep)), _cp(stdout=json.dumps(pods))]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        result = aks_safety_checks._get_pods_for_deployment("ctx", "ns", "dep-a")
    assert result == pods["items"]


def test_get_pods_for_deployment_falls_back_to_single_pod():
    pod = {"metadata": {"name": "pod-a"}}
    responses = [_cp(returncode=1), _cp(stdout=json.dumps(pod))]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        result = aks_safety_checks._get_pods_for_deployment("ctx", "ns", "pod-a")
    assert result == [pod]


def test_get_pods_for_deployment_returns_empty_when_all_lookups_fail():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(returncode=1)):
        result = aks_safety_checks._get_pods_for_deployment("ctx", "ns", "gone-pod")
    assert result == []


# ── _label_selector_matches ────────────────────────────────────────────────

def test_label_selector_matches_labels():
    selector = {"matchLabels": {"app": "x"}}
    assert aks_safety_checks._label_selector_matches(selector, {"app": "x"}) is True
    assert aks_safety_checks._label_selector_matches(selector, {"app": "y"}) is False


def test_label_selector_matches_expressions_in_operator():
    selector = {"matchExpressions": [{"key": "app", "operator": "In", "values": ["x", "y"]}]}
    assert aks_safety_checks._label_selector_matches(selector, {"app": "x"}) is True
    assert aks_safety_checks._label_selector_matches(selector, {"app": "z"}) is False


def test_label_selector_matches_expressions_exists_operator():
    selector = {"matchExpressions": [{"key": "app", "operator": "Exists"}]}
    assert aks_safety_checks._label_selector_matches(selector, {"app": "x"}) is True
    assert aks_safety_checks._label_selector_matches(selector, {}) is False


# ── _snapshot_pod_health ────────────────────────────────────────────────────

def test_snapshot_pod_health_running_ready_no_restarts():
    pods = [{
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"restartCount": 0, "state": {"running": {}}}],
        },
    }]
    snap = aks_safety_checks._snapshot_pod_health(pods)
    assert snap["p1"] == {
        "ready": True, "phase": "Running", "container_state": "Running",
        "waiting_reason": "", "restarts": 0,
    }


def test_snapshot_pod_health_waiting_crashloop():
    pods = [{
        "metadata": {"name": "p2"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "False"}],
            "containerStatuses": [{
                "restartCount": 5,
                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
            }],
        },
    }]
    snap = aks_safety_checks._snapshot_pod_health(pods)
    assert snap["p2"]["ready"] is False
    assert snap["p2"]["container_state"] == "Waiting"
    assert snap["p2"]["waiting_reason"] == "CrashLoopBackOff"
    assert snap["p2"]["restarts"] == 5


def test_snapshot_pod_health_terminated_state():
    pods = [{
        "metadata": {"name": "p3"},
        "status": {
            "phase": "Succeeded",
            "conditions": [],
            "containerStatuses": [{"restartCount": 0, "state": {"terminated": {}}}],
        },
    }]
    snap = aks_safety_checks._snapshot_pod_health(pods)
    assert snap["p3"]["container_state"] == "Terminated"


# ── check_app_stability ─────────────────────────────────────────────────────

def _healthy_pod(name="p1"):
    return {
        "metadata": {"name": name},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"restartCount": 0, "state": {"running": {}}}],
        },
    }


def test_check_app_stability_returns_false_when_no_pods_found():
    with patch.object(aks_safety_checks, "_get_pods_for_deployment", return_value=[]):
        healthy, detail = aks_safety_checks.check_app_stability("ctx", "ns", "dep-a")
    assert healthy is False
    assert "No pods found" in detail


def test_check_app_stability_healthy_with_no_restarts():
    with patch.object(aks_safety_checks, "_get_pods_for_deployment", return_value=[_healthy_pod()]):
        healthy, detail = aks_safety_checks.check_app_stability("ctx", "ns", "dep-a")
    assert healthy is True
    assert detail == "HEALTHY"


def test_check_app_stability_unhealthy_when_not_ready():
    unready_pod = {
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "False"}],
            "containerStatuses": [{"restartCount": 0, "state": {"running": {}}}],
        },
    }
    with patch.object(aks_safety_checks, "_get_pods_for_deployment", return_value=[unready_pod]):
        healthy, detail = aks_safety_checks.check_app_stability("ctx", "ns", "dep-a")
    assert healthy is False
    assert "Ready: 0/1" in detail


def test_check_app_stability_waits_out_stability_window_on_restarts(monkeypatch):
    restarted_pod = {
        "metadata": {"name": "p1"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"restartCount": 1, "state": {"running": {}}}],
        },
    }
    monkeypatch.setattr(aks_safety_checks.time, "sleep", lambda *_a, **_k: None)
    with patch.object(aks_safety_checks, "_get_pods_for_deployment", return_value=[restarted_pod]):
        healthy, detail = aks_safety_checks.check_app_stability("ctx", "ns", "dep-a", stability_secs=1)
    assert healthy is True
    assert detail == "HEALTHY"


# ── probe_aks_target_healthy ─────────────────────────────────────────────────

def test_probe_healthy_cluster_level_when_no_namespace_deployment():
    with patch.object(aks_safety_checks, "check_nodes_ready"), \
         patch.object(aks_safety_checks, "check_system_pods_running"):
        assert aks_safety_checks.probe_aks_target_healthy("ctx") is True


def test_probe_unhealthy_cluster_level_when_check_fails():
    with patch.object(aks_safety_checks, "check_nodes_ready", side_effect=RuntimeError("down")):
        assert aks_safety_checks.probe_aks_target_healthy("ctx") is False


def test_probe_unhealthy_when_replica_floor_fails():
    with patch.object(aks_safety_checks, "check_deployment_replica_floor",
                       side_effect=RuntimeError("too few")):
        result = aks_safety_checks.probe_aks_target_healthy("ctx", namespace="ns", deployment="dep-a")
    assert result is False


def test_probe_healthy_when_app_stable():
    with patch.object(aks_safety_checks, "check_deployment_replica_floor"), \
         patch.object(aks_safety_checks, "check_app_stability", return_value=(True, "HEALTHY")):
        result = aks_safety_checks.probe_aks_target_healthy("ctx", namespace="ns", deployment="dep-a")
    assert result is True


# ── verify_rollback_health ───────────────────────────────────────────────────

def test_verify_rollback_health_skips_on_dry_run():
    assert aks_safety_checks.verify_rollback_health("ctx", dry_run="true") is True


def test_verify_rollback_health_raises_when_target_unhealthy():
    with patch.object(aks_safety_checks, "check_app_stability", return_value=(False, "bad")):
        with pytest.raises(RuntimeError, match="still not healthy"):
            aks_safety_checks.verify_rollback_health("ctx", namespace="ns", deployment="dep-a")


def test_verify_rollback_health_passes_when_target_healthy():
    with patch.object(aks_safety_checks, "check_app_stability", return_value=(True, "HEALTHY")):
        assert aks_safety_checks.verify_rollback_health(
            "ctx", namespace="ns", deployment="dep-a",
        ) is True


def test_verify_rollback_health_cluster_level_raises_on_failure():
    with patch.object(aks_safety_checks, "check_nodes_ready", side_effect=RuntimeError("nope")):
        with pytest.raises(RuntimeError, match="cluster-level health checks failed"):
            aks_safety_checks.verify_rollback_health("ctx")


def test_verify_rollback_health_cluster_level_passes():
    with patch.object(aks_safety_checks, "check_nodes_ready"), \
         patch.object(aks_safety_checks, "check_system_pods_running"):
        assert aks_safety_checks.verify_rollback_health("ctx") is True


# ── _list_pods ────────────────────────────────────────────────────────────

def test_list_pods_uses_python_client_for_pod_kill():
    with patch("chaosforge.providers.azure.components.aks.kubernetes.get_pods", return_value=([{"metadata": {"name": "p1"}}], None)):
        pods, err = aks_safety_checks._list_pods("ns", "app=x", "ctx", experiment_id="aks-pod-kill")
    assert err is None
    assert pods == [{"metadata": {"name": "p1"}}]


def test_list_pods_uses_kubectl_fallback_for_other_experiments():
    pods_json = json.dumps({"items": [{"metadata": {"name": "p1"}}]})
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=pods_json)):
        pods, err = aks_safety_checks._list_pods("ns", "app=x", "ctx", experiment_id="aks-network-delay")
    assert err is None
    assert pods == [{"metadata": {"name": "p1"}}]


def test_list_pods_returns_error_on_kubectl_failure():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(returncode=1, stderr="boom")):
        pods, err = aks_safety_checks._list_pods("ns", "app=x", "ctx")
    assert pods is None
    assert "boom" in err


# ── _find_svc_name ───────────────────────────────────────────────────────────

def test_find_svc_name_matches_via_selector():
    svcs = json.dumps({"items": [{
        "metadata": {"name": "svc-a"},
        "spec": {"selector": {"app": "x"}},
    }]})
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=svcs)):
        name, found = aks_safety_checks._find_svc_name("ns", "app", "x", "fallback-svc", "ctx")
    assert name == "svc-a"
    assert found is True


def test_find_svc_name_falls_back_to_label_val_as_name():
    responses = [_cp(stdout='{"items": []}'), _cp(returncode=0)]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        name, found = aks_safety_checks._find_svc_name("ns", "app", "my-svc", "fallback-svc", "ctx")
    assert name == "my-svc"
    assert found is True


def test_find_svc_name_returns_fallback_when_not_found():
    responses = [_cp(returncode=1), _cp(returncode=1)]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        name, found = aks_safety_checks._find_svc_name("ns", "app", "x", "fallback-svc", "ctx")
    assert name == "fallback-svc"
    assert found is False


# ── build_steady_state_checks: universal "Nodes Ready" / "System Pods" ─────

def test_steady_state_nodes_ready_passes_and_lists_workers():
    nodes = {"items": [
        {"metadata": {"name": "node-1"}, "spec": {},
         "status": {"conditions": [{"type": "Ready", "status": "True"}]}},
        {"metadata": {"name": "cp-1"},
         "spec": {"taints": [{"key": "node-role.kubernetes.io/control-plane"}]},
         "status": {"conditions": [{"type": "Ready", "status": "True"}]}},
    ]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(nodes))):
        checks = aks_safety_checks.build_steady_state_checks("ctx")
        passed, detail = checks["Nodes Ready"]()
    assert passed is True
    assert "node-1" in detail
    assert "control-plane=1" in detail


def test_steady_state_nodes_ready_fails_when_none_ready():
    nodes = {"items": [
        {"metadata": {"name": "node-1"}, "spec": {},
         "status": {"conditions": [{"type": "Ready", "status": "False"}]}},
    ]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(nodes))):
        checks = aks_safety_checks.build_steady_state_checks("ctx")
        passed, detail = checks["Nodes Ready"]()
    assert passed is False
    assert "NOT Ready" in detail


def test_steady_state_nodes_ready_fails_on_kubectl_error():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(returncode=1, stderr="boom")):
        checks = aks_safety_checks.build_steady_state_checks("ctx")
        passed, detail = checks["Nodes Ready"]()
    assert passed is False
    assert "kubectl get nodes failed" in detail


def test_steady_state_system_pods_passes_when_both_ready():
    def fake_kubectl(*args, **kwargs):
        label = args[args.index("-l") + 1] if "-l" in args else ""
        if "kube-dns" in label:
            pods = {"items": [{"metadata": {"name": "coredns-1"}, "status": {
                "phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}]}
        else:
            pods = {"items": [{"metadata": {"name": "kube-proxy-1"}, "status": {
                "phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}]}
        return _cp(stdout=json.dumps(pods))

    with patch.object(aks_safety_checks, "_kubectl", side_effect=fake_kubectl):
        checks = aks_safety_checks.build_steady_state_checks("ctx")
        passed, detail = checks["System Pods (CoreDNS, kube-proxy)"]()
    assert passed is True
    assert "CoreDNS" in detail and "kube-proxy" in detail


def test_steady_state_system_pods_fails_when_coredns_missing():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout='{"items": []}')):
        checks = aks_safety_checks.build_steady_state_checks("ctx")
        passed, detail = checks["System Pods (CoreDNS, kube-proxy)"]()
    assert passed is False


def test_steady_state_system_pods_handles_kubectl_query_error():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(returncode=1, stderr="down")):
        checks = aks_safety_checks.build_steady_state_checks("ctx")
        passed, detail = checks["System Pods (CoreDNS, kube-proxy)"]()
    assert passed is False
    assert "kubectl query failed" in detail


# ── build_steady_state_checks: deployment/pod target "Replica Floor" ───────

def test_steady_state_replica_floor_passes_for_deployment():
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2, "availableReplicas": 2}}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        checks = aks_safety_checks.build_steady_state_checks(
            "ctx", namespace="ns", deployment="dep-a",
        )
        passed, detail = checks["Replica Floor (dep-a)"]()
    assert passed is True
    assert "readyReplicas" in detail or "ready" in detail.lower()
