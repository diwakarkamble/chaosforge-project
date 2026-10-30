import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety,
)


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_stress_probe_returns_empty_metric_rows_when_metrics_are_unavailable():
    stresschaos_json = json.dumps({"items": [{"status": {"conditions": [
        {"type": "AllInjected", "status": "True"}
    ]}}]})
    with patch.object(safety, "_kubectl", side_effect=[
        _result("pod-a 1/1 Running 0\n"), _result(stdout=stresschaos_json),
        _result(returncode=1), _result(""),
    ]):
        result = safety.verify_fault_active("aks-memory-stress", "ctx", "ns", "dep", "app", "demo")

    assert result["severity"] == "INFO"
    assert result["pod_rows"] == []
    assert result["node_rows"] == []


def test_io_probe_counts_ready_pods_logs_and_reports_restarts():
    iochaos = {"items": [{"status": {"conditions": [{"type": "AllInjected", "status": "True"}]}}]}
    pods = {"items": [{
        "spec": {"initContainers": [{"name": "chaosfs"}]},
        "status": {"containerStatuses": [{"restartCount": 2}]},
    }]}
    session = MagicMock()
    with patch.object(safety, "_kubectl", side_effect=[
        _result("pod-a 1/1 Running 0\n"), _result(json.dumps(iochaos)), _result(json.dumps(pods)),
    ]):
        result = safety.verify_fault_active("aks-io-latency", "ctx", "ns", "dep", "app", "demo", session=session)

    assert result["severity"] == "CHAOS"
    assert "pods: 1/1 Ready" in result["message"]
    assert "container restarts: 2" in result["message"]
    session.log_event.assert_called_once()


def test_dns_probe_reports_unavailable_shell_without_claiming_resolution_failed():
    dnschaos = {"items": [{"metadata": {"uid": "run-a"}, "status": {"conditions": [
        {"type": "AllInjected", "status": "True"},
    ]}}]}

    def respond(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _result("pod-a 1/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any("patterns" in value for value in args):
            return _result("*.example.test")
        if args[:2] == ("get", "dnschaos") and any("containerRecords" in value for value in args):
            return _result("ns/pod-a/app")
        if args[:2] == ("get", "dnschaos"):
            return _result(json.dumps(dnschaos))
        return _result(returncode=1, stderr="executable file not found")

    with patch.object(safety, "_kubectl", side_effect=respond):
        result = safety.verify_fault_active("aks-dns-failure", "ctx-shell", "ns-shell", "dep-shell", "app", "demo")

    assert result["severity"] == "CHAOS"
    assert "probe unavailable" in result["message"]
    assert "chaos injecting" not in result["message"]


def test_dns_probe_marks_a_previously_observed_fault_as_recovered_when_dns_resolves():
    run_key = "ctx-recovery/ns-recovery/dep-recovery"
    safety._DNS_CHAOS_EVER_OBSERVED.add(run_key)
    safety._DNS_CHAOS_LAST_UID[run_key] = "run-recovery"
    try:
        dnschaos = {"items": [{"metadata": {"uid": "run-recovery"}, "status": {"conditions": []}}]}

        def respond(*args, **kwargs):
            if args[:2] == ("get", "pods"):
                return _result("pod-a 1/1 Running 0\n")
            if args[:2] == ("get", "dnschaos") and any("patterns" in value for value in args):
                return _result("service.example.test")
            if args[:2] == ("get", "dnschaos") and any("containerRecords" in value for value in args):
                return _result("ns-recovery/pod-a/app")
            if args[:2] == ("get", "dnschaos"):
                return _result(json.dumps(dnschaos))
            return _result("Name: service.example.test\nAddress: 10.0.0.4")

        with patch.object(safety, "_kubectl", side_effect=respond):
            result = safety.verify_fault_active("aks-dns-failure", "ctx-recovery", "ns-recovery", "dep-recovery", "app", "demo")
    finally:
        safety._DNS_CHAOS_EVER_OBSERVED.discard(run_key)
        safety._DNS_CHAOS_LAST_UID.pop(run_key, None)

    assert result["severity"] == "CHAOS"
    assert "fault recovered" in result["message"]


def test_unknown_experiment_returns_a_pod_count_after_the_standard_listing():
    with patch.object(safety, "_kubectl", return_value=_result("pod-a 1/1 Running 0\npod-b 1/1 Running 0\n")):
        result = safety.verify_fault_active("aks-unknown", "ctx", "ns", "dep", "app", "demo")

    assert result == {"severity": "INFO", "message": "pods: 2 found"}


def test_primary_probe_honors_exact_pod_scope_and_reports_kubectl_unavailability():
    with patch.object(safety, "_kubectl", return_value=_result(returncode=1)) as kubectl:
        result = safety.verify_fault_active(
            "aks-unknown", "ctx", "ns", "dep", exact_pod_name="only-pod",
        )
    assert result["severity"] == "WARNING"
    assert "kubectl unavailable" in result["message"]
    assert "--field-selector" in kubectl.call_args.args


def test_io_probe_handles_invalid_crd_and_pod_json_without_claiming_injection():
    with patch.object(safety, "_kubectl", side_effect=[
        _result("pod-a 1/1 Running 0\n"), _result("not-json"), _result("not-json"),
    ]):
        result = safety.verify_fault_active("aks-io-errors", "ctx", "ns", "dep", "app", "demo")
    assert result["severity"] == "WARNING"
    assert "injection pending" in result["message"]


def test_dns_probe_pending_without_a_pattern_does_not_exec_or_claim_success():
    dnschaos = {"items": [{"metadata": {"uid": "dns-no-pattern"}, "status": {"conditions": []}}]}

    def respond(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _result("pod-a 1/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any("patterns" in value for value in args):
            return _result("")
        if args[:2] == ("get", "dnschaos"):
            return _result(json.dumps(dnschaos))
        raise AssertionError("DNS exec must not run without a pattern")

    with patch.object(safety, "_kubectl", side_effect=respond):
        result = safety.verify_fault_active("aks-dns-failure", "ctx", "ns-no-pattern", "dep", "app", "demo")
    assert result["severity"] == "WARNING"
    assert "injection pending" in result["message"]


def test_dns_new_uid_clears_observation_from_the_previous_run():
    run_key = "ctx-new-run/ns-new-run/dep-new-run"
    safety._DNS_CHAOS_EVER_OBSERVED.add(run_key)
    safety._DNS_CHAOS_LAST_UID[run_key] = "old-uid"
    dnschaos = {"items": [{"metadata": {"uid": "new-uid"}, "status": {"conditions": []}}]}

    def respond(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _result("pod-a 1/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any("patterns" in value for value in args):
            return _result("service.example.test")
        if args[:2] == ("get", "dnschaos") and any("containerRecords" in value for value in args):
            return _result("ns-new-run/pod-a/app")
        if args[:2] == ("get", "dnschaos"):
            return _result(json.dumps(dnschaos))
        return _result("Name: service.example.test\nAddress: 10.0.0.4")

    try:
        with patch.object(safety, "_kubectl", side_effect=respond):
            result = safety.verify_fault_active("aks-dns-failure", "ctx-new-run", "ns-new-run", "dep-new-run", "app", "demo")
    finally:
        safety._DNS_CHAOS_EVER_OBSERVED.discard(run_key)
        safety._DNS_CHAOS_LAST_UID.pop(run_key, None)
    assert result["severity"] == "WARNING"
    assert "NOT yet effective" in result["message"]
