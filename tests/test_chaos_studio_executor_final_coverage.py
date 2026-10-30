"""Behavior coverage for the final reachable AKS Chaos Studio executor paths."""

import builtins
import json
import sys
import types
from contextlib import nullcontext
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    executor,
    validation_logger,
)


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class _UI:
    def __init__(self):
        self.steps = []
        self.statuses = []

    def phase(self, _name):
        return nullcontext()

    def step(self, message, **_kwargs):
        self.steps.append(message)

    def status(self, message, **kwargs):
        self.statuses.append((message, kwargs))


class _Live:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.console = MagicMock()
        self.updates = []
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def update(self, value):
        self.updates.append(value)


@pytest.fixture
def ui(monkeypatch):
    value = _UI()
    monkeypatch.setattr(executor, "PhaseUI", lambda _experiment: value)
    return value


def _install_runtime(monkeypatch, client):
    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    management = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")
    identity.DefaultAzureCredential = MagicMock
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live")
    live.Live = _Live
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    monkeypatch.setitem(sys.modules, "azure.mgmt", management)
    monkeypatch.setitem(sys.modules, "azure.mgmt.chaos", chaos)
    monkeypatch.setitem(sys.modules, "rich.live", live)
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    _Live.instances.clear()


def _install_vmss_models(monkeypatch, client):
    _install_runtime(monkeypatch, client)
    models = types.ModuleType("azure.mgmt.chaos.models")

    class Model:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    for name in (
        "Experiment",
        "ChaosExperimentStep",
        "ChaosExperimentBranch",
        "ContinuousAction",
        "KeyValuePair",
        "ChaosTargetListSelector",
        "TargetReference",
        "ManagedServiceIdentity",
    ):
        setattr(models, name, Model)
    models.TargetReferenceType = SimpleNamespace(CHAOS_TARGET="target")
    models.ManagedServiceIdentityType = SimpleNamespace(USER_ASSIGNED="identity")
    monkeypatch.setitem(sys.modules, "azure.mgmt.chaos.models", models)


def _prepare_setup(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", MagicMock())
    monkeypatch.setattr(executor, "_kubectl", MagicMock(return_value=_result()))
    monkeypatch.setattr(executor, "run_parallel_steady_state", MagicMock())
    return state_path, session


def test_setup_crashloop_uses_safe_default_precheck_and_http_sentinel_failure_is_nonfatal(
    monkeypatch, tmp_path, ui
):
    state_path, _session = _prepare_setup(monkeypatch, tmp_path)
    executor.setup_studio(
        "aks-crashloop", "ctx", "app", "api", target_node="node-a", dry_run="true"
    )
    state = json.loads(state_path.read_text())
    assert state["_node_precheck_ok"] is True
    assert state["_node_precheck_snapshot"] == {}

    real_open = builtins.open

    def fail_sentinel(path, mode="r", *args, **kwargs):
        if mode == "w" and "aks_http_chaos_setup" in str(path):
            raise OSError("read-only temp directory")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(tmp_path / "http-state.json"))
    with patch.object(builtins, "open", side_effect=fail_sentinel):
        executor.setup_studio("aks-http-delay", "ctx", "", "", dry_run="true")
    assert (tmp_path / "http-state.json").exists()


def test_state_loading_is_scoped_and_skips_corrupt_pid_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(executor.os, "getpid", lambda: 41)
    exact = tmp_path / "aks_chaos_state_aks-pod-kill_41.json"
    exact.write_text('{"run": "exact"}')
    assert executor._load_state("aks-pod-kill") == {"run": "exact"}

    exact.write_text("bad-json")
    assert executor._load_state("aks-pod-kill") == {}

    exact.unlink()
    (tmp_path / "aks_chaos_state_a_41.json").write_text("bad-json")
    (tmp_path / "aks_chaos_state_b_41.json").write_text('{"run": "fallback"}')
    assert executor._load_state() == {"run": "fallback"}


def test_azure_resolution_honors_name_context_resource_group_and_errors(monkeypatch):
    discovery = __import__("chaosforge.providers.azure.discovery", fromlist=["resolve_subscription_id"])
    canonical = MagicMock(return_value="canonical-sub")
    monkeypatch.setattr(discovery, "resolve_subscription_id", canonical)

    responses = [
        _result('{"id": "active"}'),
        _result('[{"name":"aks-a","rg":"rg-a"},{"name":"aks-b","rg":"rg-b"}]'),
    ]
    with patch.object(executor.subprocess, "run", side_effect=responses):
        assert executor._resolve_azure_details("other", "alias", "rg-b", "aks-b") == (
            "canonical-sub",
            "rg-b",
            "aks-b",
        )
    canonical.assert_called_with("alias")

    with patch.object(
        executor.subprocess,
        "run",
        side_effect=[_result('{"id":"active"}'), _result("[]", returncode=1)],
    ):
        with pytest.raises(RuntimeError, match="Could not resolve the selected AKS cluster"):
            executor._resolve_azure_details("other", "", "", "")

    with patch.object(executor.subprocess, "run", side_effect=ValueError("malformed CLI output")):
        with pytest.raises(RuntimeError, match="Could not resolve Azure details.*malformed"):
            executor._resolve_azure_details("other", "", "", "")


def test_studio_polling_retries_observes_fault_and_reports_cancelled_detail(
    monkeypatch, ui
):
    client = MagicMock()
    client.experiments.list_all_executions.side_effect = [
        ValueError("eventual consistency"),
        [SimpleNamespace(name="run")],
        [SimpleNamespace(name="run")],
    ]
    client.experiments.get_execution.side_effect = [
        SimpleNamespace(status="Running"),
        SimpleNamespace(status="Cancelled"),
    ]
    _install_runtime(monkeypatch, client)
    session = MagicMock()
    seen_calls = 0

    def observe(*_args, **kwargs):
        nonlocal seen_calls
        seen_calls += 1
        if seen_calls == 1:
            raise OSError("probe race")
        kwargs["_seen_killed"].add("api-1")
        if seen_calls == 2:
            return {"message": "fault active", "severity": "CHAOS"}
        return {"pod_rows": [("api-1", "app", "1m", "16Mi")], "message": "stress"}

    state = {
        "experiment_id": "aks-pod-kill",
        "duration": 1,
        "namespace": "app",
        "deployment": "api",
        "aks_context": "",
        "_experiment_pre_created": True,
    }
    with patch.object(executor, "_kubectl", side_effect=OSError("offline")), patch.object(
        executor, "verify_fault_active", side_effect=observe
    ), patch.object(executor, "_get_experiment_failure_detail", return_value="operator cancelled"):
        with pytest.raises(RuntimeError, match="Reason: operator cancelled"):
            executor._run_studio_experiment(
                "exp", "{}", "urn", "sub", "rg", "aks", state, ui=ui, session=session
            )

    assert _Live.instances[-1].updates
    assert any("Terminal status: Cancelled" in call.args[1] for call in session.log_event.call_args_list)
    assert any("Failure detail: operator cancelled" in call.args[1] for call in session.log_event.call_args_list)


def test_studio_polling_propagates_runtime_errors(monkeypatch, ui):
    client = MagicMock()
    client.experiments.list_all_executions.side_effect = RuntimeError("authorization lost")
    _install_runtime(monkeypatch, client)
    with patch.object(executor, "_kubectl", return_value=_result()):
        with pytest.raises(RuntimeError, match="authorization lost"):
            executor._run_studio_experiment(
                "exp",
                "{}",
                "urn",
                "sub",
                "rg",
                "aks",
                {"experiment_id": "aks-pod-kill", "duration": 1, "_experiment_pre_created": True},
                ui=ui,
            )


@pytest.mark.parametrize("runner", ["vmss", "zone"])
def test_node_studio_polling_propagates_runtime_errors(runner, monkeypatch, tmp_path, ui):
    client = MagicMock()
    client.experiments.get.side_effect = RuntimeError("not found")
    client.experiments.list_all_executions.side_effect = RuntimeError("poll denied")
    _install_vmss_models(monkeypatch, client)
    monkeypatch.setattr(executor, "_get_chaos_identity_id", lambda *_: "identity")

    if runner == "vmss":
        state = {
            "experiment_id": "aks-node-notready",
            "duration": 1,
            "vmss_name": "pool",
            "instance_id": "1",
            "_state_path": str(tmp_path / "vmss.json"),
        }
        with patch.object(executor, "_get_node_names", return_value={"node-a"}):
            with pytest.raises(RuntimeError, match="poll denied"):
                executor._run_vmss_experiment(
                    "exp", {}, "urn", "sub", "nrg", "arg", "aks", "node-a", state, ui=ui
                )
    else:
        state = {
            "experiment_id": "aks-node-zone-failure",
            "duration": 1,
            "_node_precheck_ok": True,
            "_node_precheck_snapshot": {},
            "_state_path": str(tmp_path / "zone.json"),
        }
        targets = [{"node": "zone-a", "vmss_name": "pool", "instance_id": "1"}]
        with pytest.raises(RuntimeError, match="poll denied"):
            executor._run_zone_failure(
                "exp", {}, "urn", "sub", "nrg", "arg", "aks", targets, state, ui=ui
            )


def test_zone_poll_timeout_records_observed_nodes(monkeypatch, tmp_path, ui):
    client = MagicMock()
    client.experiments.get.side_effect = RuntimeError("not found")
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.return_value = SimpleNamespace(status="Running")
    _install_vmss_models(monkeypatch, client)
    monkeypatch.setattr(executor, "_get_chaos_identity_id", lambda *_: "identity")
    state_path = tmp_path / "zone-timeout.json"
    state = {
        "experiment_id": "aks-node-zone-failure",
        "duration": 1,
        "_node_precheck_ok": True,
        "_node_precheck_snapshot": {},
        "_state_path": str(state_path),
    }
    targets = [{"node": "zone-a", "vmss_name": "pool", "instance_id": "1"}]
    with patch.object(executor, "_get_node_conditions", return_value={"Ready": "False"}), patch.object(
        executor, "_kubectl_json", return_value={"items": []}
    ):
        executor._run_zone_failure(
            "exp", {}, "urn", "sub", "nrg", "arg", "aks", targets, state, ui=ui
        )
    assert "Experiment completed (status poll timed out)" in ui.steps
    assert json.loads(state_path.read_text())["_zone_snapshot"]["nodes_notready_seen"] == [
        "zone-a"
    ]


def test_helper_fallbacks_filter_canaries_and_handle_invalid_restart_count(monkeypatch, tmp_path, ui):
    with patch.object(executor, "_kubectl", return_value=_result("chaos=NoExecute")):
        assert executor._node_has_chaos_taint("node-a") is True
    with patch.object(
        executor,
        "_kubectl_json",
        return_value={"spec": {"taints": [{"key": "other", "effect": "NoExecute"}]}},
    ):
        assert executor._node_taint_confirmed("node-a") is False

    pods = {
        "items": [
            {
                "metadata": {"name": "pending", "namespace": "app"},
                "status": {"phase": "Pending"},
                "spec": {"containers": [{"name": "web"}]},
            }
        ]
    }
    with patch.object(executor, "_kubectl_json", return_value=pods):
        assert executor._resolve_node_stress_canary("node-a") is None

    path = tmp_path / "crash.json"

    class Temp:
        name = str(path)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, value):
            path.write_text(value)
            return len(value)

    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", lambda **_kwargs: Temp())
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    times = iter([0, 0, 0, 2])
    monkeypatch.setattr(executor.time, "time", lambda: next(times))

    def kubectl(*args, **_kwargs):
        if args[:2] == ("get", "pods") and "--field-selector=status.phase=Running" in args:
            return _result("api-1")
        if args[:2] == ("get", "pods"):
            return _result("api-1 1/1 Running invalid 1m")
        return _result()

    with patch.object(executor, "_kubectl", side_effect=kubectl):
        executor._run_crashloop(
            {"namespace": "app", "label_key": "app", "label_val": "api", "duration": 1},
            ui=ui,
        )
    assert not path.exists()


def test_stress_precheck_without_metrics_and_postcheck_dns_baseline_fallback(
    monkeypatch, ui
):
    conditions = {
        "Ready": "True",
        "DiskPressure": "False",
        "MemoryPressure": "False",
        "PIDPressure": "False",
    }
    with patch.object(executor, "_get_node_conditions", return_value=conditions), patch.object(
        executor, "_kubectl", side_effect=[_result(), _result()]
    ), patch.object(executor, "_get_node_top", return_value=None), patch.object(
        executor, "_get_unhealthy_pods", return_value=[]
    ), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(
        executor, "_get_pod_restart_counts", return_value={}
    ), patch.object(executor, "_node_pod_count", return_value=0), patch.object(
        executor, "_get_node_stress_workload_status", return_value=None
    ), patch.object(executor, "_resolve_node_stress_canary", return_value=None), patch.object(
        executor.console, "print"
    ) as output:
        ok, snapshot = executor._prechecks_node_stress("node-a", "cpu", ui=ui)
    assert ok is True and snapshot["baseline_top"] is None
    assert any("metrics-server unavailable" in str(call.args[0]) for call in output.call_args_list)

    snapshot.update(
        {
            "canary": {"namespace": "app", "pod": "api"},
            "canary_worst_dns_ms": 20,
            "canary_baseline": None,
            "restarts_before": [],
        }
    )
    with patch.object(executor.time, "sleep", lambda _seconds: None), patch.object(
        executor, "_get_node_top", return_value=None
    ), patch.object(executor, "_get_node_conditions", return_value=conditions), patch.object(
        executor, "_get_pod_restart_counts", return_value={}
    ), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(
        executor, "_get_unhealthy_pods", return_value=[]
    ), patch.object(executor, "_kubectl", return_value=_result()), patch.object(
        executor.console, "print"
    ) as output:
        executor._postchecks_node_stress("node-a", "cpu", snapshot, ui=ui)
    assert any("Worst DNS lookup time" in str(call.args[0]) for call in output.call_args_list)


def test_validation_logger_handles_detail_read_failure_and_all_passed_summary(
    monkeypatch, tmp_path
):
    session = validation_logger.ValidationSession("final")
    session.log_dir = str(tmp_path / "logs")
    session.start()
    real_open = builtins.open

    def fail_check_read(path, mode="r", *args, **kwargs):
        if mode == "r" and str(path).endswith("healthy.log"):
            raise OSError("log rotated")
        return real_open(path, mode, *args, **kwargs)

    console = MagicMock()
    with patch.object(builtins, "open", side_effect=fail_check_read), patch(
        "chaosforge.interfaces.cli.interactive.ui.console.console", console
    ):
        results = session.run_checks({"Healthy": lambda: (True, "ready")})
    session.stop()

    assert results["Healthy"]["passed"] is True
    rendered = "\n".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
    assert "ALL PASSED" in rendered
