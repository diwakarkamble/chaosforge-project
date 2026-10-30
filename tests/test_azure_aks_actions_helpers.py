"""
Direct unit tests for pure/small helper functions in actions/azure_aks_actions.py.

Separate from tests/test_aks_target_reporting.py (which owns the
targeting/reporting-focused tests) — this file targets standalone helpers:
_normalize_time_offset, _state_file, _http_chaos_sentinel, _is_true,
_kubectl_json, and the node-level kubectl helpers (_node_pod_count,
_node_is_ready, _node_is_schedulable, _check_pdbs, _pending_pods_exist,
_get_node_names, _get_unhealthy_pods, _get_deployment_readiness,
_get_node_conditions).
"""

from subprocess import CompletedProcess
from unittest.mock import patch

import chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor as azure_aks_actions

# ── _normalize_time_offset ───────────────────────────────────────────────────

def test_normalize_time_offset_rejects_invalid_format():
    assert azure_aks_actions._normalize_time_offset("aks-clock-skew-forward", "abc") is None


def test_normalize_time_offset_forward_requires_plus_sign():
    assert azure_aks_actions._normalize_time_offset("aks-clock-skew-forward", "-5m") is None
    assert azure_aks_actions._normalize_time_offset("aks-clock-skew-forward", "+5m") == "+5m"


def test_normalize_time_offset_backward_requires_minus_sign():
    assert azure_aks_actions._normalize_time_offset("aks-clock-skew-backward", "+5m") is None
    assert azure_aks_actions._normalize_time_offset("aks-clock-skew-backward", "-5m") == "-5m"


def test_normalize_time_offset_adds_sign_when_missing():
    assert azure_aks_actions._normalize_time_offset("aks-clock-skew-forward", "5m") == "+5m"
    assert azure_aks_actions._normalize_time_offset("aks-clock-skew-backward", "5m") == "-5m"


# ── _state_file / _http_chaos_sentinel ───────────────────────────────────────

def test_state_file_sanitizes_experiment_id():
    path = azure_aks_actions._state_file("aks-packet-loss!!")
    assert "aks-packet-loss" in path
    assert "!" not in path


def test_http_chaos_sentinel_sanitizes_all_components():
    path = azure_aks_actions._http_chaos_sentinel("aks-http-delay", "My_NS", "My_Dep")
    assert "aks-http-delay" in path
    # The fixed template text ("aks_http_chaos_setup_") legitimately contains
    # underscores; only the sanitized experiment_id/namespace/deployment
    # components should have theirs stripped.
    assert "myns" in path
    assert "mydep" in path
    assert "my_ns" not in path
    assert "my_dep" not in path


# ── _is_true ──────────────────────────────────────────────────────────────

def test_is_true_recognizes_truthy_strings():
    for v in ("true", "True", "1", "yes", "y", " YES "):
        assert azure_aks_actions._is_true(v) is True


def test_is_true_recognizes_falsy_strings():
    for v in ("false", "0", "no", "", "n"):
        assert azure_aks_actions._is_true(v) is False


# ── _kubectl_json ─────────────────────────────────────────────────────────

def test_kubectl_json_returns_parsed_dict_on_success():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"a": 1}', stderr="")):
        result = azure_aks_actions._kubectl_json(["kubectl", "get", "pods"])
    assert result == {"a": 1}


def test_kubectl_json_returns_none_on_failure():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="boom")):
        result = azure_aks_actions._kubectl_json(["kubectl", "get", "pods"])
    assert result is None


def test_kubectl_json_returns_none_on_bad_json():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="not json", stderr="")):
        result = azure_aks_actions._kubectl_json(["kubectl", "get", "pods"])
    assert result is None


# ── node helpers ──────────────────────────────────────────────────────────

def test_node_pod_count_excludes_daemonset_pods():
    pods = {"items": [
        {"metadata": {"ownerReferences": [{"kind": "ReplicaSet"}]}},
        {"metadata": {"ownerReferences": [{"kind": "DaemonSet"}]}},
    ]}
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=pods):
        assert azure_aks_actions._node_pod_count("node-a") == 1


def test_node_pod_count_returns_zero_when_no_data():
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=None):
        assert azure_aks_actions._node_pod_count("node-a") == 0


def test_node_is_ready_true():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="True", stderr="")):
        assert azure_aks_actions._node_is_ready("node-a") is True


def test_node_is_ready_false():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="False", stderr="")):
        assert azure_aks_actions._node_is_ready("node-a") is False


def test_node_is_schedulable_true_when_not_cordoned():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="", stderr="")):
        assert azure_aks_actions._node_is_schedulable("node-a") is True


def test_node_is_schedulable_false_when_cordoned():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="true", stderr="")):
        assert azure_aks_actions._node_is_schedulable("node-a") is False


def test_check_pdbs_returns_blocking_names():
    pdbs = {"items": [
        {"metadata": {"name": "pdb-a"}, "status": {"disruptionsAllowed": 0}},
        {"metadata": {"name": "pdb-b"}, "status": {"disruptionsAllowed": 1}},
    ]}
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=pdbs):
        assert azure_aks_actions._check_pdbs() == ["pdb-a"]


def test_check_pdbs_returns_empty_when_no_data():
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=None):
        assert azure_aks_actions._check_pdbs("ns") == []


def test_pending_pods_exist_excludes_daemonsets():
    pods = {"items": [
        {"metadata": {"name": "p1", "ownerReferences": []}},
        {"metadata": {"name": "p2", "ownerReferences": [{"kind": "DaemonSet"}]}},
    ]}
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=pods):
        assert azure_aks_actions._pending_pods_exist() == ["p1"]


def test_get_node_names_returns_set():
    with patch.object(azure_aks_actions, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="node-a node-b", stderr="")):
        assert azure_aks_actions._get_node_names() == {"node-a", "node-b"}


def test_get_unhealthy_pods_detects_crashloop_despite_running_phase():
    pods = {"items": [{
        "metadata": {"name": "p1", "namespace": "ns", "ownerReferences": []},
        "status": {
            "phase": "Running",
            "containerStatuses": [{"state": {"waiting": {"reason": "CrashLoopBackOff"}}}],
        },
    }]}
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=pods):
        result = azure_aks_actions._get_unhealthy_pods()
    assert result == [("p1", "ns", "CrashLoopBackOff")]


def test_get_unhealthy_pods_skips_healthy_running_pods():
    pods = {"items": [{
        "metadata": {"name": "p1", "namespace": "ns", "ownerReferences": []},
        "status": {"phase": "Running", "containerStatuses": [{"state": {"running": {}}}]},
    }]}
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=pods):
        assert azure_aks_actions._get_unhealthy_pods() == []


def test_get_deployment_readiness_returns_tuples():
    deps = {"items": [{
        "metadata": {"name": "dep-a", "namespace": "ns"},
        "spec": {"replicas": 3}, "status": {"readyReplicas": 2},
    }]}
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=deps):
        assert azure_aks_actions._get_deployment_readiness() == [("dep-a", "ns", 2, 3)]


def test_get_node_conditions_returns_dict():
    node = {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=node):
        assert azure_aks_actions._get_node_conditions("node-a") == {"Ready": "True"}


def test_get_node_conditions_returns_empty_when_no_data():
    with patch.object(azure_aks_actions, "_kubectl_json", return_value=None):
        assert azure_aks_actions._get_node_conditions("node-a") == {}


# ── _extract_net_metrics ──────────────────────────────────────────────────

def test_extract_net_metrics_parses_all_known_fields():
    rows = [
        ("Measured RTT (ping)", "12 ms", ""),
        ("TCP RetransSegs", 5, ""),
        ("TCP DSACKRecv", 2, ""),
        ("Endpoints ready", "2 / 3", ""),
        ("Container restarts", 1, ""),
        ("Unhealthy probe events", "3 events", ""),
    ]
    vals = azure_aks_actions._extract_net_metrics(rows)
    assert vals["rtt_ms"] == 12.0
    assert vals["retrans"] == 5
    assert vals["dsack"] == 2
    assert vals["endpoints_ready"] == 2
    assert vals["endpoints_total"] == 3
    assert vals["restarts"] == 1
    assert vals["probe_failures"] == 3


def test_extract_net_metrics_ignores_malformed_rows():
    rows = [("TCP RetransSegs", "not-a-number", ""), ("short",)]
    assert azure_aks_actions._extract_net_metrics(rows) == {}


# ── _capture_missing_net_baseline ─────────────────────────────────────────

def test_capture_missing_net_baseline_only_fills_gaps():
    baseline = {"restarts": 3}
    azure_aks_actions._capture_missing_net_baseline(baseline, {"restarts": 9, "rtt_ms": 5.0})
    assert baseline == {"restarts": 3, "rtt_ms": 5.0}


# ── _probe_recovery_status ────────────────────────────────────────────────

def test_probe_recovery_status_returns_none_when_check_absent():
    assert azure_aks_actions._probe_recovery_status({}) is None


def test_probe_recovery_status_returns_none_when_skipped():
    result = {"Probe Failures Stopped (post)": {"passed": True, "detail": "skipping — no service"}}
    assert azure_aks_actions._probe_recovery_status(result) is None


def test_probe_recovery_status_returns_bool_when_measured():
    result = {"Probe Failures Stopped (post)": {"passed": False, "detail": "2 failures found"}}
    assert azure_aks_actions._probe_recovery_status(result) is False
