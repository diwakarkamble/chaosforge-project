"""Unit coverage for the late-bound post-rollback network check factory."""

import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_corruption_duplication_partition as post_network,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _pod(restarts=0):
    return {
        "items": [{
            "metadata": {"name": "pod-a"},
            "status": {
                "phase": "Running",
                "containerStatuses": [{"restartCount": restarts}],
            },
        }],
    }


def _router(experiment_id, unhealthy):
    """Return deterministic kubectl output without invoking a cluster."""
    def kubectl(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _cp(json.dumps(_pod(5 if unhealthy else 0)))
        if args[:2] == ("get", "networkchaos"):
            return _cp("stale-networkchaos\n" if unhealthy else "")
        if args[:2] == ("delete", "networkchaos"):
            return _cp()
        if args[:2] == ("get", "service"):
            return _cp("10.0.0.10")
        if args[:2] == ("get", "endpoints"):
            endpoints = {"subsets": [{
                "addresses": [{"ip": "10.0.0.1"}],
                "notReadyAddresses": [{"ip": "10.0.0.2"}] if unhealthy else [],
            }]}
            return _cp(json.dumps(endpoints))
        if args[:2] == ("get", "events"):
            if "reason=Unhealthy" in args:
                events = [{"involvedObject": {"name": "pod-a"}, "message": "probe failed"}]
            else:
                events = [{
                    "type": "Warning", "reason": "NetworkNotReady",
                    "involvedObject": {"name": "pod-a"}, "message": "network timeout",
                }]
            return _cp(json.dumps({"items": events if unhealthy else []}))
        if args[:1] == ("exec",) and "tc" in args:
            return _cp("qdisc netem 1: dev eth0" if unhealthy else "qdisc fq_codel 0: dev eth0")
        if args[:1] == ("exec",) and "iptables" in args:
            return _cp("Chain CHAOS-TEST" if unhealthy else "Chain INPUT")
        if args[:1] == ("exec",) and "ping" in args:
            if experiment_id == "aks-packet-duplication" and unhealthy:
                return _cp("64 bytes DUP!\n0% packet loss")
            loss = "25" if unhealthy else "0"
            return _cp(f"3 packets transmitted, 3 received, {loss}% packet loss\nrtt min/avg/max = 1/2/3 ms")
        if args[:1] == ("exec",) and "nslookup" in args:
            return _cp("server failure" if unhealthy else "Name: service\nAddress: 10.0.0.1")
        if args[:1] == ("exec",) and "/proc/net/snmp" in args:
            return _cp("Tcp: RtoAlgorithm RetransSegs\nTcp: 1 42\n")
        if args[:1] == ("exec",) and "/proc/net/netstat" in args:
            return _cp("TcpExt: SyncookiesSent TCPDSACKRecv\nTcpExt: 0 13\n")
        if args[:1] == ("exec",) and "curl" in args:
            if experiment_id == "aks-packet-corruption":
                return _cp("200 3.1" if unhealthy else "200 0.1")
            return _cp("3.1" if unhealthy else "0.1")
        raise AssertionError(f"Unexpected kubectl call: {args}")

    return kubectl


def _checks(experiment_id, unhealthy):
    kubectl = Mock(side_effect=_router(experiment_id, unhealthy))
    checks = post_network.build_post_network_checks(
        experiment_id, "ctx", "app-ns", "app", "app", "demo", ("-l", "app=demo"),
        "-l app=demo", kubectl=lambda: kubectl,
        find_svc_name=lambda: lambda *_args: ("app-service", True),
        partition_ping_target=lambda: lambda _context: "10.0.0.53",
    )
    return checks, kubectl


@pytest.mark.parametrize("experiment_id", [
    "aks-packet-corruption", "aks-packet-duplication", "aks-network-partition",
])
def test_post_network_checks_all_pass_after_recovery(experiment_id):
    checks, kubectl = _checks(experiment_id, unhealthy=False)

    results = {name: check() for name, check in checks.items()}

    assert results
    assert all(passed for passed, _detail in results.values())
    assert kubectl.called  # The closure resolves the supplied facade at invocation time.


@pytest.mark.parametrize("experiment_id", [
    "aks-packet-corruption", "aks-packet-duplication", "aks-network-partition",
])
def test_post_network_checks_report_incomplete_recovery(experiment_id):
    checks, kubectl = _checks(experiment_id, unhealthy=True)

    results = {name: check() for name, check in checks.items()}

    assert any(not passed for passed, _detail in results.values())
    assert any(
        call.args[:2] == ("delete", "networkchaos")
        for call in kubectl.call_args_list
    )


def test_post_network_checks_ignores_unrelated_experiment():
    checks, kubectl = _checks("aks-network-delay", unhealthy=False)

    assert checks == {}
    kubectl.assert_not_called()
