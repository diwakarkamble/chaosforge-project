"""Error-path coverage for post-rollback AKS network safety checks."""

import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_corruption_duplication_partition as corruption_post,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_delay_loss_bandwidth as delay_post,
)

EXPERIMENTS = (
    "aks-network-delay",
    "aks-packet-loss",
    "aks-bandwidth-limit",
    "aks-packet-corruption",
    "aks-packet-duplication",
    "aks-network-partition",
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _pods(restarts=0):
    return json.dumps({
        "items": [{
            "metadata": {"name": "app-pod"},
            "status": {
                "phase": "Running",
                "containerStatuses": [{"restartCount": restarts}],
            },
        }],
    })


def _build(experiment_id, responder, service=("app-service", True)):
    kubectl = Mock(side_effect=responder)
    common = (
        experiment_id, "aks-context", "app-ns", "app", "app", "demo",
        ("-l", "app=demo"), "-l app=demo",
    )
    dependencies = {
        "kubectl": lambda: kubectl,
        "find_svc_name": lambda: lambda *_args: service,
    }
    if experiment_id in {
        "aks-packet-corruption", "aks-packet-duplication", "aks-network-partition",
    }:
        checks = corruption_post.build_post_network_checks(
            *common,
            partition_ping_target=lambda: lambda _context: "10.0.0.53",
            **dependencies,
        )
    else:
        checks = delay_post.build_post_network_checks(*common, **dependencies)
    return checks, kubectl


@pytest.mark.parametrize("experiment_id", EXPERIMENTS)
def test_post_network_checks_tolerate_unavailable_kubectl(experiment_id):
    checks, kubectl = _build(
        experiment_id,
        lambda *_args, **_kwargs: _cp(returncode=1, stderr="cluster unavailable"),
    )

    results = {name: check() for name, check in checks.items()}

    assert results
    assert all(passed for passed, _detail in results.values())
    assert "query failed" in results["NetworkChaos CRD Cleaned Up"][1]
    assert "endpoint query failed" in results["Service Endpoints Restored"][1]
    assert "kubectl failed" in results["Restart Count Delta (post)"][1]
    assert any(call.args[:2] == ("get", "pods") for call in kubectl.call_args_list)


@pytest.mark.parametrize("experiment_id", EXPERIMENTS)
def test_post_network_checks_handle_malformed_kubectl_json(experiment_id):
    def malformed(*args, **_kwargs):
        if args[:2] in {("get", "pods"), ("get", "endpoints"), ("get", "events")}:
            return _cp("not-json")
        if args[:2] == ("get", "networkchaos"):
            return _cp("")
        if args[:2] == ("get", "service"):
            return _cp(returncode=1)
        raise AssertionError(f"Unexpected kubectl call: {args}")

    checks, _kubectl = _build(experiment_id, malformed)

    results = {name: check() for name, check in checks.items()}

    assert results["Service Endpoints Restored"][0] is False
    assert "Could not parse endpoints" in results["Service Endpoints Restored"][1]
    assert results["Probe Failures Stopped (post)"][0] is True
    assert "parse" in results["Probe Failures Stopped (post)"][1]
    assert results["Restart Count Delta (post)"][0] is True
    assert "parse failed" in results["Restart Count Delta (post)"][1]


@pytest.mark.parametrize("experiment_id", EXPERIMENTS)
def test_post_network_checks_skip_unavailable_in_pod_commands(experiment_id):
    def exec_unavailable(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _cp(_pods())
        if args[:2] == ("get", "networkchaos"):
            return _cp("")
        if args[:2] == ("get", "service"):
            return _cp("")
        if args[:2] == ("get", "endpoints"):
            return _cp(json.dumps({"subsets": [{"addresses": [{"ip": "10.0.0.8"}]}]}))
        if args[:2] == ("get", "events"):
            return _cp(json.dumps({"items": []}))
        if args[:1] == ("exec",):
            return _cp(returncode=127, stderr="command not found")
        raise AssertionError(f"Unexpected kubectl call: {args}")

    checks, kubectl = _build(experiment_id, exec_unavailable)

    results = {name: check() for name, check in checks.items()}

    assert all(passed for passed, _detail in results.values())
    traffic_control = next(name for name in checks if name.startswith(("tc-", "iptables")))
    assert "unavailable" in results[traffic_control][1]
    assert any(call.args[:1] == ("exec",) for call in kubectl.call_args_list)


@pytest.mark.parametrize("experiment_id", EXPERIMENTS)
def test_post_network_endpoint_check_skips_when_service_is_absent(experiment_id):
    checks, kubectl = _build(
        experiment_id,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("kubectl not expected")),
        service=("", False),
    )

    passed, detail = checks["Service Endpoints Restored"]()

    assert passed is True
    assert "No Service found" in detail
    assert "standalone pod" in detail
    kubectl.assert_not_called()


@pytest.mark.parametrize("experiment_id", EXPERIMENTS)
def test_post_network_endpoint_check_rejects_no_ready_addresses(experiment_id):
    checks, kubectl = _build(
        experiment_id,
        lambda *args, **_kwargs: _cp(json.dumps({"subsets": []}))
        if args[:2] == ("get", "endpoints")
        else (_ for _ in ()).throw(AssertionError(f"Unexpected kubectl call: {args}")),
    )

    passed, detail = checks["Service Endpoints Restored"]()

    assert passed is False
    assert "No ready endpoints" in detail
    assert kubectl.call_args.args[:2] == ("get", "endpoints")


@pytest.mark.parametrize("experiment_id", EXPERIMENTS)
def test_post_network_checks_parse_degraded_command_output(experiment_id):
    old_event = {
        "type": "Warning",
        "lastTimestamp": "2000-01-01T00:00:00Z",
        "reason": "NetworkNotReady",
        "message": "old network timeout",
        "involvedObject": {"name": "old-pod"},
    }
    invalid_event = {
        "type": "Normal",
        "lastTimestamp": "not-a-timestamp",
        "reason": "Pulled",
        "message": "container image ready",
        "involvedObject": {"name": "app-pod"},
    }

    def degraded(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _cp(_pods(restarts=6))
        if args[:2] == ("get", "networkchaos"):
            return _cp("")
        if args[:2] == ("get", "service"):
            return _cp(returncode=1)
        if args[:2] == ("get", "endpoints"):
            return _cp(json.dumps({"subsets": [{"addresses": [{"ip": "10.0.0.8"}]}]}))
        if args[:2] == ("get", "events"):
            if "reason=Unhealthy" in args:
                return _cp(json.dumps({"items": [old_event]}))
            return _cp(json.dumps({"items": [invalid_event, old_event]}))
        if args[:1] == ("exec",) and ("tc" in args or "iptables" in args):
            return _cp("qdisc fq_codel" if "tc" in args else "Chain INPUT")
        if args[:1] == ("exec",) and "ping" in args:
            return _cp("0% packet loss\nrtt = malformed")
        if args[:1] == ("exec",) and "nslookup" in args:
            return _cp("Name: app-service\nAddress: 10.0.0.8")
        if args[:1] == ("exec",) and "/proc/net/snmp" in args:
            return _cp("Tcp: RetransSegs Other\nTcp: 9")
        if args[:1] == ("exec",) and "/proc/net/netstat" in args:
            return _cp("TcpExt: TCPDSACKRecv Other\nTcpExt: 4")
        if args[:1] == ("exec",) and "curl" in args:
            return _cp("bytes elapsed unknown" if experiment_id == "aks-bandwidth-limit" else "unknown")
        raise AssertionError(f"Unexpected kubectl call: {args}")

    checks, _kubectl = _build(experiment_id, degraded)

    results = {name: check() for name, check in checks.items()}

    assert results["Probe Failures Stopped (post)"][0] is True
    assert "no Unhealthy events" in results["Probe Failures Stopped (post)"][1]
    assert results["No Network Warning Events (post)"][0] is True
    assert "no network-related Warning events" in results["No Network Warning Events (post)"][1]
    assert results["Restart Count Delta (post)"][0] is True
    assert "High restart" in results["Restart Count Delta (post)"][1]
