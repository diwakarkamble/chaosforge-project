"""Residual branch coverage for AKS Chaos Studio safety-check helpers."""

import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_basic as basic,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_corruption_duplication_partition as post_network,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_pre_network_corruption_duplication_partition as pre_partition,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_pre_network_delay_loss_bandwidth as pre_delay,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    extended,
    safety,
)


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_system_pods_rejects_malformed_required_component_response():
    with pytest.raises(RuntimeError, match="No CoreDNS pods found"):
        basic.check_system_pods_running("ctx", lambda *_args, **_kwargs: _result("not-json"))


def test_network_prechecks_keep_command_failures_advisory():
    def delay_run(*args, **_kwargs):
        if args[:2] == ("get", "endpoints"):
            return _result(returncode=1)
        raise AssertionError(args)

    delay_checks = pre_delay.build_pre_network_checks(
        "aks-network-delay", "ctx", "app", "api", "app", "api", (), "",
        kubectl=lambda: delay_run, find_svc_name=lambda: lambda *_args: ("api", True),
    )
    assert "endpoint query failed" in delay_checks["Service Endpoints (baseline)"]()[1]

    pod = {"items": [{"metadata": {"name": "api-0"}, "status": {"phase": "Running"}}]}

    def partition_run(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _result(json.dumps(pod))
        if args[:2] == ("get", "service"):
            return _result("10.0.0.10")
        if args[:1] == ("exec",):
            return _result(returncode=1)
        raise AssertionError(args)

    partition_checks = pre_partition.build_pre_network_checks(
        "aks-packet-duplication", "ctx", "app", "api", "app", "api", (), "",
        kubectl=lambda: partition_run, find_svc_name=lambda: lambda *_args: ("api", True),
        partition_ping_target=lambda: lambda _context: "10.0.0.10",
    )
    assert "ping unavailable" in partition_checks["Baseline Ping (0 DUP! pre-fault)"]()[1]


def test_corruption_postcheck_tolerates_malformed_ping_summary():
    pod = {"items": [{"metadata": {"name": "api-0"}, "status": {"phase": "Running"}}]}

    def run(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _result(json.dumps(pod))
        if args[:2] == ("get", "service"):
            return _result("10.0.0.10")
        if args[:1] == ("exec",):
            return _result("% packet loss\nrtt min/avg/max = 1")
        raise AssertionError(args)

    checks = post_network.build_post_network_checks(
        "aks-packet-corruption", "ctx", "app", "api", "app", "api", (), "",
        kubectl=lambda: run, find_svc_name=lambda: lambda *_args: ("api", True),
        partition_ping_target=lambda: lambda _context: "10.0.0.10",
    )
    passed, detail = checks["Packet Loss Back to 0% (post-rollback)"]()
    assert passed is True
    assert "packet loss = None%" in detail


def test_rollback_skips_when_setup_state_is_absent():
    with patch(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor._load_state",
        return_value=None,
    ):
        assert safety.verify_rollback_health("ctx", experiment_id="missing") is True


def test_extended_facade_wraps_io_post_checks():
    def check():
        return True, "clean"

    with patch.object(extended._io, "build_io_chaos_post_checks", return_value={"IO": check}):
        checks = extended.build_io_chaos_post_checks("ctx", "app", "api")
    assert checks["IO"]() == (True, "clean")
