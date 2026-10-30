"""Closure-level coverage for delay, loss, and bandwidth pre-flight checks."""

import json
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _pods(restarts=2):
    return {"items": [{
        "metadata": {"name": "app-pod"},
        "status": {
            "phase": "Running",
            "containerStatuses": [{"restartCount": restarts}],
        },
    }]}


def _build(experiment_id):
    """Construct via safety so closures retain its public, late-bound seams."""
    return safety.build_steady_state_checks(
        "aks-context", namespace="app-ns", deployment="app", label_key="app",
        label_val="demo", experiment_id=experiment_id,
    )


def _network_check_names(checks):
    return [name for name in checks if name in {
        "NetworkChaos CRD Installed", "No Existing NetworkChaos",
        "No Existing tc-netem Rule", "No Existing tc Rule (tbf/netem)",
        "Service Endpoints (baseline)", "Probe Timeouts vs Delay (impact analysis)",
        "Probe Timeouts vs Packet Loss (impact analysis)",
        "Probe Timeouts vs Bandwidth Cap (impact analysis)",
        "Baseline HTTP Response Time", "Baseline Ping RTT",
        "Baseline Ping RTT (should stay stable)", "Baseline DNS Resolution",
        "Baseline DNS Resolution (UDP)", "Pod Restart Baseline",
        "TCP Retransmit Baseline (/proc/net/snmp)", "Baseline Throughput (KB/s)",
    }]


def _healthy_kubectl(*args, **_kwargs):
    if args[:3] == ("get", "crd", "networkchaoses.chaos-mesh.org"):
        return _cp("networkchaoses.chaos-mesh.org")
    if args[:2] == ("get", "networkchaos"):
        return _cp(json.dumps({"items": []}))
    if args[:2] == ("get", "pods"):
        return _cp(json.dumps(_pods()))
    if args[:2] == ("get", "endpoints"):
        return _cp(json.dumps({"subsets": [{"addresses": [{"ip": "10.0.0.8"}]}]}))
    if args[:2] == ("get", "deployment"):
        deployment = {"spec": {"template": {"spec": {"containers": [{
            "name": "app", "readinessProbe": {"timeoutSeconds": 3},
            "livenessProbe": {"timeoutSeconds": 4},
        }]}}}}
        return _cp(json.dumps(deployment))
    if args[:3] == ("get", "service", "kube-dns"):
        return _cp("10.0.0.10")
    if args[:1] == ("exec",):
        if "tc" in args:
            return _cp("qdisc fq_codel 0: dev eth0")
        if "nslookup" in args:
            return _cp("Name: app-service\nAddress: 10.0.0.8")
        if "ping" in args:
            return _cp("3 packets transmitted, 3 received")
        if "curl" in args:
            return _cp("0.012 1024")
        if "/proc/net/snmp" in args:
            return _cp("Tcp: RetransSegs\nTcp: 0")
    raise AssertionError(f"Unexpected kubectl call: {args}")


@pytest.mark.parametrize("experiment_id", [
    "aks-network-delay", "aks-packet-loss", "aks-bandwidth-limit",
])
def test_network_pre_checks_pass_with_healthy_baselines(experiment_id):
    checks = _build(experiment_id)
    kubectl = Mock(side_effect=_healthy_kubectl)

    # Patch after construction: each closure must resolve safety's seams on run.
    with patch.object(safety, "_kubectl", kubectl), \
         patch.object(safety, "_find_svc_name", return_value=("app-service", True)):
        results = {name: checks[name]() for name in _network_check_names(checks)}

    assert results
    assert all(passed for passed, _detail in results.values())
    assert kubectl.called


@pytest.mark.parametrize(("experiment_id", "check_name", "output"), [
    ("aks-network-delay", "No Existing tc-netem Rule", "qdisc netem 1: dev eth0"),
    ("aks-packet-loss", "No Existing tc-netem Rule", "qdisc netem 1: dev eth0"),
    ("aks-bandwidth-limit", "No Existing tc Rule (tbf/netem)", "qdisc tbf 1: dev eth0"),
])
def test_network_pre_checks_block_stale_traffic_control_rules(experiment_id, check_name, output):
    checks = _build(experiment_id)

    def kubectl(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _cp(json.dumps(_pods()))
        if args[:1] == ("exec",) and "tc" in args:
            return _cp(output)
        raise AssertionError(f"Unexpected kubectl call: {args}")

    with patch.object(safety, "_kubectl", side_effect=kubectl):
        passed, detail = checks[check_name]()

    assert passed is False
    assert "stale injection" in detail


def test_network_pre_checks_handle_crd_existing_and_endpoint_errors():
    checks = _build("aks-network-delay")
    live = {"items": [{
        "metadata": {"name": "live-chaos"},
        "status": {"conditions": [{"type": "AllInjected", "status": "True"}]},
    }]}

    def unavailable_crd(*_args, **_kwargs):
        return _cp(returncode=1, stderr="not found")

    with patch.object(safety, "_kubectl", side_effect=unavailable_crd):
        passed, detail = checks["NetworkChaos CRD Installed"]()
    assert passed is False
    assert "not installed" in detail

    with patch.object(safety, "_kubectl", return_value=_cp(json.dumps(live))):
        passed, detail = checks["No Existing NetworkChaos"]()
    assert passed is False
    assert "actively injecting" in detail

    with patch.object(safety, "_kubectl", return_value=_cp("not json")), \
         patch.object(safety, "_find_svc_name", return_value=("app-service", True)):
        passed, detail = checks["Service Endpoints (baseline)"]()
    assert passed is False
    assert "Could not parse endpoints JSON" in detail


def test_network_pre_checks_tolerate_unavailable_baselines_and_missing_service():
    checks = _build("aks-bandwidth-limit")

    def unavailable(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _cp(returncode=1)
        if args[:2] == ("get", "deployment"):
            return _cp(returncode=1)
        raise AssertionError(f"Unexpected kubectl call: {args}")

    with patch.object(safety, "_kubectl", side_effect=unavailable), \
         patch.object(safety, "_find_svc_name", return_value=("", False)):
        tc_passed, tc_detail = checks["No Existing tc Rule (tbf/netem)"]()
        probes_passed, probes_detail = checks["Probe Timeouts vs Bandwidth Cap (impact analysis)"]()
        restart_passed, restart_detail = checks["Pod Restart Baseline"]()
        http_passed, http_detail = checks["Baseline HTTP Response Time"]()
        dns_passed, dns_detail = checks["Baseline DNS Resolution"]()

    assert (tc_passed, probes_passed, restart_passed, http_passed, dns_passed) == (True,) * 5
    assert "skipping" in tc_detail
    assert "skipping" in probes_detail
    assert "skipping" in restart_detail
    assert "not applicable" in http_detail
    assert "no running pod - skipping" in dns_detail
