"""Final behavioral coverage for residual Chaos Studio safety paths."""

import builtins
import json
import sys
from subprocess import CompletedProcess
from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_fault_network as network,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_corruption_duplication_partition as post_network,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import safety


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _json(value):
    return _result(json.dumps(value))


def _capture_closure(builder, frame_code, name):
    captured = []
    previous = sys.getprofile()

    def profiler(frame, event, _arg):
        if event == "return" and frame.f_code is frame_code:
            closure = frame.f_locals.get(name)
            if closure is not None:
                captured.append(closure)

    sys.setprofile(profiler)
    try:
        builder()
    finally:
        sys.setprofile(previous)
    assert captured
    return captured[-1]


def test_service_fqdn_closures_report_missing_and_resolved_services():
    pre = _capture_closure(
        lambda: safety.build_steady_state_checks("ctx", "ns", "api", "app", "demo"),
        safety.build_steady_state_checks.__code__,
        "_service_fqdn",
    )
    post = _capture_closure(
        lambda: safety.build_post_experiment_checks("aks-unknown", "ctx", "ns", "api", "app", "demo"),
        safety.build_post_experiment_checks.__code__,
        "_service_fqdn",
    )
    with patch.object(safety, "_find_svc_name", return_value=("", False)):
        assert pre()[0] == ""
    with patch.object(safety, "_find_svc_name", return_value=("service", True)):
        assert pre() == ("service.ns.svc.cluster.local", "")
        assert post() == ("service.ns.svc.cluster.local", "")
    with patch.object(safety, "_find_svc_name", return_value=("", False)):
        assert post()[0] == ""


def test_network_helpers_cover_parse_and_message_fallbacks():
    assert network._counter("Tcp: A\nTcp: 1", "Tcp:", "A") == "1"
    assert network._counter("Tcp: A\nTcp: 1", "Tcp:", "Missing") is None
    assert network._ping_rtt(lambda *_a, **_k: _result("time=3.5 ms"), "pod", "ns", "ctx", "1.1.1.1") == 3.5
    assert network._ping_rtt(lambda *_a, **_k: _result(returncode=1), "pod", "ns", "ctx", "1.1.1.1") is None
    assert network._ping_rtt(lambda *_a, **_k: _result(), "", "ns", "ctx", "1.1.1.1") is None
    assert network._ping_rtt(lambda *_a, **_k: _result("time=broken"), "pod", "ns", "ctx", "1.1.1.1") is None
    assert "partition" in network._unhealthy_message("aks-network-partition", 1)
    assert "partition" in network._restart_message("aks-network-partition", 1)


def test_network_probe_covers_malformed_crd_metrics_and_not_ready_details():
    def run(*args, **_kwargs):
        if args[:2] == ("get", "networkchaos"):
            return _result("bad-json")
        if args[:1] == ("exec",) and "tc" in args:
            return _result("qdisc netem delay 10ms")
        if args[:1] == ("exec",) and "/proc/net/snmp" in args:
            return _result("Tcp: RetransSegs\nTcp: 8")
        if args[:2] == ("get", "events"):
            return _result("unhealthy")
        if args[:2] == ("get", "pods"):
            return _result("bad-json")
        raise AssertionError(args)

    probe = network.build_network_live_probe(
        kubectl=lambda: run,
        find_svc_name=lambda: lambda *_a: ("", False),
        select_live_probe_pod=lambda: lambda *_a: "pod-a",
        annotate_network_result=lambda: lambda result, *_a: result,
    )
    result = probe(
        "aks-packet-loss", "ctx", "ns", "api", "app", "demo", None,
        ["-l", "app=demo"], ["pod-a 0/1 Running 0"], 1, ["pod-a"], 0,
    )
    assert "loss rule not detected" in result["message"]
    assert "Unhealthy probe events: 1" in result["message"]
    assert any(row[0] == "TCP RetransSegs" for row in result["net_rows"])


def test_network_rows_cover_ping_and_measurement_fallbacks():
    rows = network._rows("aks-network-delay", None, None, None, None, False, 0, 0, 0, False, False, None, "pod")
    assert ("Measured RTT (ping)", "unavailable", "ping not in container image") in rows
    assert network._rows("aks-packet-corruption", None, None, 1, 1, True, 0, 0, 0, False, False, None, "pod")[0] == (
        "TCP RetransSegs", "exec blocked by fault", "packet fault disrupted the measurement exec"
    )


def test_network_probe_covers_endpoint_parse_failure_and_no_pod_measurements():
    def run(*args, **_kwargs):
        if args[:2] == ("get", "networkchaos"):
            return _json({"items": []})
        if args[:2] == ("get", "endpoints"):
            return _result("bad-json")
        if args[:2] == ("get", "events"):
            return _result("")
        if args[:2] == ("get", "pods"):
            return _json({"items": []})
        raise AssertionError(args)

    probe = network.build_network_live_probe(
        kubectl=lambda: run, find_svc_name=lambda: lambda *_a: ("svc", True),
        select_live_probe_pod=lambda: lambda *_a: None,
        annotate_network_result=lambda: lambda result, *_a: result,
    )
    result = probe("aks-packet-duplication", "ctx", "ns", "api", "app", "demo", None, (), [], 0, [], None)
    assert "injection status unknown" in result["message"]
    assert any(row[0] == "TCP DSACKRecv" for row in result["net_rows"])


def test_partition_probe_reports_inactive_rules_expected_not_ready_and_logs():
    def run(*args, **_kwargs):
        if args[:2] == ("get", "networkchaos"):
            return _json({"items": []})
        if args[:1] == ("exec",):
            return _result("Chain INPUT")
        if args[:2] == ("get", "events"):
            return _result("")
        if args[:2] == ("get", "pods"):
            return _json({"items": []})
        raise AssertionError(args)

    session = MagicMock()
    probe = network.build_network_live_probe(
        kubectl=lambda: run, find_svc_name=lambda: lambda *_a: ("", False),
        select_live_probe_pod=lambda: lambda *_a: "pod-a",
        annotate_network_result=lambda: lambda result, *_a: result,
    )
    result = probe("aks-network-partition", "ctx", "ns", "api", "app", "demo", session, (), ["pod-a 0/1 Running"], 1, [], None)
    assert "chaos chain not detected" in result["message"]
    assert "expected under full network partition" in result["message"]
    session.log_event.assert_called_once()


def test_post_network_first_pod_and_rtt_parsers_cover_non_running_and_bad_summaries():
    non_running = _json({"items": [{"metadata": {"name": "pending"}, "status": {"phase": "Pending"}}]})
    corruption = post_network.build_post_network_checks(
        "aks-packet-corruption", "ctx", "ns", "api", "app", "demo", (), "",
        kubectl=lambda: lambda *_a, **_k: non_running,
        find_svc_name=lambda: lambda *_a: ("", False),
        partition_ping_target=lambda: lambda _ctx: "10.0.0.10",
    )
    assert "no running pod" in corruption["tc-netem Corrupt Rule Removed"]()[1]

    pod = _json({"items": [{"metadata": {"name": "api-0"}, "status": {"phase": "Running"}}]})
    def malformed(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return pod
        if args[:1] == ("exec",):
            return _result("rtt min/avg/max = malformed")
        raise AssertionError(args)

    partition = post_network.build_post_network_checks(
        "aks-network-partition", "ctx", "ns", "api", "app", "demo", (), "",
        kubectl=lambda: malformed, find_svc_name=lambda: lambda *_a: ("", False),
        partition_ping_target=lambda: lambda _ctx: "10.0.0.10",
    )
    assert partition["Connectivity Restored (ping — 0% loss)"]()[0] is True

    duplication = post_network.build_post_network_checks(
        "aks-packet-duplication", "ctx", "ns", "api", "app", "demo", (), "",
        kubectl=lambda: lambda *_a, **_k: non_running,
        find_svc_name=lambda: lambda *_a: ("", False),
        partition_ping_target=lambda: lambda _ctx: "10.0.0.10",
    )
    assert "no running pod" in duplication["tc-netem Rule Removed"]()[1]
    partition_skip = post_network.build_post_network_checks(
        "aks-network-partition", "ctx", "ns", "api", "app", "demo", (), "",
        kubectl=lambda: lambda *_a, **_k: non_running,
        find_svc_name=lambda: lambda *_a: ("", False),
        partition_ping_target=lambda: lambda _ctx: "10.0.0.10",
    )
    assert "no running pod" in partition_skip["iptables Chaos Rules Removed"]()[1]

    def bad_rtt(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return pod
        if args[:2] == ("get", "service"):
            return _result("10.0.0.10")
        if args[:1] == ("exec",):
            return _result("rtt min/avg/max = one")
        raise AssertionError(args)

    assert post_network.build_post_network_checks(
        "aks-packet-corruption", "ctx", "ns", "api", "app", "demo", (), "",
        kubectl=lambda: bad_rtt, find_svc_name=lambda: lambda *_a: ("", False),
        partition_ping_target=lambda: lambda _ctx: "10.0.0.10",
    )["Ping RTT Restored"]()[0] is True

    def bad_ping(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return pod
        if args[:1] == ("exec",):
            return _result("% packet loss\nrtt avg = one")
        raise AssertionError(args)

    assert post_network.build_post_network_checks(
        "aks-network-partition", "ctx", "ns", "api", "app", "demo", (), "",
        kubectl=lambda: bad_ping, find_svc_name=lambda: lambda *_a: ("", False),
        partition_ping_target=lambda: lambda _ctx: "10.0.0.10",
    )["Connectivity Restored (ping — 0% loss)"]()[0] is True


@pytest.mark.parametrize("experiment_id", [
    "aks-clock-skew-forward", "aks-http-delay", "aks-dns-failure", "aks-io-latency", "aks-coredns-kill",
])
def test_optional_extended_imports_and_dns_lookup_exceptions_are_advisory(monkeypatch, experiment_id):
    original_import = builtins.__import__

    def unavailable(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "extended" and level == 1:
            raise ImportError("unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    safety.build_steady_state_checks("ctx", "ns", "api", experiment_id=experiment_id)
    safety.build_post_experiment_checks(experiment_id, "ctx", "ns", "api")

    def dns(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _result("pod 1/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any(
            "patterns" in value or "containerRecords" in value for value in args
        ):
            raise RuntimeError("unavailable")
        if args[:2] == ("get", "dnschaos"):
            return _json({"items": []})
        raise AssertionError(args)

    with patch.object(safety, "_kubectl", side_effect=dns):
        result = safety.verify_fault_active("aks-dns-failure", "ctx-final", "ns-final", "api")
    assert result["severity"] == "WARNING"


def test_annotation_and_exact_pod_post_checks_cover_remaining_fallbacks():
    result = {"message": "base", "net_rows": [("Container restarts", None, "old")]}
    safety._annotate_network_result(result, ["broken"], [], 0)

    checks = safety.build_post_experiment_checks(
        "aks-network-delay", "ctx", "ns", "api", "app", "demo", target_mode="pod", exact_pod_name="pod-a",
    )
    pods = _json({"items": [{"metadata": {"name": "pod-a"}, "status": {"podIP": "10.0.0.1"}}]})
    with patch.object(safety, "_kubectl", side_effect=[pods, _result("bad-json")]), patch.object(safety, "_find_svc_name", return_value=("svc", True)):
        assert checks["Service Endpoints Restored"]()[0] is False
    with patch.object(safety, "_kubectl", return_value=_json({"items": [{"involvedObject": {"name": "pod-a"}, "lastTimestamp": "bad", "message": "failure"}]})):
        assert checks["Probe Failures Stopped (post)"]()[0] is False

    endpoint = _json({"subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]})
    with patch.object(safety, "_kubectl", side_effect=[pods, endpoint]), patch.object(safety, "_find_svc_name", return_value=("svc", True)):
        assert checks["Service Endpoints Restored"]()[0] is True


def test_precheck_parse_and_pdb_skip_paths_and_dns_session_logging():
    checks = safety.build_steady_state_checks("ctx", "ns", "api", "app", "demo", "aks-network-delay")
    with patch.object(safety, "_kubectl", side_effect=[_result(returncode=1), _result("bad-json")]):
        assert checks["Replica Floor (api)"]()[0] is False
    with patch.object(safety, "_kubectl", return_value=_result("bad-json")):
        assert checks["PodDisruptionBudget"]()[0] is True
    target_pods = {"items": [{"metadata": {"labels": {"app": "demo"}}}]}
    pdbs = {"items": [{"spec": {"selector": {"matchLabels": {"app": "other"}}}}]}
    with patch.object(safety, "_kubectl", side_effect=[_json(target_pods), _json(pdbs)]):
        assert checks["PodDisruptionBudget"]()[0] is True

    session = MagicMock()
    def dns(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _result("pod 1/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any("patterns" in item for item in args):
            return _result("")
        return _json({"items": []})
    with patch.object(safety, "_kubectl", side_effect=dns):
        safety.verify_fault_active("aks-dns-failure", "ctx-log", "ns-log", "api", session=session)
    session.log_event.assert_called_once()


def test_time_spec_dns_record_and_exact_event_parse_fallbacks():
    with patch.object(builtins, "open", mock_open(read_data='{"timeOffset": "7m"}')):
        safety.build_steady_state_checks("ctx", "ns", "api", experiment_id="aks-clock-skew-forward", time_offset="")
    with patch.object(builtins, "open", side_effect=OSError("unreadable")):
        safety.build_steady_state_checks("ctx", "ns", "api", experiment_id="aks-clock-skew-forward", time_offset="")

    def dns(*args, **_kwargs):
        if args[:2] == ("get", "pods"):
            return _result("pod 1/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any("patterns" in item for item in args):
            return _result("name.example")
        if args[:2] == ("get", "dnschaos") and any("containerRecords" in item for item in args):
            raise RuntimeError("records unavailable")
        if args[:2] == ("get", "dnschaos"):
            return _json({"items": []})
        return _result("Name: name.example")
    with patch.object(safety, "_kubectl", side_effect=dns):
        safety.verify_fault_active("aks-dns-failure", "ctx-record", "ns-record", "api")

    exact = safety.build_post_experiment_checks("aks-network-delay", "ctx", "ns", "api", target_mode="pod", exact_pod_name="pod")
    with patch.object(safety, "_kubectl", return_value=_result("bad-json")):
        assert exact["Probe Failures Stopped (post)"]()[0] is True
    with patch.object(safety, "_kubectl", return_value=_json({"items": [{"involvedObject": {"name": "pod"}, "lastTimestamp": "bad", "message": "x"}]})):
        assert exact["Probe Failures Stopped (post)"]()[0] is False
    with patch.object(safety, "_kubectl", return_value=_json({"items": [{"involvedObject": {"name": "pod"}, "lastTimestamp": "2000-01-01T00:00:00Z", "message": "old"}]})):
        assert exact["Probe Failures Stopped (post)"]()[0] is True
