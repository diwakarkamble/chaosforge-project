"""Isolated unit coverage for pre-fault NetworkChaos safety check closures."""

import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_pre_network_corruption_duplication_partition as pre_network,
)


def _cp(stdout="", returncode=0):
    return CompletedProcess([], returncode, stdout=stdout)


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


def _router(experiment_id, unsafe):
    """Return local kubectl responses; no cluster or cloud calls are made."""
    def kubectl(*args, **_kwargs):
        if args[:3] == ("get", "crd", "networkchaoses.chaos-mesh.org"):
            return _cp(returncode=1) if unsafe else _cp()
        if args[:2] == ("get", "networkchaos"):
            if "--all-namespaces" in args:
                return _cp()
            active = [{
                "metadata": {"name": "other-fault"},
                "status": {"conditions": [{"type": "AllInjected", "status": "True"}]},
            }]
            return _cp(json.dumps({"items": active if unsafe else []}))
        if args[:2] == ("get", "pods"):
            return _cp(json.dumps(_pod(3 if unsafe else 0)))
        if args[:2] == ("get", "service"):
            return _cp("10.0.0.10")
        if args[:2] == ("get", "endpoints"):
            addresses = [] if unsafe else [{"ip": "10.0.0.1"}]
            return _cp(json.dumps({"subsets": [{"addresses": addresses}]}))
        if args[:2] == ("get", "deployment"):
            return _cp(json.dumps({"spec": {"replicas": 1 if unsafe else 2}}))
        if args[:1] == ("exec",) and "tc" in args:
            return _cp("qdisc netem 1: dev eth0" if unsafe else "qdisc fq_codel 0: dev eth0")
        if args[:1] == ("exec",) and "iptables" in args:
            return _cp("Chain CHAOS-TEST" if unsafe else "Chain INPUT")
        if args[:1] == ("exec",) and "ping" in args:
            if experiment_id == "aks-packet-duplication" and unsafe:
                return _cp("64 bytes from target: DUP!\n0% packet loss")
            loss = "25" if unsafe else "0"
            return _cp(f"3 packets transmitted, 3 received, {loss}% packet loss")
        if args[:1] == ("exec",) and "nslookup" in args:
            return _cp("server failure" if unsafe else "Name: app\nAddress: 10.0.0.1")
        if args[:1] == ("exec",) and "/proc/net/snmp" in args:
            return _cp("Tcp: RtoAlgorithm RetransSegs\nTcp: 1 42")
        if args[:1] == ("exec",) and "curl" in args:
            return _cp("0.1")
        raise AssertionError(f"Unexpected kubectl call: {args}")

    return kubectl


def _checks(experiment_id, unsafe=False):
    kubectl = Mock(side_effect=_router(experiment_id, unsafe))
    checks = pre_network.build_pre_network_checks(
        experiment_id, "ctx", "app-ns", "app", "app", "demo", ("-l", "app=demo"),
        "-l app=demo", kubectl=lambda: kubectl,
        find_svc_name=lambda: lambda *_args: ("app-service", True),
        partition_ping_target=lambda: lambda _context: "10.0.0.53",
    )
    return checks, kubectl


@pytest.mark.parametrize("experiment_id", [
    "aks-packet-corruption", "aks-packet-duplication", "aks-network-partition",
])
def test_pre_network_checks_pass_healthy_baseline(experiment_id):
    checks, kubectl = _checks(experiment_id)

    results = {name: check() for name, check in checks.items()}

    assert results
    assert all(passed for passed, _detail in results.values())
    assert kubectl.called


@pytest.mark.parametrize("experiment_id", [
    "aks-packet-corruption", "aks-packet-duplication", "aks-network-partition",
])
def test_pre_network_checks_reject_unsafe_baseline(experiment_id):
    checks, kubectl = _checks(experiment_id, unsafe=True)

    results = {name: check() for name, check in checks.items()}

    assert any(not passed for passed, _detail in results.values())
    assert any(
        call.args[:3] == ("get", "crd", "networkchaoses.chaos-mesh.org")
        for call in kubectl.call_args_list
    )
    assert any("baseline" in detail.lower() or "rule" in detail.lower()
               for passed, detail in results.values() if not passed)


@pytest.mark.parametrize("experiment_id", [None, "aks-network-delay"])
def test_pre_network_checks_ignore_unrelated_or_incomplete_experiments(experiment_id):
    kubectl = Mock()

    checks = pre_network.build_pre_network_checks(
        experiment_id, "ctx", "app-ns", "app", "app", "demo", (), "",
        kubectl=lambda: kubectl,
        find_svc_name=lambda: Mock(),
        partition_ping_target=lambda: Mock(),
    )

    assert checks == {}
    kubectl.assert_not_called()
