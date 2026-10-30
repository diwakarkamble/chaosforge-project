"""Focused branch coverage for AKS safety helpers and validation logging."""

import json
import time
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    validation_logger,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_common as common,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_time as time_checks,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_basic as basic,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_fault_network as network,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import safety


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _json(value):
    return _result(json.dumps(value))


def _pod(name="api-0", *, ready=True, phase="Running", restarts=0):
    return {
        "metadata": {"name": name, "namespace": "app"},
        "spec": {"containers": [{"name": "api", "image": "repo/api:1"}]},
        "status": {
            "phase": phase,
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "containerStatuses": [{
                "name": "api",
                "ready": ready,
                "restartCount": restarts,
                "state": {"running": {}} if phase == "Running" else {"terminated": {}},
            }],
        },
    }


def test_common_transport_and_resource_error_paths_are_explicit():
    dispatched = _result("client")
    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl",
        return_value=dispatched,
    ):
        assert common._kubectl("version", context="ctx") is dispatched

    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl",
        side_effect=RuntimeError("client unavailable"),
    ), patch("chaosforge.providers.azure.components.aks.kubernetes.subprocess.run", return_value=_result("fallback")) as run:
        assert common._kubectl("version").stdout == "fallback"
    assert run.call_args.args[0] == ["kubectl", "version", "--request-timeout=10s"]

    failed = _result(returncode=1, stderr="forbidden")
    with patch.object(common, "_kubectl", return_value=failed):
        assert common._check_no_stale_chaos_crd("ctx", "timechaos") == (
            True,
            "kubectl get timechaos -n chaos-testing\n  (query failed — assuming clean)",
        )
        assert common._get_deployment_json("ctx", "app", "api") == (
            None,
            "kubectl get deployment failed: forbidden",
        )
        assert common._get_workload_by_selector("ctx", "app", "daemonset", "app=x") == (
            None,
            "kubectl get daemonset failed: forbidden",
        )


def test_common_stale_resources_that_resist_finalizer_removal_fail_safely():
    responses = [_result("fault-a\n"), _result()]
    responses.extend([_result("fault-a\n")] * 5)
    responses.extend([_result(returncode=1, stderr="patch denied"), _result("fault-a\n")])
    with patch.object(common, "_kubectl", side_effect=responses), patch("time.sleep"):
        passed, detail = common._check_no_stale_chaos_crd("ctx", "networkchaos")
    assert passed is False
    assert "could not be cleared" in detail
    assert "Manual cleanup required" in detail


def test_common_pod_dns_and_canary_edge_paths():
    with patch.object(common, "_kubectl", return_value=_result("not-json")):
        assert common._first_running_pod("ctx", "app", "app=api") is None
        assert common._canary_pod("ctx") == (None, None)
    with patch.object(common, "_first_running_pod", return_value=None):
        assert common._measure_dns_latency("ctx", "app", "app=api", "example.com") is None

    unavailable = _result(stderr="OCI runtime exec failed", returncode=1)
    with patch.object(common, "_first_running_pod", return_value="api-0"), patch.object(
        common, "_kubectl", return_value=unavailable
    ):
        assert common._measure_dns_latency("ctx", "app", "app=api", "example.com") is None

    missing_tools = [_result(returncode=127)] * 3
    with patch.object(common, "_first_running_pod", return_value="api-0"), patch.object(
        common, "_kubectl", side_effect=missing_tools
    ):
        assert common._measure_dns_latency("ctx", "app", "app=api", "example.com") is None

    candidates = [_pod("system", ready=True), _pod("pending", ready=False)]
    candidates[0]["metadata"]["namespace"] = "kube-system"
    candidates[1]["metadata"]["namespace"] = "team"
    with patch.object(common, "_kubectl", return_value=_json({"items": candidates})):
        assert common._canary_pod("ctx") == (None, None)


@pytest.mark.parametrize(
    ("probe_results", "expected_tool", "expected_success"),
    [
        ([_result(returncode=127), _result("10.0.0.1"), _result("10.0.0.1")], "dig", 1),
        (
            [_result(returncode=127), _result(returncode=127), _result("10.0.0.1 host"),
             _result("10.0.0.1 host")],
            "getent",
            1,
        ),
    ],
)
def test_common_dns_measurement_supports_fallback_tools(
    probe_results, expected_tool, expected_success
):
    ticks = iter([1.0, 1.004])
    with patch.object(common, "_first_running_pod", return_value="api-0"), patch.object(
        common, "_kubectl", side_effect=probe_results
    ), patch("time.monotonic", side_effect=lambda: next(ticks)):
        measured = common._measure_dns_latency(
            "ctx", "app", "app=api", "example.com", n=1
        )
    assert measured["tool"] == expected_tool
    assert measured["success"] == expected_success
    assert measured["p95_ms"] == 4


def test_time_prechecks_report_unqueryable_and_unsafe_targets():
    checks = time_checks.build_time_chaos_pre_checks(
        "ctx", "app", "api", experiment_id="aks-clock-skew-forward", time_offset="n/a"
    )
    passed, detail = checks["Clock Skew Offset Magnitude"]()
    assert passed is True
    assert "Could not parse offset" in detail

    with patch.object(time_checks, "_kubectl", return_value=_result(returncode=1)):
        assert checks["Timing-Sensitive System Detection"]()[0] is True
    with patch.object(time_checks, "_kubectl", return_value=_result("bad-json")):
        assert checks["Timing-Sensitive System Detection"]() == (
            True,
            "Could not parse pods — skipping timing-sensitive check",
        )
        assert checks["cert-manager Certificate Expiry Window"]() == (
            True,
            "Could not parse Certificate resources — skipping",
        )
    with patch.object(time_checks, "_get_pods_json", return_value=(None, "denied")):
        assert checks["No Pre-Existing CrashLoop"]()[0] is True

    with patch.object(time_checks, "_first_running_pod", return_value=None):
        assert checks["Node Time Sync (NTP/Chrony)"]()[0] is True
    with patch.object(time_checks, "_first_running_pod", return_value="api-0"), patch.object(
        time_checks, "_kubectl", return_value=_result(returncode=1)
    ):
        assert "Could not determine target node" in checks["Node Time Sync (NTP/Chrony)"]()[1]


def test_time_prechecks_detect_sensitive_apps_crashes_and_bad_ntp_data():
    checks = time_checks.build_time_chaos_pre_checks("ctx", "app", "api", time_offset="5m")
    vault = _pod()
    vault["spec"]["containers"][0].update({"name": "vault-agent", "image": "hashicorp/vault:1"})
    with patch.object(time_checks, "_kubectl", return_value=_json({"items": [vault]})):
        passed, detail = checks["Timing-Sensitive System Detection"]()
    assert passed is False
    assert "vault" in detail

    crashing = _pod()
    crashing["status"]["containerStatuses"][0]["state"] = {
        "waiting": {"reason": "CrashLoopBackOff"}
    }
    with patch.object(time_checks, "_get_pods_json", return_value=([crashing], None)):
        assert checks["No Pre-Existing CrashLoop"]()[0] is False

    with patch.object(time_checks, "_first_running_pod", return_value="api-0"), patch.object(
        time_checks,
        "_kubectl",
        side_effect=[_result("node-a"), _result("bad-json")],
    ):
        passed, detail = checks["Node Time Sync (NTP/Chrony)"]()
    assert passed is True
    assert detail.startswith("⚠ ")
    assert "not found" in detail


def test_time_postchecks_cover_query_failures_and_clock_drift():
    checks = time_checks.build_time_chaos_post_checks("ctx", "app", "api")
    with patch.object(time_checks, "_get_pods_json", return_value=(None, "denied")):
        assert checks["No CrashLoop After Clock Skew"]() == (
            False,
            "Could not query pods: denied",
        )
    with patch.object(time_checks, "_get_deployment_json", return_value=(None, "gone")):
        assert checks["Replicas Restored"]() == (False, "Could not query deployment: gone")
    with patch.object(time_checks, "_kubectl", return_value=_result(returncode=1, stderr="rbac")):
        assert checks["No TLS/Auth Events Post-Skew"]()[0] is True
        assert checks["TimeChaos CRD Cleaned Up"]()[0] is True
    with patch.object(time_checks, "_kubectl", return_value=_result("bad-json")):
        assert checks["No TLS/Auth Events Post-Skew"]() == (
            True,
            "Could not parse events — skipping",
        )

    with patch.object(time_checks, "_first_running_pod", return_value="api-0"), patch.object(
        time_checks, "_kubectl", return_value=_result(returncode=1, stderr="no shell")
    ):
        assert "exec failed" in checks["Pod Clock Reverted"]()[1]
    with patch.object(time_checks, "_first_running_pod", return_value="api-0"), patch.object(
        time_checks, "_kubectl", return_value=_result(str(int(time.time()) - 120))
    ):
        passed, detail = checks["Pod Clock Reverted"]()
    assert passed is False
    assert "still drifted" in detail


def test_basic_parsing_failures_do_not_masquerade_as_healthy_resources():
    with pytest.raises(RuntimeError, match="Could not parse deployment"):
        basic.check_deployment_replica_floor(
            "ctx", "app", "api", 1, "", lambda *a, **k: _result("bad-json")
        )

    responses = iter([_result(returncode=1), _result("bad-json")])
    with pytest.raises(RuntimeError, match="Could not parse pod"):
        basic.check_deployment_replica_floor(
            "ctx", "app", "api-0", 1, "", lambda *a, **k: next(responses)
        )

    basic.check_pdb_allows_disruption(
        "ctx", "app", "app", "api", lambda *a, **k: _result(returncode=1)
    )
    basic.check_pdb_allows_disruption(
        "ctx", "app", "app", "api", lambda *a, **k: _result("bad-json")
    )
    with pytest.raises(RuntimeError, match="Could not parse node list"):
        basic.check_nodes_ready("ctx", 1, lambda *a, **k: _result("bad-json"))


def test_basic_system_pod_and_lookup_failure_fallbacks(capsys):
    calls = []

    def system_responder(*args, **kwargs):
        calls.append(args)
        if "k8s-app=kube-dns" in args:
            return _json({"items": [_pod("coredns")]})
        return _result(returncode=1)

    basic.check_system_pods_running("ctx", system_responder)
    assert "Could not query kube-proxy" in capsys.readouterr().out
    assert len(calls) == 3

    malformed = iter([_result("bad-json"), _result(returncode=1)])
    assert basic.get_pods_for_deployment(
        "ctx", "app", "api", "", lambda *a, **k: next(malformed)
    ) == []
    malformed_pod = iter([_result(returncode=1), _result("bad-json")])
    assert basic.get_pods_for_deployment(
        "ctx", "app", "api", "", lambda *a, **k: next(malformed_pod)
    ) == []


def test_basic_chaos_mesh_bad_json_and_unhealthy_probe_detail():
    with pytest.raises(RuntimeError, match="not running or not ready"):
        basic.check_chaos_mesh_running("ctx", "chaos-testing", lambda *a, **k: _result("bad-json"))

    assert basic.probe_aks_target_healthy(
        "ctx",
        "app",
        "api",
        "",
        lambda *a, **k: None,
        lambda *a, **k: (False, "CrashLoopBackOff"),
        lambda *a, **k: None,
        lambda *a, **k: None,
    ) is False


def test_network_helpers_handle_malformed_metrics_and_messages():
    assert network._counter("Tcp: RetransSegs\nTcp: 9", "Tcp:", "Missing") is None
    assert network._counter("Tcp: RetransSegs\nTcp:", "Tcp:", "RetransSegs") is None
    assert network._ping_rtt(MagicMock(), None, "app", "ctx", "10.0.0.10") is None
    run = MagicMock(return_value=_result("64 bytes time=not-a-number ms"))
    assert network._ping_rtt(run, "api-0", "app", "ctx", "10.0.0.10") is None
    for experiment_id in (
        "aks-network-delay",
        "aks-packet-loss",
        "aks-packet-corruption",
        "aks-bandwidth-limit",
        "aks-packet-duplication",
    ):
        assert "1 pod(s) NotReady" in network._not_ready_message(experiment_id, 1)


def test_network_live_probe_reports_partition_effects_and_logs_session():
    def run(*args, **kwargs):
        if args[:2] == ("get", "networkchaos"):
            return _json({"items": [{"status": {"conditions": [
                {"type": "AllInjected", "status": "True"}
            ]}}]})
        if args[:1] == ("exec",):
            return _result("CHAOS-DROP all -- anywhere anywhere")
        if args[:2] == ("get", "endpoints"):
            return _json({"subsets": [{"notReadyAddresses": [{"ip": "10.0.0.2"}]}]})
        if args[:2] == ("get", "events"):
            return _result("warning-a\n")
        if args[:2] == ("get", "pods"):
            return _result("bad-json")
        raise AssertionError(args)

    annotate = MagicMock(side_effect=lambda result, *args: result)
    probe = network.build_network_live_probe(
        kubectl=lambda: run,
        find_svc_name=lambda: (lambda *a: ("api", True)),
        select_live_probe_pod=lambda: (lambda *a: "api-0"),
        annotate_network_result=lambda: annotate,
    )
    session = MagicMock()
    result = probe(
        "aks-network-partition", "ctx", "app", "api", "app", "api", session,
        ["-l", "app=api"], ["api-0 0/1 Running 0"], 1, ["api-0"], 0,
    )
    assert result["severity"] == "CHAOS"
    assert "iptables CHAOS chain ACTIVE" in result["message"]
    assert "expected under full network partition" in result["message"]
    assert "Unhealthy probe events: 1" in result["message"]
    assert ("iptables CHAOS chain", "ACTIVE", "Chaos Mesh iptables rule confirmed") in result["net_rows"]
    session.log_event.assert_called_once()
    annotate.assert_called_once()


def test_safety_network_annotation_ignores_bad_rows_and_marks_missing_targets():
    result = {
        "message": "pods healthy | container restarts: unknown",
        "net_rows": [("Container restarts", "unknown", "old")],
    }
    annotated = safety._annotate_network_result(
        result,
        ["malformed", "control-0 1/1 Running 0"],
        ["target-0"],
        restart_baseline=2,
    )
    assert "targeted pod(s) absent: target-0" in annotated["message"]
    assert annotated["net_rows"][0] == ("Container restarts", "unknown", "old")
    assert ("Targeted pods ready", "0 / 1", "actual targets: target-0") in annotated[
        "net_rows"
    ]


def test_safety_prechecks_handle_bad_pod_and_target_label_json():
    checks = safety.build_steady_state_checks(
        "ctx",
        "app",
        "api-0",
        "app",
        "api",
        "aks-network-delay",
        target_mode="pod",
        exact_pod_name="api-0",
    )
    with patch.object(
        safety,
        "_kubectl",
        side_effect=[_result(returncode=1), _result("bad-json")],
    ):
        passed, detail = checks["Replica Floor (api-0)"]()
    assert passed is False
    assert "Could not parse pod JSON" in detail

    with patch.object(safety, "_kubectl", return_value=_result("bad-json")):
        passed, detail = checks["PodDisruptionBudget"]()
    assert passed is True
    assert detail == "Could not parse target pod labels — skipping PDB check"


def test_safety_exact_pod_postchecks_validate_endpoint_and_event_failures():
    checks = safety.build_post_experiment_checks(
        "aks-network-delay",
        "ctx",
        "app",
        "api",
        "app",
        "api",
        target_mode="pod",
        exact_pod_name="api-0",
    )
    pod = _pod()
    pod["status"]["podIP"] = "10.0.0.7"
    endpoint = {"subsets": [{"addresses": [{"ip": "10.0.0.7"}]}]}
    with patch.object(safety, "_find_svc_name", return_value=("api", True)), patch.object(
        safety, "_kubectl", side_effect=[_json({"items": [pod]}), _json(endpoint)]
    ):
        passed, detail = checks["Service Endpoints Restored"]()
    assert passed is True
    assert "restored in Service endpoints" in detail

    with patch.object(safety, "_kubectl", return_value=_result(returncode=1)):
        assert checks["Probe Failures Stopped (post)"]() == (
            True,
            "Could not query probe events — advisory skipped",
        )
    with patch.object(safety, "_kubectl", return_value=_result("bad-json")):
        assert checks["Probe Failures Stopped (post)"]() == (
            True,
            "Could not parse probe events — advisory skipped",
        )


def test_validation_session_full_lifecycle_and_all_result_types(tmp_path):
    session = validation_logger.ValidationSession("aks/test run")
    session.log_dir = str(tmp_path / "logs")
    session.start()

    def runtime_failure():
        raise RuntimeError("blocked by policy")

    def unexpected_failure():
        raise ValueError("malformed response")

    fake_console = MagicMock()
    checks = {
        "Baseline HTTP Response Time": lambda: (True, "p50=2ms\np95=4ms"),
        "Advisory": lambda: (False, "metrics unavailable"),
        "Runtime Failure": runtime_failure,
        "Unexpected / Failure": unexpected_failure,
    }
    with patch(
        "chaosforge.interfaces.cli.interactive.ui.console.console", fake_console
    ), patch.object(validation_logger.time, "monotonic", side_effect=range(20)):
        results = session.run_checks(checks, phase="pre", advisory_labels={"Advisory"})
    session.log_event("chaos", "fault injected")
    session.stop()
    session.stop()

    assert results["Baseline HTTP Response Time"]["passed"] is True
    assert results["Advisory"]["passed"] is False
    assert results["Runtime Failure"]["error"] is True
    assert results["Unexpected / Failure"]["detail"] == "Unexpected: malformed response"
    assert (tmp_path / "logs" / "unexpected___failure.log").exists()
    combined = (tmp_path / "logs" / "session.log").read_text()
    assert "ChaosForge Validation Session" in combined
    assert "CHECK: Baseline HTTP Response Time" in combined
    assert "ERROR: blocked by policy" in combined
    assert "fault injected" in combined
    assert "Total checks: 4  Passed: 1  Failed: 3" in combined
    live_output = "\n".join(
        str(call.args[0]) for call in fake_console.print.call_args_list if call.args
    )
    assert "advisory" in live_output
    assert "2 FAILED" in live_output
    assert "p95=4ms" in live_output


def test_validation_session_reopen_and_non_live_run(tmp_path):
    assert validation_logger.ValidationSession.reopen("exp", str(tmp_path / "missing")) is None
    log_dir = tmp_path / "existing"
    log_dir.mkdir()
    (log_dir / "session.log").write_text("original\n")
    session = validation_logger.ValidationSession.reopen("exp", str(log_dir))
    assert session.log_dir == str(log_dir)
    results = session.run_checks({"Simple": lambda: (True, "ready")}, print_live=False)
    session.stop()
    assert results["Simple"]["passed"] is True
    assert "original" in (log_dir / "session.log").read_text()
    assert "Session complete" in (log_dir / "session.log").read_text()
