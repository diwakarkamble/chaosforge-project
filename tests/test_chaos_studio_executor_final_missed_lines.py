"""Tests for the final executable fallback and status-reporting paths."""

import json
import sys
import threading
import types
from contextlib import nullcontext
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import executor


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class _UI:
    def __init__(self):
        self.steps = []

    def phase(self, _name):
        return nullcontext()

    def step(self, message, **_kwargs):
        self.steps.append(message)

    def status(self, *_args, **_kwargs):
        pass


class _Live:
    def __init__(self, *_args, **_kwargs):
        self.console = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def update(self, *_args):
        pass


def _install_studio_runtime(monkeypatch, client):
    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    management = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")
    live = types.ModuleType("rich.live")
    identity.DefaultAzureCredential = MagicMock
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live.Live = _Live
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    monkeypatch.setitem(sys.modules, "azure.mgmt", management)
    monkeypatch.setitem(sys.modules, "azure.mgmt.chaos", chaos)
    monkeypatch.setitem(sys.modules, "rich.live", live)
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)


def test_setup_ignores_http_sentinel_write_error(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "PhaseUI", lambda _id: _UI())
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_kubectl", lambda *_args, **_kwargs: _result())
    monkeypatch.setattr(executor, "run_parallel_steady_state", lambda *_args, **_kwargs: None)
    real_open = open

    def deny_sentinel(path, mode="r", *args, **kwargs):
        if mode == "w" and "aks_http_chaos_setup" in str(path):
            raise OSError("read-only")
        return real_open(path, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=deny_sentinel):
        executor.setup_studio("aks-http-delay", "ctx", "app", "api", dry_run="true")

    assert json.loads(state_path.read_text())["_setup_complete"] is True


def test_remaining_warning_resolution_and_state_default_paths(monkeypatch):
    monkeypatch.setattr(
        executor,
        "POD_DISRUPTIVE_EXPERIMENTS",
        executor.POD_DISRUPTIVE_EXPERIMENTS - {"aks-crashloop"},
    )
    assert "CrashLoopBackOff" in executor._destructive_warning("aks-crashloop")

    responses = [_result('{"id":"sub"}'), _result('[{"name":"aks","rg":"rg"}]')]
    with patch.object(executor.subprocess, "run", side_effect=responses):
        assert executor._resolve_azure_details("ctx", "", "", "aks") == ("sub", "rg", "aks")

    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    with patch.object(executor, "_node_is_ready", return_value=True), patch.object(
        executor, "_node_is_schedulable", return_value=True
    ), patch.object(executor, "_get_node_conditions", return_value={
        "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False"
    }), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(
        executor, "_pending_pods_exist", return_value=[]
    ), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(
        executor, "_get_node_names", return_value=set()
    ), patch.object(executor.console, "print"):
        executor._postchecks_node_drain("node", state=None)
        executor._postchecks_node_taint("node", state=None)


def test_node_holds_show_running_and_stuck_states(monkeypatch):
    live_module = types.ModuleType("rich.live")
    live_module.Live = _Live
    monkeypatch.setitem(sys.modules, "rich.live", live_module)
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)

    class DrainThread:
        def __init__(self, target, **_kwargs):
            self.target = target
            self.calls = 0

        def start(self):
            pass

        def is_alive(self):
            self.calls += 1
            if self.calls == 2:
                self.target()
            return self.calls <= 2

    monkeypatch.setattr(threading, "Thread", DrainThread)
    with patch.object(executor, "_get_node_names", return_value={"node"}), patch.object(
        executor, "_node_pod_count", return_value=1
    ), patch.object(executor, "_node_is_schedulable", return_value=False), patch.object(
        executor, "_kubectl", return_value=_result()
    ):
        executor._run_node_drain("node", {"duration": 31}, ui=_UI())

    with patch.object(executor, "_get_node_names", return_value={"node"}), patch.object(
        executor, "_kubectl", return_value=_result()
    ), patch.object(executor, "_node_pod_count", return_value=1), patch.object(
        executor, "_node_is_schedulable", return_value=False
    ), patch.object(executor, "_node_taint_confirmed", return_value=True):
        executor._run_node_taint("node", {"duration": 31}, ui=_UI())


def test_studio_polling_reports_starting_target_filter_and_probe_fallback(monkeypatch):
    client = MagicMock()
    client.experiments.list_all_executions.side_effect = [
        [types.SimpleNamespace(name="run")], [types.SimpleNamespace(name="run")],
    ]
    client.experiments.get_execution.side_effect = [
        types.SimpleNamespace(status="Running"), types.SimpleNamespace(status="Succeeded"),
    ]
    _install_studio_runtime(monkeypatch, client)

    class Thread:
        def __init__(self, target, **_kwargs):
            self.target = target
            self.calls = 0

        def start(self):
            pass

        def is_alive(self):
            self.calls += 1
            if self.calls == 2:
                self.target()
            return self.calls <= 2

    monkeypatch.setattr(threading, "Thread", Thread)
    calls = iter([_result("api Running"), _result(json.dumps({"items": [
        {"spec": {"selector": {"namespaces": ["other"]}}, "status": {"experiment": {"records": ["other/pod"]}}},
        {"spec": {"selector": {"namespaces": ["app"]}}, "metadata": {"creationTimestamp": "2"}, "status": {"experiment": {"records": ["app/api"]}}},
    ]}))])
    probes = 0

    def fault_status(*_args, **kwargs):
        nonlocal probes
        probes += 1
        if probes == 4:
            raise RuntimeError("transient probe failure")
        if probes > 4:
            kwargs["_seen_killed"].add("api")
            return {"message": "pod terminating", "severity": "CHAOS"}
        return {}

    with patch.object(executor, "_kubectl", side_effect=lambda *_args, **_kwargs: next(calls)), patch.object(
        executor, "verify_fault_active", side_effect=fault_status
    ):
        executor._run_studio_experiment(
            "exp", "{}", "urn", "sub", "rg", "aks",
            {"experiment_id": "aks-pod-kill", "duration": 11, "namespace": "app", "aks_context": "ctx", "_experiment_pre_created": True},
            ui=_UI(),
        )


def test_studio_poll_timeout_reports_running_experiment(monkeypatch):
    client = MagicMock()
    client.experiments.list_all_executions.side_effect = [
        [types.SimpleNamespace(name="run")]
    ] + [[]] * 120
    client.experiments.get_execution.return_value = types.SimpleNamespace(status="Running")
    _install_studio_runtime(monkeypatch, client)

    class Thread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

        def is_alive(self):
            return False

    monkeypatch.setattr(threading, "Thread", Thread)
    ui = _UI()
    with patch.object(executor, "_kubectl", return_value=_result("")), patch.object(
        executor, "verify_fault_active", return_value={}
    ):
        executor._run_studio_experiment(
            "exp", "{}", "urn", "sub", "rg", "aks",
            {"experiment_id": "aks-pod-kill", "duration": 1, "namespace": "app", "_experiment_pre_created": True},
            ui=ui,
        )
    assert "Experiment completed (status poll timed out)" in ui.steps


def test_node_notready_and_zone_postchecks_cover_recovery_edge_reporting(monkeypatch):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    snapshot = {
        "nodes_before": [],
        "unhealthy_before": [("old", "app", "Pending")],
        "deployments_before": [("api", "app", 1, 1)],
        "pod_count_before": 1,
    }
    with patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(
        executor, "_node_is_ready", return_value=True
    ), patch.object(executor, "_node_is_schedulable", return_value=True), patch.object(
        executor, "_get_node_conditions", return_value={
            "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False"
        }
    ), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(
        executor, "_get_unhealthy_pods", return_value=[]
    ), patch.object(executor, "_get_node_names", return_value=set()), patch.object(executor.console, "print"):
        executor._postchecks_node_notready("node", "sub", "rg", "pool", "1", snapshot)

    targets = [
        {"node": "zone-a", "vmss_name": "pool", "instance_id": "1"},
        {"node": "zone-b", "vmss_name": "pool", "instance_id": "2"},
    ]
    zone_snapshot = {"nodes_notready_seen": [], "nodes_before": [], "deployments_before": [], "unhealthy_before": []}
    power = {"zone-a": 0, "zone-b": 0}
    ready = {"zone-a": 0, "zone-b": 0}

    def vm_state(_sub, _rg, _pool, instance):
        node = "zone-a" if instance == "1" else "zone-b"
        power[node] += 1
        return "stopped" if node == "zone-a" and power[node] == 1 else "running"

    def conditions(node):
        ready[node] += 1
        return {"Ready": "False" if node == "zone-a" and ready[node] == 1 else "True"}

    with patch.object(executor, "_get_vm_power_state", side_effect=vm_state), patch.object(
        executor, "_get_node_conditions", side_effect=conditions
    ), patch.object(executor, "_pending_pods_exist", return_value=[]), patch.object(
        executor, "_get_deployment_readiness", return_value=[]
    ), patch.object(executor, "_get_unhealthy_pods", return_value=[("bad", "app", "Pending")]), patch.object(
        executor, "_get_node_names", return_value=set()
    ), patch.object(executor.console, "print"):
        executor._postchecks_zone_failure(targets, "sub", "rg", zone_snapshot)

    assert power == {"zone-a": 2, "zone-b": 1}
    assert ready == {"zone-a": 2, "zone-b": 1}
