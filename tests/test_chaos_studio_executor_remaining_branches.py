"""High-value branch coverage for the AKS Chaos Studio executor."""

import json
import sys
import types
from contextlib import nullcontext
from subprocess import CompletedProcess, TimeoutExpired
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import executor


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


def _prepare_setup(monkeypatch, tmp_path, kubectl=None):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", MagicMock())
    monkeypatch.setattr(executor, "_kubectl", kubectl or MagicMock(return_value=_result()))
    monkeypatch.setattr(executor, "run_parallel_steady_state", MagicMock())
    return state_path, session


def _install_discovery(monkeypatch, lookup):
    from chaosforge.providers.azure.components.aks import discovery

    monkeypatch.setattr(
        discovery,
        "AzureAKSDiscovery",
        lambda: SimpleNamespace(get_vmss_instance_for_node=lookup),
    )


def _install_live(monkeypatch):
    live = types.ModuleType("rich.live")
    live.Live = _Live
    monkeypatch.setitem(sys.modules, "rich.live", live)
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    _Live.instances.clear()


def _azure_sdk(client):
    class Model:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    management = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")
    models = types.ModuleType("azure.mgmt.chaos.models")
    identity.DefaultAzureCredential = MagicMock
    chaos.ChaosManagementClient = MagicMock(return_value=client)
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
    return {
        "azure": azure,
        "azure.identity": identity,
        "azure.mgmt": management,
        "azure.mgmt.chaos": chaos,
        "azure.mgmt.chaos.models": models,
    }


def test_setup_http_recovers_leftover_and_handles_malformed_deployment(
    monkeypatch, tmp_path, ui
):
    kubectl = MagicMock(
        side_effect=[
            _result(),
            _result(),
            _result("not-json"),
        ]
    )
    state_path, _session = _prepare_setup(monkeypatch, tmp_path, kubectl)
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    sentinel = executor._http_chaos_sentinel("aks-http-delay", "app", "api")
    with open(sentinel, "w") as stream:
        json.dump({"_http_orig_allow_privilege_escalation": {"api": False}}, stream)
    teardown = MagicMock()
    monkeypatch.setattr(executor, "_http_chaos_teardown", teardown)

    executor.setup_studio("aks-http-delay", "ctx", "app", "api", dry_run="true")

    teardown.assert_called_once_with(
        "aks-http-delay", "ctx", "app", "api", {"api": False}, session=None
    )
    assert json.loads(state_path.read_text())["_http_orig_allow_privilege_escalation"] == {}
    assert any("No allowPrivilegeEscalation=false" in step for step in ui.steps) is False


def test_setup_http_no_patch_and_bad_leftover_are_nonfatal(monkeypatch, tmp_path, ui):
    deployment = {
        "spec": {"template": {"spec": {"containers": [{"name": "api", "securityContext": {}}]}}}
    }
    kubectl = MagicMock(side_effect=[_result(), _result(), _result(json.dumps(deployment))])
    state_path, session = _prepare_setup(monkeypatch, tmp_path, kubectl)
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    sentinel = executor._http_chaos_sentinel("aks-http-abort", "app", "api")
    with open(sentinel, "w") as stream:
        stream.write("bad-json")

    executor.setup_studio("aks-http-abort", "ctx", "app", "api", dry_run="true")

    state = json.loads(state_path.read_text())
    assert state["_http_orig_allow_privilege_escalation"] == {"api": None}
    assert any("no patch needed" in step for step in ui.steps)
    assert not any(c.args and c.args[0] == "patch" for c in kubectl.call_args_list)
    session.log_event.assert_any_call("http-chaos-setup", "Namespace labeled: app chaos-experiments=enabled")


@pytest.mark.parametrize(
    ("experiment_id", "precheck_name", "expected_kind"),
    [
        ("aks-node-taint", "_prechecks_node_taint", None),
        ("aks-node-cpu-stress", "_prechecks_node_stress", "cpu"),
        ("aks-node-memory-pressure", "_prechecks_node_stress", "memory"),
    ],
)
def test_setup_routes_remaining_node_prechecks(
    experiment_id, precheck_name, expected_kind, monkeypatch, tmp_path, ui
):
    state_path, _session = _prepare_setup(monkeypatch, tmp_path)
    precheck = MagicMock(return_value=(True, {"baseline": experiment_id}))
    monkeypatch.setattr(executor, precheck_name, precheck)

    executor.setup_studio(experiment_id, "ctx", "", "", target_node="node-a", dry_run="true")

    state = json.loads(state_path.read_text())
    assert state["_node_precheck_snapshot"] == {"baseline": experiment_id}
    if expected_kind:
        assert precheck.call_args.args[:2] == ("node-a", expected_kind)
    else:
        assert precheck.call_args.args == ("node-a",)
    assert any("DRY RUN" in step for step in ui.steps)


def test_setup_selector_map_and_single_vmss_registration(monkeypatch, tmp_path, ui):
    state_path, _session = _prepare_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        executor,
        "validate_and_resolve_selector",
        lambda *_args, **_kwargs: {
            "ok": True,
            "warning": "selector narrowed",
            "label_selectors_map": {"app": "api", "tier": "backend"},
        },
    )
    monkeypatch.setattr(executor, "_setup_studio_target", MagicMock())
    monkeypatch.setattr(executor, "_build_spec", lambda *_: ({}, "{}", "Unsupported"))

    executor.setup_studio(
        "aks-network-delay", "ctx", "app", "api", label_key="app", label_val="api"
    )
    state = json.loads(state_path.read_text())
    assert state["label_selectors_map"] == {"app": "api", "tier": "backend"}
    assert any("selector narrowed" in step for step in ui.steps)

    state_path.unlink()
    _install_discovery(monkeypatch, MagicMock(return_value=("pool", "3")))
    monkeypatch.setattr(executor, "_get_node_resource_group", lambda *_: "node-rg")
    monkeypatch.setattr(
        executor, "_prechecks_node_notready", MagicMock(return_value=(False, {"ready": False}))
    )
    register = MagicMock()
    monkeypatch.setattr(executor, "_setup_vmss_target", register)
    executor.setup_studio("aks-node-notready", "ctx", "", "", target_node="node-a")
    state = json.loads(state_path.read_text())
    register.assert_called_once_with("sub", "node-rg", "pool")
    assert "Node pre-checks failed for node-a" in state["_precheck_failures"]


@pytest.mark.parametrize(
    ("target", "lookup", "message"),
    [
        ("node-a", (None, None), "Could not find VMSS instance for node 'node-a'"),
        ("node-a,node-b", (None, None), "Could not find VMSS instances for zone nodes"),
    ],
)
def test_setup_rejects_unresolved_vmss_targets(
    target, lookup, message, monkeypatch, tmp_path, ui
):
    _prepare_setup(monkeypatch, tmp_path)
    _install_discovery(monkeypatch, MagicMock(return_value=lookup))
    monkeypatch.setattr(executor, "_get_node_resource_group", lambda *_: "node-rg")

    with pytest.raises(RuntimeError, match=message):
        executor.setup_studio("aks-node-zone-failure", "ctx", "", "", target_node=target)


def test_setup_vmss_without_target_records_empty_snapshot(monkeypatch, tmp_path, ui):
    state_path, _session = _prepare_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(executor, "_get_node_resource_group", lambda *_: "node-rg")

    executor.setup_studio("aks-node-notready", "ctx", "", "", dry_run="true")

    assert json.loads(state_path.read_text())["_node_precheck_snapshot"] == {}


@pytest.mark.parametrize(
    ("experiment_id", "runner", "log_fragment"),
    [
        ("aks-node-taint", "_run_node_taint", "Node taint complete"),
        ("aks-node-cpu-stress", "_run_node_cpu_stress", "Node CPU stress complete"),
        ("aks-node-memory-pressure", "_run_node_memory_pressure", "Node memory pressure complete"),
        ("aks-crashloop", "_run_crashloop", "Crashloop injection complete"),
    ],
)
def test_run_direct_routes_log_completion(experiment_id, runner, log_fragment, ui):
    session = MagicMock()
    state = {"_setup_complete": True, "dry_run": False, "target_node": "node-a"}
    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(executor, runner) as run:
        executor.run_experiment(experiment_id, "ctx", "app", "api")

    run.assert_called_once()
    assert any(log_fragment in c.args[1] for c in session.log_event.call_args_list)


def test_cleanup_logs_successful_network_and_exception_rollbacks(tmp_path, ui):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    session.run_checks.return_value = {}
    state = {
        "dry_run": False,
        "_state_path": str(state_path),
        "aks_context": "stored",
        "studio_experiment_name": "audit-exp",
    }
    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(executor, "_kubectl", return_value=_result()), patch.object(
        executor, "build_post_experiment_checks", return_value={}
    ), patch.object(executor, "_print_network_outcome"), patch.object(
        executor, "_print_net_impact_summary"
    ), patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-network-delay", "ctx", "app", "api")
    messages = [c.args[1] for c in session.log_event.call_args_list]
    assert "NetworkChaos resources cleanup attempted" in messages
    assert "Studio resource retained: audit-exp" in messages

    state_path.write_text("{}")
    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(executor, "_kubectl", side_effect=OSError("kubectl missing")), patch.object(
        executor, "build_post_experiment_checks", return_value={}
    ), patch.object(executor, "_print_network_outcome"), patch.object(
        executor, "_print_net_impact_summary"
    ), patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-network-delay", "ctx", "app", "api")
    assert any("networkchaos delete raised: kubectl missing" in c.args[1] for c in session.log_event.call_args_list)


def test_cleanup_cluster_plane_without_session_raises_failed_checks(
    monkeypatch, tmp_path, ui
):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    state = {"dry_run": False, "_state_path": str(state_path)}
    temporary = MagicMock()
    temporary.run_checks.return_value = {"CoreDNS Ready": {"passed": False}}
    monkeypatch.setattr(executor, "ValidationSession", MagicMock(return_value=temporary))
    extended = __import__(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended",
        fromlist=["build_cluster_plane_chaos_post_checks"],
    )
    monkeypatch.setattr(
        extended,
        "build_cluster_plane_chaos_post_checks",
        MagicMock(return_value={"CoreDNS Ready": object()}),
    )
    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=None
    ), patch.object(executor, "_kubectl", return_value=_result()), patch.object(
        executor.console, "print"
    ):
        with pytest.raises(RuntimeError, match="CoreDNS Ready"):
            executor.cleanup_experiment("aks-coredns-kill", "ctx", "", "")

    temporary.start.assert_called_once()
    temporary.stop.assert_called_once()


def test_azure_resolution_error_match_and_no_cluster_paths():
    with patch.object(executor.subprocess, "run", return_value=_result(returncode=1)):
        with pytest.raises(RuntimeError, match="Not logged in to Azure"):
            executor._resolve_azure_details("ctx", "", "", "")

    responses = [
        _result('{"id":"sub"}'),
        _result('[{"name":"aks-a","rg":"rg-a"}]'),
    ]
    with patch.object(executor.subprocess, "run", side_effect=responses):
        assert executor._resolve_azure_details("prefix-aks-a", "", "", "") == (
            "sub",
            "rg-a",
            "aks-a",
        )

    with patch.object(
        executor.subprocess,
        "run",
        side_effect=[_result('{"id":"sub"}'), _result("[]")],
    ):
        with pytest.raises(RuntimeError, match="Could not resolve the selected AKS cluster"):
            executor._resolve_azure_details("ctx", "", "", "")


def test_helm_install_preserves_runtime_values_and_reports_timeout(ui):
    session = MagicMock()
    values = {"chaosDaemon": {"runtime": "crio", "socketPath": "/run/crio.sock"}}
    with patch(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.studio_execution.ChaosMeshInstaller.release_info",
        return_value=SimpleNamespace(status=SimpleNamespace(value="ABSENT"), version=None, message="missing"),
    ), patch.object(executor, "_kubectl", return_value=_result()), patch.object(
        executor.subprocess,
        "run",
        side_effect=[_result(json.dumps(values)), _result(stdout="installed")],
    ) as run:
        executor._ensure_chaos_mesh_in_chaos_testing(
            ui=ui, session=session, aks_context="ctx", action="install"
        )
    command = run.call_args_list[1].args[0]
    assert command[command.index("--version") + 1] == "2.8.7"
    assert "chaosDaemon.runtime=crio" in command
    assert "chaosDaemon.socketPath=/run/crio.sock" in command

    with patch(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.studio_execution.ChaosMeshInstaller.release_info",
        return_value=SimpleNamespace(status=SimpleNamespace(value="ABSENT"), version=None, message="missing"),
    ), patch.object(executor, "_kubectl", return_value=_result()), patch.object(
        executor.subprocess,
        "run",
        side_effect=[_result("not-json"), TimeoutExpired(["helm"], 360)],
    ):
        with pytest.raises(RuntimeError, match="timed out after 6 minutes"):
            executor._ensure_chaos_mesh_in_chaos_testing(
                session=session, aks_context="ctx", action="install"
            )
    assert any("timed out" in c.args[1] for c in session.log_event.call_args_list)


def test_target_and_failure_helpers_cover_invalid_and_empty_records():
    pods = ["a", "b", "c"]
    assert executor._target_selection_preview(pods, "fixed", "bad") == (
        [],
        ["selector matched 3 pod(s); Chaos Mesh mode=fixed, value=bad"],
    )
    assert executor._target_selection_preview(pods, "percentage", "") == (
        [],
        ["selector matched 3 pod(s); Chaos Mesh mode=percentage"],
    )
    assert executor._extract_chaos_target_pods(
        [{"status": {"experiment": {"records": ["", {"name": "app/api"}]}}}]
    ) == ["api"]

    client = MagicMock()
    client.experiments.list_all_executions.return_value = []
    assert executor._get_experiment_failure_detail(client, "rg", "exp") is None
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.execution_details.return_value = None
    assert executor._get_experiment_failure_detail(client, "rg", "exp") is None


def test_deploy_stress_pod_timeout_is_actionable(monkeypatch, tmp_path):
    path = tmp_path / "manifest.json"

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
    with patch.object(executor, "_kubectl", side_effect=[_result(), _result()] + [_result("Pending")] * 30):
        with pytest.raises(RuntimeError, match="did not reach Running"):
            executor._deploy_stress_pod("stress", {"kind": "Pod"})
    assert not path.exists()


@pytest.mark.parametrize(
    ("raw_cpu", "top", "workload", "probe", "phase", "expected_workers"),
    [
        (
            "2500m",
            None,
            {
                "ready_pods": 1,
                "running_pods": 1,
                "not_ready_pods": 1,
                "restart_total": 2,
                "total_pods": 2,
            },
            {"summary": "dns slow"},
            "Succeeded",
            "4",
        ),
        ("", {"cpu_pct": 77, "cpu_cores": "2", "mem_pct": 40}, None, None, "Succeeded", "2"),
        ("invalid", None, None, None, "Failed", "2"),
    ],
)
def test_cpu_stress_loop_handles_metrics_canary_and_cpu_fallbacks(
    raw_cpu, top, workload, probe, phase, expected_workers, monkeypatch, tmp_path, ui
):
    _install_live(monkeypatch)
    snapshot = {"canary": {"namespace": "app", "pod": "api"}, "last_canary_summary": "cached"}
    state = {
        "experiment_id": "aks-node-cpu-stress",
        "duration": 30 if phase == "Failed" else 1,
        "_state_path": str(tmp_path / f"cpu-{raw_cpu or 'empty'}.json"),
        "_node_precheck_snapshot": snapshot,
    }
    phases = [_result(raw_cpu), _result(phase), _result(phase), _result()]
    deploy = MagicMock()
    with patch.object(executor, "_kubectl", side_effect=phases), patch.object(
        executor, "_deploy_stress_pod", deploy
    ), patch.object(executor, "_get_node_top", return_value=top), patch.object(
        executor, "_get_node_stress_workload_status", return_value=workload
    ), patch.object(executor, "_get_node_conditions", return_value={}), patch.object(
        executor, "_get_node_io_wait", return_value=3.5
    ), patch.object(executor, "_probe_node_stress_canary", return_value=probe) as canary:
        executor._run_node_cpu_stress("node-a", state, ui=ui)

    command = deploy.call_args.args[1]["spec"]["containers"][0]["command"]
    assert command[command.index("--cpu") + 1] == expected_workers
    assert canary.called
    if top:
        assert state["_stress_snapshot"]["peak_cpu_pct"] == 77
    if phase == "Failed":
        assert _Live.instances[-1].console.print.called


@pytest.mark.parametrize(
    ("baseline", "allocatable", "top", "workload", "probe", "phase", "expected_bytes"),
    [
        (
            {"mem_bytes": "100Mi"},
            "1048576Ki",
            None,
            {
                "ready_pods": 1,
                "running_pods": 1,
                "not_ready_pods": 0,
                "restart_total": 0,
                "total_pods": 1,
            },
            {"summary": "ok"},
            "Succeeded",
            "924M",
        ),
        ({"mem_bytes": "bad"}, "bad", {"mem_pct": 70, "mem_bytes": "1Gi", "cpu_pct": 20}, None, None, "Succeeded", "100%"),
        ({}, "", None, None, None, "Failed", "100%"),
    ],
)
def test_memory_stress_loop_handles_sizing_metrics_and_fallbacks(
    baseline, allocatable, top, workload, probe, phase, expected_bytes, monkeypatch, tmp_path, ui
):
    _install_live(monkeypatch)
    snapshot = {
        "baseline_top": baseline,
        "canary": {"namespace": "app", "pod": "api"},
        "last_canary_summary": "cached",
    }
    state = {
        "experiment_id": "aks-node-memory-pressure",
        "duration": 30 if phase == "Failed" else 1,
        "_state_path": str(tmp_path / f"memory-{expected_bytes.replace('%', 'pct')}.json"),
        "_node_precheck_snapshot": snapshot,
    }
    deploy = MagicMock()
    with patch.object(
        executor, "_kubectl", side_effect=[_result(allocatable), _result(phase), _result(phase), _result()]
    ), patch.object(executor, "_deploy_stress_pod", deploy), patch.object(
        executor, "_get_node_top", return_value=top
    ), patch.object(executor, "_get_node_stress_workload_status", return_value=workload), patch.object(
        executor, "_get_node_conditions", return_value={}
    ), patch.object(executor, "_get_node_io_wait", return_value=2.0), patch.object(
        executor, "_probe_node_stress_canary", return_value=probe
    ) as canary:
        executor._run_node_memory_pressure("node-a", state, ui=ui)

    container = deploy.call_args.args[1]["spec"]["containers"][0]
    command = container["command"]
    assert command[command.index("--vm-bytes") + 1] == expected_bytes
    assert canary.called
    if expected_bytes != "100%":
        assert container["resources"]["limits"] == {"memory": "1024Mi"}
    if top:
        assert state["_stress_snapshot"]["peak_mem_pct"] == 70
    if phase == "Failed":
        assert _Live.instances[-1].console.print.called


def test_vmss_runner_rejects_missing_target_before_client_creation(monkeypatch):
    client = MagicMock()
    with patch.dict(sys.modules, _azure_sdk(client)):
        with pytest.raises(RuntimeError, match="Could not find VMSS instance"):
            executor._run_vmss_experiment(
                "exp", {"parameters": {}}, "urn", "sub", "nrg", "arg", "aks", "node", {}
            )
    client.experiments.begin_create_or_update.assert_not_called()


def test_vmss_runner_logs_poll_error_transitions_and_failed_detail(
    monkeypatch, tmp_path, ui
):
    _install_live(monkeypatch)
    client = MagicMock()
    client.experiments.get.side_effect = RuntimeError("not found")
    client.experiments.list_all_executions.side_effect = [
        ValueError("temporary"),
        [SimpleNamespace(name="run")],
        [SimpleNamespace(name="run")],
        [SimpleNamespace(name="run")],
    ]
    client.experiments.get_execution.side_effect = [
        SimpleNamespace(status="Running"),
        SimpleNamespace(status="Running"),
        SimpleNamespace(status="Failed"),
    ]
    session = MagicMock()
    state = {
        "experiment_id": "aks-node-notready",
        "duration": 1,
        "vmss_name": "pool",
        "instance_id": "2",
        "_state_path": str(tmp_path / "vmss.json"),
        "_node_precheck_snapshot": {},
    }
    with patch.dict(sys.modules, _azure_sdk(client)), patch.object(
        executor, "_get_node_names", return_value={"node-a"}
    ), patch.object(executor, "_get_chaos_identity_id", return_value="identity"), patch.object(
        executor, "_node_is_ready", side_effect=[False, True]
    ), patch.object(executor, "_get_vm_power_state", return_value="deallocated"), patch.object(
        executor, "_node_pod_count", return_value=0
    ), patch.object(executor, "_get_experiment_failure_detail", return_value="capacity denied"):
        with pytest.raises(RuntimeError, match="capacity denied"):
            executor._run_vmss_experiment(
                "exp",
                {"parameters": {}},
                "urn",
                "sub",
                "nrg",
                "arg",
                "aks",
                "node-a",
                state,
                ui=ui,
                session=session,
            )

    assert any("NotReady" in c.args[1] for c in session.log_event.call_args_list)
    assert any("auto-heal" in c.args[1] for c in session.log_event.call_args_list)
    assert any("Failure detail" in step for step in ui.steps)


def test_safe_name_without_context_and_identity_success(monkeypatch):
    monkeypatch.setattr(executor.time, "time", lambda: 100)
    assert executor._safe_name("AKS/Pod Kill!") == "chaosforge-akspodkill-100"
    with patch.object(executor.subprocess, "run", return_value=_result("/identity/id\n")):
        assert executor._get_chaos_identity_id("sub", "rg") == "/identity/id"


def test_state_and_dry_run_preview_remaining_success_paths(monkeypatch, tmp_path, ui):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(executor.os, "getpid", lambda: 42)
    assert executor._load_state() == {}

    client = MagicMock()
    with patch.dict(sys.modules, _azure_sdk(client)), patch("builtins.print") as output:
        executor._delete_studio_experiment("sub", "rg", "exp")
    client.experiments.begin_delete.assert_called_once_with("rg", "exp")
    assert any("resource deleted" in str(c.args[0]) for c in output.call_args_list)

    multi = {
        "duration": 20,
        "vmss_targets": [
            {"node": "node-a", "vmss_name": "pool-a", "instance_id": "1"},
            {"node": "node-b", "vmss_name": "pool-b", "instance_id": "2"},
        ],
    }
    with patch.object(executor, "_build_spec", return_value=({}, "{}", "VmssShutdown")), patch.object(
        executor.console, "print"
    ) as console_print:
        executor._print_dry_run_preview("aks-node-zone-failure", "node-a,node-b", multi)
    assert console_print.call_count == 2

    with patch.object(executor, "_build_spec", return_value=({}, '{"mode":"one"}', "PodChaos")), patch.object(
        executor, "_safe_name", return_value="preview-name"
    ), patch("builtins.print") as output:
        executor._print_dry_run_preview("aks-pod-kill", "", {"duration": 12})
    rendered = "\n".join(str(c.args[0]) for c in output.call_args_list)
    assert "preview-name" in rendered
    assert 'jsonSpec   : {"mode":"one"}' in rendered


def test_build_spec_rejects_direction_and_blank_label_and_rewrites_container(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="positive"):
        executor._build_spec(
            "aks-clock-skew-forward",
            {"namespace": "app", "deployment": "api", "time_offset": "-5m"},
        )

    spec_path = tmp_path / "blank.json"
    spec_path.write_text(
        json.dumps(
            {
                "kind": "PodChaos",
                "selector": {"labelSelectors": {" ": "api"}},
                "containerNames": ["<container-name>", "sidecar"],
            }
        )
    )
    monkeypatch.setitem(executor.EXPERIMENT_SPECS, "aks-blank-test", "blank.json")
    monkeypatch.setattr(executor, "SPEC_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="Label keys must be non-empty"):
        executor._build_spec("aks-blank-test", {"container_name": "web"})

    spec_path.write_text(
        json.dumps({"kind": "PodChaos", "containerNames": ["<container-name>", "sidecar"]})
    )
    spec, _, _ = executor._build_spec("aks-blank-test", {"container_name": "web"})
    assert spec["containerNames"] == ["web", "sidecar"]


def test_studio_target_provider_timeout_continues_and_completes(ui):
    session = MagicMock()
    with patch.object(
        executor.subprocess, "run", side_effect=TimeoutExpired(["az"], 60)
    ), patch.object(executor, "_az_rest_put") as put, patch.object(
        executor, "_ensure_chaos_mesh_in_chaos_testing"
    ) as install:
        executor._setup_studio_target("sub", "rg", "aks", ui=ui, session=session)

    assert put.call_count == 8
    install.assert_called_once_with(
        ui=ui, session=session, aks_context="",
        action="", expected_installed_version=None,
    )
    assert any("timed out" in c.args[1] for c in session.log_event.call_args_list)
    assert any("capabilities registered" in step for step in ui.steps)


def test_node_drain_failure_and_taint_apply_failure_are_actionable(
    monkeypatch, tmp_path, ui
):
    _install_live(monkeypatch)
    drain_state = {
        "experiment_id": "aks-node-drain",
        "duration": 1,
        "_state_path": str(tmp_path / "drain.json"),
        "_node_precheck_snapshot": {},
    }
    with patch.object(executor, "_get_node_names", return_value={"node-a"}), patch.object(
        executor, "_kubectl", return_value=_result(returncode=1, stderr="PDB blocked")
    ):
        with pytest.raises(RuntimeError, match="PDB blocked"):
            executor._run_node_drain("node-a", drain_state, ui=ui)

    taint_state = {
        "experiment_id": "aks-node-taint",
        "duration": 1,
        "_state_path": str(tmp_path / "taint.json"),
        "_node_precheck_snapshot": {},
    }
    with patch.object(executor, "_get_node_names", return_value={"node-a"}), patch.object(
        executor, "_kubectl", return_value=_result(returncode=1, stderr="forbidden")
    ):
        with pytest.raises(RuntimeError, match="forbidden"):
            executor._run_node_taint("node-a", taint_state, ui=ui)


def test_postcheck_drain_reports_resolved_failures_and_new_nodes(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    state = {
        "nodes_before": ["node-a"],
        "unhealthy_before": [("old-bad", "app", "Pending")],
        "deployments_before": [("api", "app", 2, 2)],
        "pod_count_before": 2,
        "drain_start_time": 1,
        "aks_name": "aks",
    }
    with patch.object(executor, "_node_is_ready", return_value=True), patch.object(
        executor, "_node_is_schedulable", return_value=True
    ), patch.object(
        executor,
        "_get_node_conditions",
        return_value={"MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False"},
    ), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 2, 2)]), patch.object(
        executor, "_pending_pods_exist", return_value=[]
    ), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(
        executor, "_get_node_names", return_value={"node-a", "node-new"}
    ), patch.object(executor.console, "print") as output:
        executor._postchecks_node_drain("node-a", state, ui=ui, session=MagicMock())

    rendered = "\n".join(str(c.args[0]) for c in output.call_args_list)
    assert "pre-existing failure(s) resolved" in rendered
    assert "node-new" in rendered


def test_stress_canary_selection_probe_and_postcheck_adverse_paths(monkeypatch, ui):
    pods = {
        "items": [
            {
                "metadata": {"name": f"api-{index}", "namespace": "app"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
                "spec": {"containers": [{"name": "web"}]},
            }
            for index in range(12)
        ]
    }
    probes = [None] * 4 + [{"dns_status": "failed"}]
    with patch.object(executor, "_kubectl_json", return_value=pods), patch.object(
        executor, "_probe_node_stress_canary", side_effect=probes
    ):
        assert executor._resolve_node_stress_canary("node-a")["pod"] == "api-4"

    canary = {"namespace": "app", "pod": "api"}
    times = iter([0, 0.01, 1, 1.01, 2, 2.01, 3, 3.01, 4, 10])
    with patch.object(executor.time, "time", lambda: next(times)), patch.object(
        executor,
        "_kubectl",
        side_effect=[
            _result(returncode=1, stderr="getent: not found"),
            _result(returncode=1, stderr="NXDOMAIN"),
            _result(returncode=1, stderr="getent: not found"),
            _result(returncode=1, stderr="nslookup: not found"),
            TimeoutExpired(["kubectl"], 6),
        ],
    ):
        assert executor._probe_node_stress_canary(canary)["dns_status"] == "failed"
        assert executor._probe_node_stress_canary(canary)["dns_status"] == "unavailable"
        assert executor._probe_node_stress_canary(canary)["dns_status"] == "failed"

    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    snapshot = {
        "baseline_top": {"cpu_pct": 10},
        "peak_cpu_pct": 90,
        "baseline_workload": {"ready_pods": 2, "total_pods": 2},
        "min_ready_pods_during": 1,
        "max_not_ready_pods_during": 1,
        "max_restart_delta_during": 2,
        "max_iowait_pct_during": 25,
        "baseline_iowait_pct": 1,
        "disk_pressure_fired": True,
        "baseline_disk_pressure": True,
        "canary": canary,
        "canary_dns_unavailable": True,
        "restarts_before": [],
        "deployments_before": [("api", "app", 2, 2)],
        "unhealthy_before": [],
    }
    with patch.object(executor, "_get_node_top", return_value=None), patch.object(
        executor, "_get_node_conditions", return_value={"Ready": "False"}
    ), patch.object(executor, "_get_pod_restart_counts", return_value={("api", "app"): 2}), patch.object(
        executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]
    ), patch.object(
        executor,
        "_get_unhealthy_pods",
        return_value=[(f"bad-{i}", "app", "Pending") for i in range(7)],
    ), patch.object(executor, "_kubectl", side_effect=OSError("offline")), patch.object(
        executor.console, "print"
    ) as output:
        executor._postchecks_node_stress("node-a", "cpu", snapshot, ui=ui)
    rendered = "\n".join(str(c.args[0]) for c in output.call_args_list)
    assert "metrics unavailable" in rendered
    assert "and 2 more" in rendered
    assert "NOT Ready" in rendered


def test_crashloop_logs_restart_detection(monkeypatch, tmp_path, ui):
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
    times = iter([0, 0, 0, 1])
    monkeypatch.setattr(executor.time, "time", lambda: next(times))
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)

    def kubectl(*args, **_kwargs):
        if args[:2] == ("get", "pods") and "--field-selector=status.phase=Running" in args:
            return _result("api-1")
        if args[:2] == ("get", "pods"):
            return _result("api-1 1/1 Running 3 1m")
        return _result()

    event = MagicMock(return_value={"severity": "WARNING", "message": "restarted"})
    module = __import__(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.event_log",
        fromlist=["crashloop_restart_detected"],
    )
    monkeypatch.setattr(module, "crashloop_restart_detected", event)
    with patch.object(executor, "_kubectl", side_effect=kubectl):
        executor._run_crashloop(
            {
                "namespace": "app",
                "label_key": "app",
                "label_val": "api",
                "label_selectors_map": {"app": "api", "tier": "web"},
                "duration": 1,
            },
            ui=ui,
        )
    event.assert_called_once_with("api-1", 3)


def test_zone_pre_and_postchecks_report_failures_capacity_and_recovery(monkeypatch, ui):
    targets = [
        {"node": "zone-a", "vmss_name": "pool", "instance_id": "1"},
        {"node": "zone-b", "vmss_name": "pool", "instance_id": "2"},
    ]
    session = MagicMock()
    with patch.object(
        executor, "_get_node_conditions", side_effect=[{"Ready": "False"}, {"Ready": "True"}]
    ), patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(
        executor.console, "print"
    ):
        assert executor._prechecks_zone_failure(
            targets, "sub", "nrg", ui=ui, session=session
        ) == (False, {})
    session.log_event.assert_any_call("pre-check", "Zone failure aborted — nodes already NotReady")

    with patch.object(executor, "_get_node_conditions", return_value={"Ready": "True"}), patch.object(
        executor, "_get_vm_power_state", return_value="running"
    ), patch.object(executor, "_get_node_names", return_value={"zone-a", "zone-b", "survivor"}), patch.object(
        executor, "_node_pod_count", side_effect=lambda node: 2 if node.startswith("zone") else 1
    ), patch.object(executor, "_kubectl", return_value=_result("pv-a eastus-1")), patch.object(
        executor, "_get_unhealthy_pods", return_value=[("bad", "app", "Pending")]
    ), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(
        executor.console, "print"
    ) as output:
        ok, snapshot = executor._prechecks_zone_failure(
            targets, "sub", "nrg", ui=ui, session=session, cluster="aks"
        )
    assert ok is True and snapshot["total_evictable"] == 4
    assert any("zone-pinned" in str(c.args[0]) for c in output.call_args_list)

    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    pending_json = {
        "items": [
            {"metadata": {"name": "daemon", "namespace": "kube", "ownerReferences": [{"kind": "DaemonSet"}]}},
            {"metadata": {"name": "pending", "namespace": "app"}},
        ]
    }
    snapshot.update(
        {
            "nodes_notready_seen": ["zone-a"],
            "deployments_before": [("api", "app", 2, 2)],
            "unhealthy_before": [],
        }
    )
    with patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(
        executor, "_get_node_conditions", return_value={"Ready": "True"}
    ), patch.object(executor, "_pending_pods_exist", return_value=["pending"]), patch.object(
        executor, "_kubectl_json", return_value=pending_json
    ), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]), patch.object(
        executor, "_get_unhealthy_pods", return_value=[("bad", "app", "CrashLoopBackOff")]
    ), patch.object(executor, "_get_node_names", return_value={"zone-a", "zone-b", "new-node"}), patch.object(
        executor.console, "print"
    ) as output:
        executor._postchecks_zone_failure(targets, "sub", "nrg", snapshot, ui=ui, session=session)
    rendered = "\n".join(str(c.args[0]) for c in output.call_args_list)
    assert "app/pending" in rendered
    assert "capacity gap" in rendered
    assert "new-node" in rendered


def test_zone_runner_rejects_precheck_and_surfaces_failed_execution(
    monkeypatch, tmp_path, ui
):
    targets = [{"node": "zone-a", "vmss_name": "pool", "instance_id": "1"}]
    state = {
        "experiment_id": "aks-node-zone-failure",
        "duration": 1,
        "_state_path": str(tmp_path / "zone.json"),
        "_node_precheck_snapshot": {},
        "_node_precheck_ok": False,
    }
    with patch.dict(sys.modules, _azure_sdk(MagicMock())):
        with pytest.raises(RuntimeError, match="Pre-experiment checks failed"):
            executor._run_zone_failure(
                "exp", {"parameters": {}}, "urn", "sub", "nrg", "arg", "aks", targets, state
            )

    _install_live(monkeypatch)
    client = MagicMock()
    client.experiments.get.side_effect = RuntimeError("not found")
    client.experiments.list_all_executions.side_effect = [
        ValueError("temporary"),
        [SimpleNamespace(name="run")],
    ]
    client.experiments.get_execution.return_value = SimpleNamespace(status="Failed")
    state["_node_precheck_ok"] = True
    session = MagicMock()
    with patch.dict(sys.modules, _azure_sdk(client)), patch.object(
        executor, "_get_chaos_identity_id", return_value="identity"
    ), patch.object(executor, "_get_node_conditions", return_value={"Ready": "False"}), patch.object(
        executor, "_kubectl_json", return_value={"items": []}
    ), patch.object(executor, "_get_experiment_failure_detail", return_value="denied"):
        with pytest.raises(RuntimeError, match="denied"):
            executor._run_zone_failure(
                "exp",
                {"parameters": {}},
                "urn",
                "sub",
                "nrg",
                "arg",
                "aks",
                targets,
                state,
                ui=ui,
                session=session,
            )
    assert any("Failure detail" in step for step in ui.steps)


def test_direct_apply_failure_removes_manifest(monkeypatch, tmp_path, ui):
    path = tmp_path / "direct.json"

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
    with patch.object(executor, "_kubectl", return_value=_result(returncode=1, stderr="denied")):
        with pytest.raises(executor.subprocess.CalledProcessError) as raised:
            executor._apply_direct({}, "Custom", "aks-custom", {"duration": 1}, ui=ui)
    assert raised.value.stderr == "denied"
    assert not path.exists()


def test_direct_apply_success_reports_duration(monkeypatch, tmp_path, ui):
    path = tmp_path / "direct-success.json"

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
    with patch.object(executor, "_kubectl", return_value=_result()), patch.object(
        executor, "_live_wait"
    ) as wait:
        executor._apply_direct({}, "Custom", "aks-custom", {"duration": 7}, ui=ui)
    assert "Chaos Mesh resource applied (7s)" in ui.steps
    wait.assert_called_once()


def test_http_teardown_malformed_deployment_still_removes_label(monkeypatch, tmp_path):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    session = MagicMock()
    with patch.object(
        executor, "_kubectl", side_effect=[_result("not-json"), _result()]
    ) as kubectl:
        executor._http_chaos_teardown(
            "aks-http-delay", "ctx", "app", "api", {"api": False}, session
        )
    assert kubectl.call_args_list[-1].args == (
        "label",
        "namespace",
        "app",
        "chaos-experiments-",
    )
    session.log_event.assert_called_once_with(
        "rollback", "Namespace label removed: app chaos-experiments-"
    )


def test_network_summary_and_operator_prompt_remaining_branches(monkeypatch):
    fake_console = MagicMock()
    console_module = types.ModuleType("chaosforge.interfaces.cli.interactive.ui.console")
    console_module.console = fake_console
    with patch.dict(
        sys.modules,
        {"chaosforge.interfaces.cli.interactive.ui.console": console_module},
    ):
        executor._print_net_impact_summary(
            "aks-network-delay",
            {"endpoints_ready": None, "endpoints_total": None},
            {
                "endpoints_ready": 2,
                "endpoints_total": 2,
                "probe_failures": 1,
            },
            20,
            True,
            [],
            False,
        )
        executor._print_net_impact_summary(
            "aks-network-delay",
            {"endpoints_ready": 2, "endpoints_total": 2},
            {
                "endpoints_ready": 2,
                "endpoints_total": 2,
                "probe_failures": 1,
            },
            20,
            True,
            ["api-1"],
            None,
        )
        executor._print_net_impact_summary(
            "aks-network-delay",
            {"rtt_ms": None},
            {"rtt_ms": 10},
            20,
            True,
            ["api-1"],
            True,
        )
        executor._print_net_impact_summary(
            "aks-network-delay",
            {"rtt_ms": 10},
            {"rtt_ms": 10},
            20,
            True,
            ["api-1"],
            True,
        )
    assert fake_console.print.called
    assert "terminate/disrupt" in executor._destructive_warning("aks-crashloop")

    prompt = MagicMock(return_value="n")
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.prompts.prompt", prompt)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.panels.title", MagicMock())
    with patch.object(executor.console, "print"):
        with pytest.raises(RuntimeError, match="override was declined"):
            executor._prompt_precheck_override("aks-pod-kill", "• replicas low\nplain detail")


@pytest.mark.parametrize(
    ("experiment_id", "target", "mode"),
    [
        ("aks-node-taint", "node-a", "fixed"),
        ("aks-node-notready", "node-a", "all"),
    ],
)
def test_confirmation_preview_renders_node_engine_and_optional_rows(
    experiment_id, target, mode, monkeypatch
):
    prompt = MagicMock(return_value="y")
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.prompts.prompt", prompt)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.panels.title", MagicMock())
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"name": "Node Fault", "kind": "VmssShutdown"}),
    )
    fake_console = MagicMock()
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.console.console", fake_console
    )

    executor._confirm_destructive_action(
        experiment_id,
        "sub",
        "rg",
        "aks",
        "eastus",
        "app",
        "api",
        30,
        target_node=target,
        chaos_mode=mode,
        chaos_value="2",
        dry_run=True,
        fault_severity="high",
    )

    prompt.assert_called_once_with("Preview Node Fault? (Y/N)")
    assert fake_console.print.called


def test_precreate_reports_success_to_ui(ui):
    client = MagicMock()
    with patch.dict(sys.modules, _azure_sdk(client)), patch.object(
        executor, "_build_studio_experiment_object", return_value="experiment"
    ):
        executor._precreate_studio_experiment(
            "exp", "{}", "urn", "sub", "chaos-rg", "aks", {}, ui=ui
        )
    assert "Studio experiment ARM resource created: exp" in ui.steps


def test_run_non_precreated_studio_route_reports_creation(ui):
    state = {
        "_setup_complete": True,
        "dry_run": False,
        "subscription_id": "sub",
        "resource_group": "rg",
        "chaos_rg": "chaos-rg",
        "aks_name": "aks",
    }
    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=None
    ), patch.object(
        executor, "_build_spec", return_value=({}, "{}", "PodChaos")
    ), patch.object(executor, "_safe_name", return_value="new-exp"), patch.object(
        executor, "_save_state_field"
    ), patch.object(executor, "_run_studio_experiment") as run:
        executor.run_experiment("aks-pod-kill", "ctx", "app", "api")

    assert "Creating Studio experiment: new-exp" in ui.steps
    run.assert_called_once()


def test_studio_runner_propagates_background_start_failure(monkeypatch, ui):
    _install_live(monkeypatch)
    client = MagicMock()
    client.experiments.begin_start.return_value.result.side_effect = RuntimeError("start denied")
    state = {
        "experiment_id": "aks-pod-kill",
        "duration": 1,
        "namespace": "app",
        "deployment": "api",
        "aks_context": "ctx",
        "_experiment_pre_created": True,
    }
    with patch.dict(sys.modules, _azure_sdk(client)), patch.object(
        executor, "_kubectl", return_value=_result("api Running")
    ):
        with pytest.raises(RuntimeError, match="begin_start failed.*start denied"):
            executor._run_studio_experiment(
                "exp", "{}", "urn", "sub", "rg", "aks", state, ui=ui
            )


def test_vmss_runner_reports_status_poll_timeout(monkeypatch, tmp_path, ui):
    _install_live(monkeypatch)
    client = MagicMock()
    client.experiments.get.side_effect = RuntimeError("not found")
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.return_value = SimpleNamespace(status="Running")
    state = {
        "experiment_id": "aks-node-notready",
        "duration": 1,
        "vmss_name": "pool",
        "instance_id": "2",
        "_state_path": str(tmp_path / "vmss-timeout.json"),
        "_node_precheck_snapshot": {},
    }
    with patch.dict(sys.modules, _azure_sdk(client)), patch.object(
        executor, "_get_node_names", return_value={"node-a"}
    ), patch.object(executor, "_get_chaos_identity_id", return_value="identity"), patch.object(
        executor, "_node_is_ready", return_value=True
    ), patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(
        executor, "_node_pod_count", return_value=1
    ), patch.object(executor.console, "print") as output:
        executor._run_vmss_experiment(
            "exp",
            {"parameters": {}},
            "urn",
            "sub",
            "nrg",
            "arg",
            "aks",
            "node-a",
            state,
            ui=ui,
        )
    assert any("status poll timed out" in step for step in ui.steps)
    assert any("Node was Ready" in str(c.args[0]) for c in output.call_args_list)


def test_node_notready_postcheck_defaults_state_and_reports_incomplete(
    monkeypatch, ui
):
    monkeypatch.setattr(executor.time, "sleep", lambda _seconds: None)
    with patch.object(executor, "_get_vm_power_state", return_value="deallocated"), patch.object(
        executor, "_node_is_ready", return_value=False
    ), patch.object(executor.console, "print") as output:
        executor._postchecks_node_notready(
            "node-a", "sub", "nrg", "pool", "1", state=None, ui=ui
        )
    rendered = "\n".join(str(c.args[0]) for c in output.call_args_list)
    assert "VM did not return" in rendered
    assert "Recovery incomplete" in rendered
