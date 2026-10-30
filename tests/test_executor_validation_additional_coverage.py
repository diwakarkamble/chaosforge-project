"""Additional branch coverage for AKS execution and offline validation."""

import json
import sys
import types
from contextlib import nullcontext
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from chaosforge.application.validation.legacy_experiment_validator import (
    ExperimentValidator as LegacyExperimentValidator,
)
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


@pytest.fixture
def ui(monkeypatch):
    instance = _UI()
    monkeypatch.setattr(executor, "PhaseUI", lambda _experiment: instance)
    return instance


def _prepare_setup(monkeypatch, tmp_path, *, steady_state=None):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_kubectl", lambda *_args, **_kwargs: _result())
    monkeypatch.setattr(
        executor,
        "run_parallel_steady_state",
        steady_state or (lambda *_args, **_kwargs: None),
    )
    return state_path, session


def test_legacy_validator_reports_required_unknown_and_all_type_failures():
    validator = LegacyExperimentValidator()
    metadata = {
        "inputs": [
            {"name": "count", "required": True, "type": "integer", "min": 2, "max": 5},
            {"name": "ratio", "required": True, "type": "float", "min": 0.5, "max": 1.5},
            {"name": "enabled", "type": "boolean"},
            "ignored",
            {},
        ]
    }

    result = validator.validate(
        metadata,
        {"count": True, "ratio": "bad", "enabled": "yes", "extra": 1},
    )

    assert result["valid"] is False
    assert result["warnings"] == ["Variable 'extra' is not defined in experiment metadata."]
    assert "Variable 'count' must be an integer. Received: True." in result["errors"]
    assert "Variable 'ratio' must be a float. Received: 'bad'." in result["errors"]
    assert "Variable 'enabled' must be a boolean. Received: 'yes'." in result["errors"]


def test_legacy_validator_covers_ranges_blanks_limits_and_boolean_forms():
    validator = LegacyExperimentValidator()
    metadata = {
        "inputs": [
            {"name": "low_int", "type": "integer", "min": "2", "max": "invalid"},
            {"name": "high_int", "type": "integer", "min": "invalid", "max": "5"},
            {"name": "low_float", "type": "float", "min": "1.5", "max": "invalid"},
            {"name": "high_float", "type": "float", "min": "invalid", "max": "3.5"},
            {"name": "required", "required": True},
            {"name": "empty", "type": "integer"},
            {"name": "missing", "type": "float"},
            {"name": "bool_true", "type": "boolean"},
            {"name": "bool_false", "type": "boolean"},
        ]
    }

    result = validator.validate(
        metadata,
        {
            "low_int": 1,
            "high_int": 6,
            "low_float": 1.0,
            "high_float": 4.0,
            "required": " ",
            "empty": "",
            "bool_true": True,
            "bool_false": " FALSE ",
        },
    )

    assert result["valid"] is False
    assert len(result["errors"]) == 5
    assert any("greater than or equal to 2" in error for error in result["errors"])
    assert any("less than or equal to 5" in error for error in result["errors"])
    assert any("greater than or equal to 1.5" in error for error in result["errors"])
    assert any("less than or equal to 3.5" in error for error in result["errors"])
    assert validator._parse_integer_limit(object()) is None
    assert validator._parse_float_limit(object()) is None
    assert validator._is_boolean(1) is False


def test_legacy_validator_rejects_invalid_inputs_and_non_boolean_numeric_values():
    validator = LegacyExperimentValidator()
    invalid = validator.validate({"inputs": {}}, {})
    assert invalid == {
        "valid": False,
        "errors": ["Experiment metadata contains an invalid inputs definition."],
        "warnings": [],
    }

    integer_errors = []
    float_errors = []
    assert validator._parse_integer("count", object(), integer_errors) is None
    assert validator._parse_float("ratio", False, float_errors) is None
    assert "integer" in integer_errors[0]
    assert "float" in float_errors[0]


def test_reopen_session_delegates_to_persisted_log_directory():
    with patch.object(executor.ValidationSession, "reopen", return_value="session") as reopen:
        assert executor._reopen_session("aks-pod-kill", {"_log_dir": "/tmp/logs"}) == "session"
    reopen.assert_called_once_with("aks-pod-kill", "/tmp/logs")


def test_setup_node_drain_uses_node_checks_and_direct_engine_summary(
    monkeypatch, tmp_path, ui
):
    def fail_steady(*_args, **_kwargs):
        raise RuntimeError("cluster unstable")

    state_path, session = _prepare_setup(
        monkeypatch, tmp_path, steady_state=fail_steady
    )
    monkeypatch.setattr(
        executor,
        "_prechecks_node_drain",
        lambda *_args, **_kwargs: (False, {"pod_count_before": 4}),
    )

    executor.setup_studio(
        "aks-node-drain", "ctx", "", "", target_node="node-a", duration="9"
    )

    state = json.loads(state_path.read_text())
    assert state["_node_precheck_ok"] is False
    assert state["_node_precheck_snapshot"] == {"pod_count_before": 4}
    assert "Node pre-checks failed for node-a" in state["_precheck_failures"]
    assert any("kubectl drain" in step for step in ui.steps)
    session.log_event.assert_any_call("pre-check", "Node pre-checks FAILED for node-a")


def test_setup_workload_records_steady_state_failure(monkeypatch, tmp_path, ui):
    def fail_steady(*_args, **_kwargs):
        raise RuntimeError("cluster unstable")

    state_path, session = _prepare_setup(monkeypatch, tmp_path, steady_state=fail_steady)
    monkeypatch.setattr(
        executor,
        "validate_and_resolve_selector",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(executor, "_setup_studio_target", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_build_spec", lambda *_args, **_kwargs: ({}, "{}", "PodChaos"))
    monkeypatch.setattr(executor, "_safe_name", lambda *_args: "experiment")
    monkeypatch.setattr(executor, "_precreate_studio_experiment", lambda *_args, **_kwargs: None)

    executor.setup_studio("aks-pod-kill", "ctx", "ns", "dep", label_key="app", label_val="dep")

    state = json.loads(state_path.read_text())
    assert state["_precheck_failures"] == "cluster unstable"
    session.log_event.assert_any_call(
        "pre-check", "Pre-checks FAILED — operator override will be prompted: cluster unstable"
    )


def test_setup_multi_node_vmss_resolves_prechecks_and_registers_each_target(
    monkeypatch, tmp_path, ui
):
    state_path, _session = _prepare_setup(monkeypatch, tmp_path)
    discovery_module = __import__(
        "chaosforge.providers.azure.components.aks.discovery", fromlist=["AzureAKSDiscovery"]
    )
    lookup = MagicMock(side_effect=[("pool-a", "1"), ("pool-b", "2")])
    monkeypatch.setattr(
        discovery_module,
        "AzureAKSDiscovery",
        lambda: SimpleNamespace(get_vmss_instance_for_node=lookup),
    )
    monkeypatch.setattr(executor, "_get_node_resource_group", lambda *_: "node-rg")
    monkeypatch.setattr(
        executor,
        "_prechecks_zone_failure",
        lambda *_args, **_kwargs: (True, {"total_evictable": 7}),
    )
    register = MagicMock()
    monkeypatch.setattr(executor, "_setup_vmss_target", register)

    executor.setup_studio(
        "aks-node-zone-failure", "ctx", "", "", target_node="node-a,node-b"
    )

    state = json.loads(state_path.read_text())
    assert state["vmss_targets"] == [
        {"node": "node-a", "vmss_name": "pool-a", "instance_id": "1"},
        {"node": "node-b", "vmss_name": "pool-b", "instance_id": "2"},
    ]
    assert state["_node_precheck_snapshot"] == {"total_evictable": 7}
    assert register.call_args_list == [
        call("sub", "node-rg", "pool-a"),
        call("sub", "node-rg", "pool-b"),
    ]


def test_setup_selector_soft_failure_is_persisted(monkeypatch, tmp_path, ui):
    state_path, session = _prepare_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        executor,
        "validate_and_resolve_selector",
        lambda *_args, **_kwargs: {"ok": False, "warning": "selector collision"},
    )

    executor.setup_studio(
        "aks-pod-kill",
        "ctx",
        "app",
        "api",
        label_key="app",
        label_val="api",
        dry_run="true",
    )

    state = json.loads(state_path.read_text())
    assert "Selector-scope validation failed: selector collision" in state["_precheck_failures"]
    session.log_event.assert_any_call(
        "pre-check", "Selector-scope validation FAILED: selector collision"
    )


def test_setup_selector_hard_block_aborts_before_registration(monkeypatch, tmp_path, ui):
    _state_path, session = _prepare_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        executor,
        "validate_and_resolve_selector",
        lambda *_args, **_kwargs: {
            "ok": False,
            "hard_block": True,
            "warning": "selector crosses workloads",
        },
    )
    register = MagicMock()
    monkeypatch.setattr(executor, "_setup_studio_target", register)

    with pytest.raises(RuntimeError, match="selector crosses workloads"):
        executor.setup_studio(
            "aks-pod-kill",
            "ctx",
            "app",
            "api",
            label_key="app",
            label_val="api",
        )

    register.assert_not_called()
    session.log_event.assert_any_call(
        "pre-check", "Selector-scope validation FAILED: selector crosses workloads"
    )


@pytest.mark.parametrize(
    ("state", "expected_runner"),
    [
        ({"vmss_targets": [{"node": "node-a"}]}, "_run_zone_failure"),
        ({"vmss_name": "pool", "instance_id": "1"}, "_run_vmss_experiment"),
    ],
)
def test_run_vmss_experiment_routes_zone_and_single_node(state, expected_runner, ui):
    state.update(
        {
            "_setup_complete": True,
            "dry_run": False,
            "subscription_id": "sub",
            "resource_group": "rg",
            "chaos_rg": "chaos-rg",
            "aks_name": "aks",
            "target_node": "node-a",
            "node_rg": "node-rg",
        }
    )
    session = MagicMock()
    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(
        executor, "_build_spec", return_value=({"parameters": {}}, "{}", "VmssShutdown")
    ), patch.object(
        executor, "_safe_name", return_value="vmss-exp"
    ), patch.object(
        executor, "_save_state_field"
    ), patch.object(
        executor, expected_runner
    ) as runner:
        executor.run_experiment("aks-node-notready", "ctx", "", "")

    runner.assert_called_once()
    assert any("Targeting" in step for step in ui.steps)


def test_run_experiment_prompts_override_and_logs_direct_fallback(ui):
    state = {
        "_setup_complete": True,
        "_precheck_failures": "readiness",
        "dry_run": False,
    }
    session = MagicMock()
    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_prompt_precheck_override"
    ) as prompt, patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(
        executor, "_build_spec", return_value=({"kind": "Custom"}, "{}", "Custom")
    ), patch.object(
        executor, "_apply_direct"
    ) as apply_direct:
        executor.run_experiment("custom", "ctx", "app", "api")

    prompt.assert_called_once_with("custom", "readiness")
    apply_direct.assert_called_once()
    session.log_event.assert_any_call("experiment", "Starting fault: custom")
    session.log_event.assert_any_call("experiment", "Direct Chaos Mesh: kind=Custom")


def test_cleanup_without_session_uses_temporary_validation_and_surfaces_failure(
    monkeypatch, tmp_path, ui
):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    state = {"dry_run": False, "_state_path": str(state_path)}
    temporary = MagicMock()
    temporary.run_checks.return_value = {
        "Replica Recovery": {"passed": False},
        "Pod Events (last 5m)": {"passed": False},
    }
    validation_factory = MagicMock(return_value=temporary)
    monkeypatch.setattr(executor, "ValidationSession", validation_factory)

    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=None
    ), patch.object(
        executor, "_kubectl", return_value=_result()
    ), patch.object(
        executor, "build_post_experiment_checks", return_value={"Replica Recovery": object()}
    ), patch.object(executor, "_ui_warning") as warning:
        with pytest.raises(RuntimeError, match="Replica Recovery"):
            executor.cleanup_experiment("aks-pod-kill", "ctx", "app", "api")

    validation_factory.assert_called_once_with("aks-pod-kill-post")
    temporary.start.assert_called_once()
    temporary.stop.assert_called_once()
    warning.assert_called_once()


def test_cleanup_taint_and_zone_routes_log_and_postcheck(monkeypatch, tmp_path, ui):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    taint_state = {
        "dry_run": False,
        "_state_path": str(state_path),
        "target_node": "node-a",
    }
    with patch.object(executor, "_load_state", return_value=taint_state), patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(executor, "_kubectl", return_value=_result()) as kubectl, patch.object(
        executor, "_postchecks_node_taint"
    ) as post, patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-node-taint", "ctx", "", "")
    assert kubectl.call_args_list[0].args == (
        "taint", "nodes", "node-a", "chaos=test:NoExecute-"
    )
    post.assert_called_once()

    state_path.write_text("{}")
    zone_state = {
        "dry_run": False,
        "_state_path": str(state_path),
        "subscription_id": "sub",
        "node_rg": "node-rg",
        "vmss_targets": [{"node": "node-a", "vmss_name": "pool", "instance_id": "1"}],
        "_zone_snapshot": {"nodes_before": ["node-a"]},
    }
    with patch.object(executor, "_load_state", return_value=zone_state), patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(executor, "_postchecks_zone_failure") as post, patch.object(
        executor.console, "print"
    ):
        executor.cleanup_experiment("aks-node-zone-failure", "ctx", "", "")
    post.assert_called_once()


@pytest.mark.parametrize("failure", [executor.subprocess.TimeoutExpired(["kubectl"], 30), OSError("gone")])
def test_cleanup_mesh_crd_delete_errors_are_logged_and_nonfatal(
    failure, tmp_path, ui
):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    session.run_checks.return_value = {}
    state = {"dry_run": False, "_state_path": str(state_path)}

    with patch.object(executor, "_load_state", return_value=state), patch.object(
        executor, "_reopen_session", return_value=session
    ), patch.object(executor, "_kubectl", side_effect=failure), patch.object(
        executor, "build_post_experiment_checks", return_value={}
    ), patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-io-errors", "ctx", "app", "api")

    messages = [call.args[1] for call in session.log_event.call_args_list if len(call.args) > 1]
    assert any("iochaos delete" in message for message in messages)
    assert not state_path.exists()


def test_node_prechecks_capture_adverse_drain_and_zone_conditions(ui):
    unhealthy = [(f"bad-{index}", "app", "Pending") for index in range(6)]
    with patch.object(executor, "_node_is_ready", return_value=False), patch.object(
        executor, "_node_is_schedulable", return_value=False
    ), patch.object(executor, "_node_pod_count", return_value=3), patch.object(
        executor, "_check_pdbs", return_value=["strict-pdb"]
    ), patch.object(executor, "_get_unhealthy_pods", return_value=unhealthy), patch.object(
        executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]
    ), patch.object(executor, "_kubectl", return_value=_result("node-a")):
        ok, snapshot = executor._prechecks_node_drain(
            "node-a", ui=ui, session=MagicMock(), cluster="aks"
        )
    assert ok is False
    assert snapshot["pod_count_before"] == 3
    assert len(snapshot["unhealthy_before"]) == 6

    targets = [{"node": "node-a", "vmss_name": "pool", "instance_id": "1"}]
    with patch.object(
        executor, "_get_node_conditions", return_value={"Ready": "False"}
    ), patch.object(executor, "_get_vm_power_state", return_value="running"):
        ok, snapshot = executor._prechecks_zone_failure(
            targets, "sub", "node-rg", ui=ui, session=MagicMock()
        )
    assert ok is False
    assert snapshot == {}


def test_stress_precheck_hard_failures_and_rich_baseline(ui):
    session = MagicMock()
    with patch.object(
        executor, "_get_node_conditions", return_value={"Ready": "False"}
    ):
        assert executor._prechecks_node_stress(
            "node-a", "cpu", ui=ui, session=session
        ) == (False, {})

    conditions = {
        "Ready": "True",
        "DiskPressure": "True",
        "MemoryPressure": "True",
        "PIDPressure": "True",
    }
    top = {"cpu_pct": 20, "cpu_cores": "200m", "mem_pct": 30, "mem_bytes": "1Gi"}
    workload = {
        "total_pods": 2,
        "ready_pods": 1,
        "running_pods": 1,
        "not_ready_pods": 1,
        "restart_total": 4,
    }
    canary = {"namespace": "app", "pod": "api"}
    probe = {"summary": "dns ok", "dns_status": "ok", "dns_elapsed_ms": 12}
    with patch.object(executor, "_get_node_conditions", return_value=conditions), patch.object(
        executor, "_kubectl", side_effect=[_result("Running"), _result()]
    ), patch.object(executor, "_get_node_top", return_value=top), patch.object(
        executor,
        "_get_unhealthy_pods",
        return_value=[(f"bad-{i}", "app", "Pending") for i in range(6)],
    ), patch.object(
        executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]
    ), patch.object(executor, "_get_pod_restart_counts", return_value={("api", "app"): 4}), patch.object(
        executor, "_node_pod_count", return_value=2
    ), patch.object(executor, "_get_node_stress_workload_status", return_value=workload), patch.object(
        executor, "_resolve_node_stress_canary", return_value=canary
    ), patch.object(executor, "_probe_node_stress_canary", return_value=probe):
        ok, snapshot = executor._prechecks_node_stress(
            "node-a", "memory", ui=ui, session=session, cluster="aks"
        )
    assert ok is True
    assert snapshot["baseline_disk_pressure"] is True
    assert snapshot["canary_baseline"] == probe
    assert snapshot["min_ready_pods_during"] == 1


def test_query_and_stress_deployment_helpers_cover_empty_and_failure_paths(
    monkeypatch, tmp_path
):
    with patch.object(executor, "_kubectl_json", return_value=None):
        assert executor._node_pod_count("node") == 0
        assert executor._check_pdbs("app") == []
        assert executor._pending_pods_exist() == []
        assert executor._get_unhealthy_pods("app") == []
        assert executor._get_deployment_readiness("app") == []
        assert executor._get_node_conditions("node") == {}

    path = tmp_path / "stress.json"

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
    with patch.object(
        executor,
        "_kubectl",
        side_effect=[_result(), _result(), _result("Failed")],
    ):
        with pytest.raises(RuntimeError, match="phase=Failed"):
            executor._deploy_stress_pod("stress", {"kind": "Pod"})


def test_crashloop_rejects_empty_selection_and_failed_apply(monkeypatch, tmp_path, ui):
    with patch.object(executor, "_kubectl", return_value=_result("")):
        with pytest.raises(RuntimeError, match="No running pods"):
            executor._run_crashloop(
                {"namespace": "app", "label_key": "app", "label_val": "api"}, ui=ui
            )

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
    monkeypatch.setattr(executor.time, "time", MagicMock(side_effect=[0, 0]))
    with patch.object(
        executor,
        "_kubectl",
        side_effect=[_result("api-1"), _result(), _result(returncode=1, stderr="denied")],
    ):
        with pytest.raises(RuntimeError, match="Failed to apply PodChaos"):
            executor._run_crashloop(
                {
                    "namespace": "app",
                    "label_key": "app",
                    "label_val": "api",
                    "duration": 1,
                    "container_name": "web",
                },
                ui=ui,
            )
    assert not path.exists()


def test_precreate_studio_experiment_uses_cluster_resource_group(monkeypatch, ui):
    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    management = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")
    identity.DefaultAzureCredential = MagicMock
    client = MagicMock()
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    sdk_modules = {
        "azure": azure,
        "azure.identity": identity,
        "azure.mgmt": management,
        "azure.mgmt.chaos": chaos,
    }
    with patch.dict(sys.modules, sdk_modules), patch.object(
        executor, "_build_studio_experiment_object", return_value="experiment"
    ) as build:
        executor._precreate_studio_experiment(
            "name",
            "{}",
            "urn",
            "sub",
            "chaos-rg",
            "aks",
            {"resource_group": "cluster-rg"},
            ui=ui,
        )

    build.assert_called_once_with(
        "{}", "urn", "sub", "cluster-rg", "aks", {"resource_group": "cluster-rg"}
    )
    client.experiments.begin_create_or_update.assert_called_once_with(
        "chaos-rg", "name", "experiment"
    )
    client.experiments.begin_create_or_update.return_value.result.assert_called_once()
