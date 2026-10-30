"""Mocked coverage for the remaining AKS Chaos Studio production paths."""

import json
import sys
import types
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import executor
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import safety


def _result(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def test_io_live_probe_reports_success_and_failure(monkeypatch):
    pods = {"items": [{"metadata": {"name": "api"}, "status": {
        "phase": "Running", "containerStatuses": [{"restartCount": 1}],
    }}]}
    chaos = {"items": [{"status": {"conditions": [{"type": "AllInjected", "status": "True"}]}}]}
    responses = iter([
        _result("api 1/1 Running 0"), _result(json.dumps(chaos)),
        _result(json.dumps(pods)), _result(stderr="permission denied", returncode=1),
        _result("api 1/1 Running 0"), _result(json.dumps(chaos)),
        _result(json.dumps(pods)), _result(),
    ])
    monkeypatch.setattr(safety, "_kubectl", lambda *_args, **_kwargs: next(responses))
    monotonic = iter([1.0, 1.025, 2.0, 2.01])
    monkeypatch.setattr("time.monotonic", lambda: next(monotonic))

    failed = safety.verify_fault_active("aks-io-errors", "ctx", "ns", "api")
    passed = safety.verify_fault_active("aks-io-latency", "ctx", "ns", "api")

    assert "I/O probe FAILED: permission denied" in failed["message"]
    assert passed["io_ms"] == 9
    assert "I/O round-trip: 9ms" in passed["message"]


def test_post_recovery_waits_before_polling(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr(safety.time, "sleep", sleep)
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.kubernetes.get_pods",
        MagicMock(return_value=([{"metadata": {"name": "api"}, "status": {"phase": "Running"}}], None)),
    )
    checks = safety.build_post_experiment_checks(
        "aks-pod-kill", "ctx", "ns", "api", recovery_wait_seconds=3,
    )

    assert checks["Pod Recovery"]()[0] is True
    sleep.assert_called_once_with(3)


def test_io_summary_formats_target_delta_and_elevated_post(monkeypatch):
    console = MagicMock()
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.console.console", console,
    )
    executor._print_io_impact_summary(
        "aks-io-latency", {"io_ms": 10}, {"io_ms": 25}, 30, True, ["api"], 100,
    )
    text = " ".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
    assert "Actual targeted pod(s)" in text
    assert len(console.print.call_args_list) == 6

    executor._print_io_impact_summary(
        "aks-io-errors", {"io_ms": 25}, {"io_ms": 25}, 30, True,
    )


def test_read_io_baseline_handles_probe_success_and_unavailable(monkeypatch):
    running = json.dumps({"items": [{"metadata": {"name": "api"}, "status": {"phase": "Running"}}]})
    monkeypatch.setattr(executor, "_kubectl", MagicMock(side_effect=[_result(running), _result()]))
    ticks = iter([1.0, 1.012])
    monkeypatch.setattr("time.monotonic", lambda: next(ticks))
    assert executor._read_io_baseline_ms("ns", "app=api", "ctx", "/mnt/") == 12

    monkeypatch.setattr(executor, "_kubectl", MagicMock(return_value=_result(json.dumps({"items": []}))))
    assert executor._read_io_baseline_ms("ns", "app=api", "ctx") is None

    monkeypatch.setattr(executor, "_kubectl", MagicMock(return_value=_result("not json")))
    assert executor._read_io_baseline_ms("ns", "app=api", "ctx") is None

    monkeypatch.setattr(executor, "_kubectl", MagicMock(return_value=_result(returncode=1)))
    assert executor._read_io_baseline_ms("ns", "app=api", "ctx") is None

    monkeypatch.setattr(executor, "_kubectl", MagicMock(side_effect=[_result(running), _result(returncode=1)]))
    ticks = iter([3.0, 3.01])
    monkeypatch.setattr("time.monotonic", lambda: next(ticks))
    assert executor._read_io_baseline_ms("ns", "app=api", "ctx") is None


def test_cleanup_records_io_post_measurement(monkeypatch, tmp_path):
    state = {"_state_path": str(tmp_path / "state.json"), "duration": 1}
    session = MagicMock()
    session.run_checks.return_value = {
        "Residual I/O Fault Check": {"passed": True, "detail": "round-trip = 17ms"},
    }
    monkeypatch.setattr(executor, "_load_state", lambda *_: state)
    monkeypatch.setattr(executor, "_reopen_session", lambda *_: session)
    monkeypatch.setattr(executor, "PhaseUI", lambda *_: SimpleNamespace(phase=lambda *_: nullcontext(), step=lambda *_a, **_k: None))
    monkeypatch.setattr(executor, "_kubectl", lambda *_a, **_k: _result())
    monkeypatch.setattr(executor, "build_post_experiment_checks", lambda *_a, **_k: {"Residual I/O Fault Check": lambda: (True, "ok")})
    monkeypatch.setattr(executor.os.path, "exists", lambda *_: False)

    executor.cleanup_experiment("aks-io-latency", "ctx", "ns", "api")
    assert state["_io_post_ms"] == 17


def test_setup_captures_io_baseline_from_precheck_detail(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path))
    session._results = {"Baseline File I/O Timing": {"detail": "round-trip = 23ms"}}
    monkeypatch.setattr(executor, "ValidationSession", lambda *_: session)
    monkeypatch.setattr(executor, "PhaseUI", lambda *_: SimpleNamespace(phase=lambda *_: nullcontext(), step=lambda *_a, **_k: None))
    monkeypatch.setattr(executor, "_state_file", lambda *_: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", lambda *_a, **_k: None)
    monkeypatch.setattr(executor, "_kubectl", lambda *_a, **_k: _result())
    monkeypatch.setattr(executor, "run_parallel_steady_state", lambda *_a, **_k: None)

    executor.setup_studio("aks-io-latency", "ctx", "ns", "api", dry_run="true")
    assert json.loads(state_path.read_text())["_io_baseline_ms"] == 23


def _install_runtime(monkeypatch, client):
    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    management = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")
    live = types.ModuleType("rich.live")
    identity.DefaultAzureCredential = MagicMock
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live.Live = type("Live", (), {
        "__init__": lambda self, *_a, **_k: setattr(self, "console", MagicMock()),
        "__enter__": lambda self: self,
        "__exit__": lambda self, *_a: False,
        "update": lambda self, *_a: None,
    })
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    monkeypatch.setitem(sys.modules, "azure.mgmt", management)
    monkeypatch.setitem(sys.modules, "azure.mgmt.chaos", chaos)
    monkeypatch.setitem(sys.modules, "rich.live", live)
    monkeypatch.setattr(executor.time, "sleep", lambda *_: None)


def test_runtime_uses_precheck_io_baseline_and_persists_peak(monkeypatch):
    client = MagicMock()
    client.experiments.list_all_executions.side_effect = [[SimpleNamespace(name="run")], [SimpleNamespace(name="run")]]
    client.experiments.get_execution.side_effect = [SimpleNamespace(status="Running"), SimpleNamespace(status="Succeeded")]
    _install_runtime(monkeypatch, client)
    monkeypatch.setattr(executor, "_kubectl", lambda *_a, **_k: _result("api Running"))
    monkeypatch.setattr(executor, "_read_io_baseline_ms", MagicMock())
    monkeypatch.setattr(executor, "verify_fault_active", lambda *_a, **_k: {"message": "io active", "severity": "CHAOS", "crd_injected": True, "io_ms": 31})
    state = {"experiment_id": "aks-io-latency", "duration": 1, "namespace": "ns", "deployment": "api", "_io_baseline_ms": 12, "_experiment_pre_created": True}

    executor._run_studio_experiment("exp", "{}", "urn", "sub", "rg", "aks", state)
    assert state["_io_pre_fault"] == {"io_ms": 12}
    assert state["_io_peak"] == {"io_ms": 31}


def test_runtime_falls_back_to_io_probe_and_logs_live_update(monkeypatch):
    client = MagicMock()
    client.experiments.list_all_executions.side_effect = [[SimpleNamespace(name="run")], [SimpleNamespace(name="run")]]
    client.experiments.get_execution.side_effect = [SimpleNamespace(status="Running"), SimpleNamespace(status="Succeeded")]
    _install_runtime(monkeypatch, client)
    monkeypatch.setattr(executor, "_kubectl", lambda *_a, **_k: _result("api Running"))
    monkeypatch.setattr(executor, "_read_io_baseline_ms", MagicMock(return_value=8))
    observations = iter([
        {"message": "burst", "severity": "CHAOS", "crd_injected": True, "io_ms": 9},
        {"message": "burst", "severity": "CHAOS", "crd_injected": True, "io_ms": 9},
        {"message": "burst", "severity": "CHAOS", "crd_injected": True, "io_ms": 9},
        {"message": "live", "severity": "CHAOS", "crd_injected": True, "io_ms": 20},
    ])
    monkeypatch.setattr(executor, "verify_fault_active", lambda *_a, **_k: next(observations, {"message": "live", "crd_injected": True, "io_ms": 20}))
    state = {"experiment_id": "aks-io-errors", "duration": 11, "namespace": "ns", "deployment": "api", "_experiment_pre_created": True}

    executor._run_studio_experiment("exp", "{}", "urn", "sub", "rg", "aks", state)
    assert state["_io_pre_fault"] == {"io_ms": 8}
    assert state["_io_peak"] == {"io_ms": 20}
