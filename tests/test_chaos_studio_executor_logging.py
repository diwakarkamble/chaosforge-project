"""Unit coverage for Chaos Studio execution helpers and presentation logging."""

import json
import sys
import types
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.common.azure_cli import azure_cli_command
from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    executor,
    validation_logger,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    event_log,
)


def _completed(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_kubectl_uses_dispatcher_with_active_context():
    dispatcher = MagicMock(return_value=_completed("from dispatcher"))
    kubernetes_module = types.ModuleType("kubernetes")
    kubernetes_module.run_kubernetes_command = dispatcher
    with patch.dict(sys.modules, {
        "chaosforge.providers.azure.components.aks.kubernetes": kubernetes_module,
    }), patch.object(executor.subprocess, "run") as run:
        executor._ACTIVE_KCTX["context"] = "active-context"
        result = executor._kubectl("get", "pods")

    assert result.stdout == "from dispatcher"
    dispatcher.assert_called_once_with(("get", "pods"), "active-context", timeout=None)
    run.assert_not_called()


def test_kubectl_falls_back_to_subprocess_when_dispatcher_declines():
    kubernetes_module = types.ModuleType("kubernetes")
    fallback = MagicMock(return_value=_completed())
    kubernetes_module.run_kubernetes_command = fallback
    with patch.dict(sys.modules, {
        "chaosforge.providers.azure.components.aks.kubernetes": kubernetes_module,
    }), patch.object(executor.subprocess, "run", return_value=_completed()) as run:
        executor._kubectl("get", "pods", context="explicit", timeout=12)

    fallback.assert_called_once_with(("get", "pods"), "explicit", timeout=12)
    run.assert_not_called()


@pytest.mark.parametrize(
    ("experiment_id", "value", "expected"),
    [
        ("aks-clock-skew-forward", "5m", "+5m"),
        ("aks-clock-skew-forward", "+10s", "+10s"),
        ("aks-clock-skew-backward", "1h", "-1h"),
        ("aks-clock-skew-backward", "-10s", "-10s"),
        ("aks-clock-skew-forward", "-5m", None),
        ("aks-clock-skew-backward", "+5m", None),
        ("aks-clock-skew-forward", "0m", None),
        ("aks-clock-skew-forward", "five minutes", None),
    ],
)
def test_normalize_time_offset_enforces_direction_and_format(experiment_id, value, expected):
    assert executor._normalize_time_offset(experiment_id, value) == expected


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_completed('{"items": [1]}'), {"items": [1]}),
        (_completed("", returncode=1), None),
        (_completed("not json"), None),
    ],
)
def test_kubectl_json_parses_only_successful_json_results(result, expected):
    with patch.object(executor, "_kubectl", return_value=result) as kubectl:
        assert executor._kubectl_json(["kubectl", "get", "pods", "-n", "app"]) == expected

    kubectl.assert_called_once_with("get", "pods", "-n", "app", "-o", "json")


def test_build_network_delay_spec_applies_runtime_values_and_omits_duration_from_studio_spec():
    spec, json_spec, kind = executor._build_spec(
        "aks-network-delay",
        {
            "namespace": "payments",
            "deployment": "api",
            "label_key": "app.kubernetes.io/name",
            "label_val": "checkout",
            "chaos_mode": "fixed",
            "chaos_value": "2",
            "duration": 75,
            "latency": "750ms",
            "jitter": "50ms",
            "correlation": "90",
        },
    )

    assert kind == "NetworkChaos"
    assert spec["duration"] == "75s"
    assert spec["mode"] == "fixed"
    assert spec["value"] == "2"
    assert spec["selector"] == {
        "namespaces": ["payments"],
        "labelSelectors": {"app.kubernetes.io/name": "checkout"},
    }
    assert spec["delay"] == {"latency": "750ms", "jitter": "50ms", "correlation": "90"}
    assert "duration" not in json.loads(json_spec)


def test_build_partition_spec_applies_resolved_selector_to_both_sides():
    selector = {"app": "checkout", "component": "api"}
    spec, _, _ = executor._build_spec(
        "aks-network-partition",
        {
            "namespace": "payments",
            "deployment": "api",
            "label_selectors_map": selector,
            "duration": 30,
        },
    )

    assert spec["selector"]["labelSelectors"] == selector
    assert spec["target"]["selector"]["labelSelectors"] == selector


def test_build_io_specs_override_numeric_values_and_preserve_direct_duration():
    latency_spec, latency_json, latency_kind = executor._build_spec(
        "aks-io-latency",
        {
            "namespace": "payments",
            "deployment": "api",
            "volume_path": "/var/lib/app",
            "io_delay": "250ms",
            "io_percent": "80",
            "duration": 45,
        },
    )
    error_spec, _, error_kind = executor._build_spec(
        "aks-io-errors",
        {"namespace": "payments", "deployment": "api", "io_errno": "28", "io_percent": "65"},
    )

    assert latency_kind == error_kind == "IOChaos"
    assert latency_spec["delay"] == "250ms"
    assert latency_spec["percent"] == 80
    assert latency_spec["volumePath"] == "/var/lib/app"
    assert latency_spec["duration"] == "45s"
    assert "duration" not in json.loads(latency_json)
    assert error_spec["errno"] == 28
    assert error_spec["percent"] == 65


def test_build_spec_rejects_unknown_experiment_and_unresolved_pod_target():
    with pytest.raises(ValueError, match="No spec file"):
        executor._build_spec("aks-not-real", {})

    with pytest.raises(ValueError, match="exact pod name"):
        executor._build_spec(
            "aks-http-delay",
            {"namespace": "payments", "deployment": "api", "target_mode": "pod"},
        )


@pytest.mark.parametrize(
    ("pods", "mode", "value", "expected_pods", "expected_summary"),
    [
        ([], "one", "", [], []),
        (["api-1", "api-2"], "all", "", ["api-1", "api-2"], []),
        (["api-1", "api-2"], "one", "", [], ["1 pod will be randomly selected by Chaos Mesh from 2 matching pod(s)"]),
        (["api-1", "api-2", "api-3"], "fixed", "2", [], ["2 pod(s) will be randomly selected by Chaos Mesh from 3 matching pod(s)"]),
        (["api-1", "api-2"], "fixed", "4", ["api-1", "api-2"], []),
    ],
)
def test_target_selection_preview_reports_deterministic_and_runtime_selected_targets(
    pods, mode, value, expected_pods, expected_summary
):
    assert executor._target_selection_preview(pods, mode, value) == (expected_pods, expected_summary)


def test_extract_chaos_target_pods_handles_record_formats_and_deduplicates():
    crds = [
        {"status": {"experiment": {"containerRecords": [{"id": "payments/api-1/app"}, {"podName": "api-2"}]}}},
        {"status": {"experiment": {"podRecords": {"payments/api-1": {}}}}},
        {"status": {"experiment": {"records": ["payments/api-3"]}}},
    ]

    assert executor._extract_chaos_target_pods(crds) == ["api-1", "api-2", "api-3"]


def test_network_metric_helpers_parse_values_and_preserve_existing_baseline():
    metrics = executor._extract_net_metrics(
        [
            ("RTT", "12.5ms"),
            ("RetransSegs", "3"),
            ("DSACKRecv", "2"),
            ("Endpoints ready", "2 / 3"),
            ("Container restarts", "4"),
            ("Unhealthy probe events", "5 events"),
            ("Malformed",),
            ("RTT", "not-a-number"),
        ]
    )
    baseline = {"rtt_ms": 1.0}
    executor._capture_missing_net_baseline(baseline, metrics)

    assert metrics == {
        "rtt_ms": 12.5,
        "retrans": 3,
        "dsack": 2,
        "endpoints_ready": 2,
        "endpoints_total": 3,
        "restarts": 4,
        "probe_failures": 5,
    }
    assert baseline["rtt_ms"] == 1.0
    assert baseline["retrans"] == 3


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ({}, None),
        ({"Probe Failures Stopped (post)": {"detail": "Skipping unavailable API", "passed": False}}, None),
        ({"Probe Failures Stopped (post)": {"detail": "No new events", "passed": True}}, True),
        ({"Probe Failures Stopped (post)": {"detail": "Events remain", "passed": False}}, False),
    ],
)
def test_probe_recovery_status_distinguishes_unavailable_checks(results, expected):
    assert executor._probe_recovery_status(results) is expected


def test_state_paths_are_sanitized_and_safe_name_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(executor.os, "getpid", lambda: 4321)
    monkeypatch.setattr(executor.time, "time", lambda: 1234567890)

    assert executor._state_file("AKS/Pod Kill!").endswith("aks_chaos_state_akspodkill_4321.json")
    assert executor._http_chaos_sentinel("AKS/HTTP", "App_NS", "API.v1").endswith(
        "aks_http_chaos_setup_akshttp_appns_apiv1.json"
    )
    name = executor._safe_name(
        "aks-pod-kill!",
        {"aks_name": "A" * 80, "namespace": "Payments_Production"},
    )
    assert name.endswith("-1234567890")
    assert len(name) <= 64
    assert name == name.lower()


def test_save_and_load_state_uses_current_process_state_file(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(executor.os, "getpid", lambda: 4321)
    state = {"experiment_id": "aks-pod-kill", "_state_path": str(tmp_path / "aks_chaos_state_aks-pod-kill_4321.json")}

    executor._save_state_field(state, "exact_pod_name", "api-123")

    assert executor._load_state() == {**state, "exact_pod_name": "api-123"}


def test_chaos_resource_group_cache_avoids_repeat_az_calls():
    executor._CHAOS_RG_CACHE.clear()
    responses = [_completed("", returncode=1), _completed()]
    with patch.object(executor.subprocess, "run", side_effect=responses) as run:
        assert executor._get_or_create_chaos_rg("subscription-123", "westus") == "chaosforge-experiments-subscrip"
        assert executor._get_or_create_chaos_rg("subscription-123", "eastus") == "chaosforge-experiments-subscrip"

    assert run.call_count == 2
    assert run.call_args_list[1].args[0][0:4] == azure_cli_command(
        "group", "create", "--name"
    )
    executor._CHAOS_RG_CACHE.clear()


def test_build_studio_experiment_object_constructs_expected_sdk_graph():
    class Model:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    models = types.ModuleType("azure.mgmt.chaos.models")
    for name in (
        "Experiment", "ChaosExperimentStep", "ChaosExperimentBranch", "ContinuousAction",
        "KeyValuePair", "ChaosTargetListSelector", "TargetReference", "ManagedServiceIdentity",
    ):
        setattr(models, name, Model)
    models.TargetReferenceType = types.SimpleNamespace(CHAOS_TARGET="chaosTarget")
    models.ManagedServiceIdentityType = types.SimpleNamespace(USER_ASSIGNED="userAssigned")
    azure = types.ModuleType("azure")
    mgmt = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")

    with patch.dict(sys.modules, {
        "azure": azure,
        "azure.mgmt": mgmt,
        "azure.mgmt.chaos": chaos,
        "azure.mgmt.chaos.models": models,
    }), patch.object(executor, "_get_chaos_identity_id", return_value="/identity"):
        experiment = executor._build_studio_experiment_object(
            '{"kind":"NetworkChaos"}', "urn:test", "sub", "cluster-rg", "aks", {"duration": 61, "location": "eastus"},
        )

    assert experiment.location == "eastus"
    assert experiment.identity.user_assigned_identities == {"/identity": {}}
    action = experiment.steps[0].branches[0].actions[0]
    assert action.name == "urn:test"
    assert action.duration == "PT1M1S"
    assert action.parameters[0].key == "jsonSpec"
    assert experiment.selectors[0].targets[0].id.endswith("managedClusters/aks/providers/Microsoft.Chaos/targets/Microsoft-AzureKubernetesServiceChaosMesh")


def test_resolve_azure_details_short_circuits_valid_explicit_values():
    subscription = "12345678-1234-1234-1234-123456789abc"
    with patch.object(executor.subprocess, "run") as run:
        result = executor._resolve_azure_details("ignored", subscription, "rg", "aks")

    assert result == (subscription, "rg", "aks")
    run.assert_not_called()


def test_resolve_azure_details_accepts_non_uuid_subscription_selected_by_interface():
    with patch(
        "chaosforge.providers.azure.discovery.resolve_subscription_id",
        return_value="12345678-1234-1234-1234-123456789abc",
    ) as resolve, patch.object(executor.subprocess, "run") as run:
        result = executor._resolve_azure_details("ctx", "subscription-alias", "rg", "aks")

    assert result == ("12345678-1234-1234-1234-123456789abc", "rg", "aks")
    resolve.assert_called_once_with("subscription-alias")
    run.assert_not_called()


def test_resolve_azure_details_uses_first_cluster_when_context_does_not_match():
    responses = [
        _completed('{"id": "sub-1"}'),
        _completed(json.dumps([{"name": "aks-a", "rg": "rg-a"}])),
    ]
    with patch(
        "chaosforge.providers.azure.discovery.resolve_subscription_id",
        return_value="sub-1",
    ), patch.object(executor.subprocess, "run", side_effect=responses):
        assert executor._resolve_azure_details("unrelated", "", "", "") == (
            "sub-1", "rg-a", "aks-a"
        )


def test_resolve_azure_details_uses_only_cluster_in_selected_resource_group():
    responses = [
        _completed('{"id": "sub"}'),
        _completed(json.dumps([{"name": "aks-a", "rg": "rg-a"}])),
    ]
    with patch(
        "chaosforge.providers.azure.discovery.resolve_subscription_id",
        return_value="sub",
    ), patch.object(executor.subprocess, "run", side_effect=responses) as run:
        assert executor._resolve_azure_details("unrelated-context", "sub", "rg-a", "") == (
            "sub",
            "rg-a",
            "aks-a",
        )

    assert "--resource-group" in run.call_args_list[1].args[0]


def test_helper_error_and_fallback_paths_are_safe_and_actionable(monkeypatch, tmp_path):
    with patch.object(executor, "SPEC_DIR", str(tmp_path)):
        with patch.object(executor.os.path, "exists", return_value=False):
            with pytest.raises(FileNotFoundError, match="Spec not found"):
                executor._build_spec("aks-pod-kill", {})

    with patch.object(executor, "_kubectl", return_value=_completed("", returncode=1)):
        assert executor._read_chaos_target_pods("podchaos", "ctx") == []
        assert executor._read_restart_total("app", "app=api", "ctx") is None

    with patch.object(executor, "_kubectl", return_value=_completed("not json")):
        assert executor._read_chaos_target_pods("podchaos", "ctx") == []


def test_load_state_skips_invalid_files_and_delete_studio_resource_is_nonfatal(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(executor.os, "getpid", lambda: 77)
    (tmp_path / "aks_chaos_state_bad_77.json").write_text("not-json")
    (tmp_path / "aks_chaos_state_good_77.json").write_text('{"ok": true}')
    assert executor._load_state() == {"ok": True}

    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    mgmt = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")
    identity.DefaultAzureCredential = MagicMock
    client = MagicMock()
    client.experiments.begin_delete.side_effect = RuntimeError("unavailable")
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    with patch.dict(sys.modules, {
        "azure": azure, "azure.identity": identity, "azure.mgmt": mgmt,
        "azure.mgmt.chaos": chaos,
    }):
        executor._delete_studio_experiment("sub", "rg", "exp")
    assert "could not delete Studio experiment 'exp'" in capsys.readouterr().out


def test_az_rest_put_logs_and_raises_command_error():
    session = MagicMock()
    with patch.object(executor.subprocess, "run", return_value=_completed(stderr="denied", returncode=1)):
        with pytest.raises(RuntimeError, match="registration failed for target"):
            executor._az_rest_put("https://example.test/resource", "target", session=session)

    session.log_event.assert_any_call("experiment-setup", "PUT target — start")
    assert "FAILED" in session.log_event.call_args_list[-1].args[1]


def test_az_rest_put_translates_timeout_to_actionable_error():
    with patch.object(executor.subprocess, "run", side_effect=TimeoutExpired(["az"], 30)):
        with pytest.raises(RuntimeError, match=r"Timed out \(30s\) registering target"):
            executor._az_rest_put("https://example.test/resource", "target")


def test_read_restart_total_uses_exact_pod_selector_and_handles_invalid_json():
    payload = {"items": [{"status": {"containerStatuses": [{"restartCount": 2}, {"restartCount": 3}]}}]}
    with patch.object(executor, "_kubectl", return_value=_completed(json.dumps(payload))) as kubectl:
        assert executor._read_restart_total("ns", "app=api", "ctx", "api-1") == 5

    assert "--field-selector" in kubectl.call_args.args
    with patch.object(executor, "_kubectl", return_value=_completed("not json")):
        assert executor._read_restart_total("ns", "app=api", "ctx") is None


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "PT0S"), (61, "PT1M1S"), (3661, "PT1H1M1S")],
)
def test_seconds_to_iso8601_formats_duration_components(seconds, expected):
    assert executor._seconds_to_iso8601(seconds) == expected


def test_validation_session_records_pass_runtime_error_and_unexpected_error(tmp_path):
    session = validation_logger.ValidationSession("api/test run")
    session.log_dir = str(tmp_path / "logs")
    session.start()

    def runtime_failure():
        raise RuntimeError("blocked")

    def unexpected_failure():
        raise ValueError("bad response")

    results = session.run_checks(
        {
            "Healthy Check": lambda: (True, "ready"),
            "Runtime Failure": runtime_failure,
            "Unexpected Failure": unexpected_failure,
        },
        print_live=False,
    )
    session.stop()

    assert results["Healthy Check"]["passed"] is True
    assert results["Runtime Failure"]["passed"] is False
    assert results["Runtime Failure"]["error"] is True
    assert results["Runtime Failure"]["detail"] == "blocked"
    assert results["Unexpected Failure"]["detail"] == "Unexpected: bad response"
    session_log = (tmp_path / "logs" / "session.log").read_text()
    assert "CHECK: Healthy Check" in session_log
    assert "ERROR: blocked" in session_log
    assert "Total checks: 3  Passed: 1  Failed: 2" in session_log


def test_validation_session_reopen_appends_and_missing_directory_returns_none(tmp_path):
    assert validation_logger.ValidationSession.reopen("exp", "") is None
    log_dir = tmp_path / "existing"
    log_dir.mkdir()
    session = validation_logger.ValidationSession.reopen("exp", str(log_dir))
    session.log_event("run", "continued")
    session.stop()
    assert "continued" in (log_dir / "session.log").read_text()


def test_validation_session_persists_unicode_check_output_as_utf8(tmp_path):
    session = validation_logger.ValidationSession("unicode")
    session.log_dir = str(tmp_path / "logs")
    session.start()
    session.run_checks({"Nodes Ready": lambda: (True, "✔ Ready — stable")}, print_live=False)
    session.stop()

    assert "✔ Ready — stable" in (tmp_path / "logs" / "nodes_ready.log").read_text(encoding="utf-8")


def test_validation_session_live_summary_distinguishes_advisory_failures(tmp_path):
    session = validation_logger.ValidationSession("exp")
    session.log_dir = str(tmp_path / "logs")
    session.start()
    fake_console = MagicMock()
    with patch(
        "chaosforge.interfaces.cli.interactive.ui.console.console",
        fake_console,
    ):
        session.run_checks(
            {"Advisory": lambda: (False, "optional")},
            advisory_labels={"Advisory"},
        )
    session.stop()

    output = "\n".join(str(call.args[0]) for call in fake_console.print.call_args_list if call.args)
    assert "advisory — non-blocking" in output
    assert "ALL PASSED" in output


def test_event_log_formats_lines_metrics_and_experiment_banner():
    live = MagicMock()
    event_log.log_line(live, "custom", "message", ts="12:00:00")
    event_log.log_stress_metrics(
        live,
        "12:00:01",
        {"summary": "active", "pod_rows": [("api", "app", "10m", "20Mi")], "node_rows": [("node", "1", "2%", "3Mi", "4%")]},
    )
    event_log.log_net_metrics(
        live,
        "12:00:02",
        {"severity": "WARNING", "message": "loss", "net_rows": [("RTT", "10 ms"), ("Empty",)]},
    )
    lines = event_log.format_experiment_start(
        "aks-pod-kill", "ns", "api", 30, False, target_pods=["api-1"], chaos_mode="one"
    )

    printed = "\n".join(call.args[0] for call in live.console.print.call_args_list)
    assert "CUSTOM" in printed
    assert "POD" in printed and "NODE" in printed and "METRIC" in printed
    assert "[bold red]WARNING" in printed
    assert "eligible pod pool" in "\n".join(lines)
    assert "LIVE FAULT" in lines[0]


def test_event_log_banner_uses_summary_when_pods_are_not_resolved():
    lines = event_log.format_experiment_start(
        "unknown", "ns", "api", 10, True, target_summary=["selector matched 2 pods"]
    )
    rendered = "\n".join(lines)
    assert "unknown" in rendered
    assert "DRY RUN PREVIEW" in rendered
    assert "selector matched 2 pods" in rendered
