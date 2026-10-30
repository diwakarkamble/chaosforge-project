"""Mocked lifecycle and client-wrapper coverage for the Chaos Studio executor."""

import json
import subprocess
import sys
import types
from contextlib import nullcontext
from subprocess import CompletedProcess, TimeoutExpired
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshReleaseInfo,
    HelmReleaseStatus,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio import executor


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class _UI:
    def phase(self, _name):
        return nullcontext()

    def step(self, *_args, **_kwargs):
        pass

    def status(self, *_args, **_kwargs):
        pass


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setattr(executor, "PhaseUI", lambda _experiment: _UI())
    return _UI()


def test_http_teardown_restores_only_originally_restricted_containers_and_removes_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    sentinel = executor._http_chaos_sentinel("aks-http-delay", "app", "api")
    open(sentinel, "w").close()
    deployment = {"spec": {"template": {"spec": {"containers": [
        {"name": "api", "securityContext": {}},
        {"name": "sidecar", "securityContext": {"allowPrivilegeEscalation": True}},
    ]}}}}
    session = MagicMock()
    with patch.object(executor, "_kubectl", side_effect=[_result(json.dumps(deployment)), _result(), _result(), _result(), _result()]) as kubectl:
        executor._http_chaos_teardown("aks-http-delay", "ctx", "app", "api", {"api": None, "sidecar": True}, session)

    patch_command = kubectl.call_args_list[1].args
    assert patch_command[:3] == ("patch", "deployment", "api")
    assert '"value": false' in patch_command[6]
    assert not __import__("os").path.exists(sentinel)
    session.log_event.assert_called()


def test_http_teardown_still_removes_namespace_label_when_deployment_read_fails():
    with patch.object(executor, "_kubectl", side_effect=[_result(returncode=1), _result()]) as kubectl:
        executor._http_chaos_teardown("aks-http-delay", "ctx", "app", "api", {})
    assert kubectl.call_args_list[-1].args == ("label", "namespace", "app", "chaos-experiments-")


def test_setup_studio_dry_run_persists_complete_state_without_external_registration(tmp_path, monkeypatch, ui):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_kubectl", lambda *_args, **_kwargs: _result())
    monkeypatch.setattr(executor, "run_parallel_steady_state", lambda *_args, **_kwargs: None)

    executor.setup_studio("aks-pod-kill", "ctx", "app", "api", duration="12", dry_run="yes")

    state = json.loads(state_path.read_text())
    assert state["_setup_complete"] is True
    assert state["dry_run"] is True
    assert state["chaos_rg"] == "chaos-rg"


def test_setup_studio_registers_target_precreates_spec_and_saves_selector_resolution(tmp_path, monkeypatch, ui):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_kubectl", lambda *_args, **_kwargs: _result())
    monkeypatch.setattr(executor, "run_parallel_steady_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "validate_and_resolve_selector", lambda *_args, **_kwargs: {"ok": True, "warning": "pinned", "exact_pod_name": "api-1", "label_selectors_map": {"app": "api", "tier": "web"}})
    target = MagicMock()
    precreate = MagicMock()
    monkeypatch.setattr(executor, "_setup_studio_target", target)
    monkeypatch.setattr(executor, "_build_spec", lambda *_: ({"kind": "ignored"}, "{\"spec\":true}", "PodChaos"))
    monkeypatch.setattr(executor, "_safe_name", lambda *_: "experiment-name")
    monkeypatch.setattr(executor, "_precreate_studio_experiment", precreate)

    executor.setup_studio("aks-pod-kill", "ctx", "app", "api", label_key="app", label_val="api", target_mode="pod")

    state = json.loads(state_path.read_text())
    target.assert_called_once()
    precreate.assert_called_once()
    assert state["exact_pod_name"] == "api-1"
    assert state["label_selectors_map"] == {"app": "api", "tier": "web"}
    assert state["_experiment_pre_created"] is True


def test_setup_http_chaos_snapshots_patches_and_records_recovery_sentinel(tmp_path, monkeypatch, ui):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    deployment = {"spec": {"template": {"spec": {"containers": [
        {"name": "api", "securityContext": {"allowPrivilegeEscalation": False}},
        {"name": "metrics", "securityContext": {"allowPrivilegeEscalation": True}},
    ]}}}}
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "run_parallel_steady_state", lambda *_args, **_kwargs: None)
    with patch.object(executor, "_kubectl", side_effect=[
        _result(),  # config use-context
        _result(),  # namespace label
        _result(json.dumps(deployment)),
        _result(),  # deployment patch
        _result(),  # rollout restart
        _result(),  # rollout status
    ]) as kubectl:
        executor.setup_studio("aks-http-delay", "ctx", "app", "api", dry_run="true")

    state = json.loads(state_path.read_text())
    sentinel = executor._http_chaos_sentinel("aks-http-delay", "app", "api")
    assert state["_http_orig_allow_privilege_escalation"] == {"api": False, "metrics": True}
    assert json.loads(open(sentinel).read())["_http_orig_allow_privilege_escalation"] == {
        "api": False, "metrics": True,
    }
    patch_command = kubectl.call_args_list[3].args
    assert patch_command[:3] == ("patch", "deployment", "api")
    assert '"op": "remove"' in patch_command[6]


def test_setup_studio_vmss_dry_run_resolves_single_node_and_persists_snapshot(tmp_path, monkeypatch, ui):
    state_path = tmp_path / "state.json"
    session = MagicMock(log_dir=str(tmp_path / "logs"))
    monkeypatch.setattr(executor, "ValidationSession", lambda _id: session)
    monkeypatch.setattr(executor, "_state_file", lambda _id: str(state_path))
    monkeypatch.setattr(executor, "_resolve_azure_details", lambda *_: ("sub", "rg", "aks"))
    monkeypatch.setattr(executor, "_get_or_create_chaos_rg", lambda *_: "chaos-rg")
    monkeypatch.setattr(executor, "_confirm_destructive_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_kubectl", lambda *_args, **_kwargs: _result())
    monkeypatch.setattr(executor, "run_parallel_steady_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(executor, "_get_node_resource_group", lambda *_: "node-rg")
    monkeypatch.setattr(executor, "_prechecks_node_notready", lambda *_args, **_kwargs: (True, {"ready": True}))
    from chaosforge.providers.azure.components.aks import discovery
    monkeypatch.setattr(discovery, "AzureAKSDiscovery", lambda: SimpleNamespace(
        get_vmss_instance_for_node=lambda *_: ("agentpool", "2"),
    ))

    executor.setup_studio(
        "aks-node-notready", "ctx", "", "", target_node="node-a", dry_run="true",
    )

    state = json.loads(state_path.read_text())
    assert state["node_rg"] == "node-rg"
    assert state["vmss_name"] == "agentpool"
    assert state["instance_id"] == "2"
    assert state["_node_precheck_snapshot"] == {"ready": True}


def test_run_experiment_rejects_missing_or_incomplete_setup():
    with patch.object(executor, "_load_state", return_value={}):
        with pytest.raises(RuntimeError, match="setup_studio did not complete"):
            executor.run_experiment("aks-pod-kill", "ctx", "ns", "dep")


def test_run_experiment_dry_run_uses_preview_only(ui):
    state = {"_setup_complete": True, "dry_run": True, "target_node": "node-a"}
    with patch.object(executor, "_load_state", return_value=state), patch.object(executor, "_reopen_session", return_value=None), patch.object(executor, "_print_dry_run_preview") as preview:
        executor.run_experiment("aks-node-drain", "ctx", "ns", "dep")
    preview.assert_called_once_with("aks-node-drain", "node-a", state)


@pytest.mark.parametrize("experiment_id, runner", [
    ("aks-node-drain", "_run_node_drain"),
    ("aks-node-taint", "_run_node_taint"),
    ("aks-node-cpu-stress", "_run_node_cpu_stress"),
    ("aks-node-memory-pressure", "_run_node_memory_pressure"),
    ("aks-crashloop", "_run_crashloop"),
])
def test_run_experiment_routes_direct_experiments(experiment_id, runner, ui):
    state = {"_setup_complete": True, "target_node": "node-a", "dry_run": False}
    with patch.object(executor, "_load_state", return_value=state), patch.object(executor, "_reopen_session", return_value=None), patch.object(executor, runner) as run:
        executor.run_experiment(experiment_id, "ctx", "ns", "dep")
    assert run.called


def test_run_experiment_routes_unknown_capability_to_direct_apply(ui):
    state = {"_setup_complete": True, "dry_run": False}
    with patch.object(executor, "_load_state", return_value=state), patch.object(executor, "_reopen_session", return_value=None), patch.object(executor, "_build_spec", return_value=({"x": 1}, "{}", "Unknown")), patch.object(executor, "_apply_direct") as apply:
        executor.run_experiment("aks-pod-kill", "ctx", "ns", "dep")
    apply.assert_called_once()


def test_run_experiment_uses_precreated_studio_values(ui):
    state = {"_setup_complete": True, "dry_run": False, "subscription_id": "sub", "chaos_rg": "chaos", "aks_name": "aks", "studio_experiment_name": "saved", "_json_spec": "saved-json", "_capability_urn": "saved-urn", "_experiment_pre_created": True}
    with patch.object(executor, "_load_state", return_value=state), patch.object(executor, "_reopen_session", return_value=None), patch.object(executor, "_build_spec", return_value=({}, "new-json", "PodChaos")), patch.object(executor, "_save_state_field"), patch.object(executor, "_run_studio_experiment") as run:
        executor.run_experiment("aks-pod-kill", "ctx", "ns", "dep")
    assert run.call_args.args[:6] == ("saved", "saved-json", "saved-urn", "sub", "chaos", "aks")


def test_cleanup_dry_run_stops_session_and_removes_state(tmp_path, ui):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    state = {"dry_run": True, "_state_path": str(state_path)}
    with patch.object(executor, "_load_state", return_value=state), patch.object(executor, "_reopen_session", return_value=session):
        executor.cleanup_experiment("aks-pod-kill", "ctx", "ns", "dep")
    assert not state_path.exists()
    session.stop.assert_called_once()


def test_cleanup_skips_post_checks_when_setup_never_completed(ui):
    with patch.object(executor, "_load_state", return_value={}), patch.object(
        executor, "build_post_experiment_checks"
    ) as post_checks, patch.object(executor, "_kubectl") as kubectl:
        executor.cleanup_experiment("aks-pod-kill", "ctx", "ns", "dep")

    post_checks.assert_not_called()
    kubectl.assert_not_called()


def test_rollback_health_skips_when_setup_never_completed(monkeypatch):
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import safety

    monkeypatch.setattr(executor, "_load_state", lambda *_: {})
    verify = MagicMock()
    monkeypatch.setattr(safety._safety_basic, "verify_rollback_health", verify)

    assert safety.verify_rollback_health("ctx", "ns", "pod", experiment_id="aks-pod-kill") is True
    verify.assert_not_called()


def test_cleanup_network_and_mesh_delete_failures_are_nonfatal(tmp_path, ui):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    state = {"dry_run": False, "_state_path": str(state_path), "aks_context": "stored"}
    with patch.object(executor, "_load_state", return_value=state), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "_kubectl", side_effect=[TimeoutExpired(["kubectl"], 30), RuntimeError("gone")]), patch.object(executor, "build_post_experiment_checks", return_value={}), patch.object(executor, "os") as os_mock:
        os_mock.path.exists.return_value = False
        executor.cleanup_experiment("aks-network-delay", "ctx", "ns", "dep")
    assert session.log_event.called


def test_cleanup_http_restores_then_runs_post_checks_and_removes_state(tmp_path, ui):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    session.run_checks.return_value = {"healthy": {"passed": True}}
    state = {"dry_run": False, "_state_path": str(state_path), "_http_orig_allow_privilege_escalation": {}}
    with patch.object(executor, "_load_state", return_value=state), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "_http_chaos_teardown") as teardown, patch.object(executor, "_kubectl", return_value=_result()), patch.object(executor, "build_post_experiment_checks", return_value={}), patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-http-delay", "ctx", "ns", "dep")
    teardown.assert_called_once()
    assert not state_path.exists()


def test_cleanup_node_routes_postchecks_and_generic_cleanup_uses_steady_state(tmp_path, ui):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    drain_state = {"dry_run": False, "_state_path": str(state_path), "target_node": "node-a"}
    with patch.object(executor, "_load_state", return_value=drain_state), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "_kubectl", return_value=_result()), patch.object(executor, "_postchecks_node_drain") as post, patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-node-drain", "ctx", "ns", "dep")
    post.assert_called_once()
    state_path.write_text("{}")
    generic_state = {"dry_run": False, "_state_path": str(state_path)}
    with patch.object(executor, "_load_state", return_value=generic_state), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "run_parallel_steady_state") as steady, patch.object(executor.console, "print"):
        executor.cleanup_experiment("unclassified", "ctx", "ns", "dep")
    steady.assert_called_once()


def test_node_query_helpers_filter_daemonsets_and_report_health():
    pods = {"items": [
        {"metadata": {"name": "daemon", "namespace": "kube", "ownerReferences": [{"kind": "DaemonSet"}]}, "status": {"phase": "Pending"}},
        {"metadata": {"name": "bad", "namespace": "app"}, "status": {"phase": "Running", "containerStatuses": [{"state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}},
        {"metadata": {"name": "pending", "namespace": "app"}, "status": {"phase": "Pending"}},
    ]}
    with patch.object(executor, "_kubectl_json", return_value=pods):
        assert executor._node_pod_count("node") == 2
        assert executor._pending_pods_exist() == ["bad", "pending"]
        assert executor._get_unhealthy_pods() == [("bad", "app", "CrashLoopBackOff"), ("pending", "app", "Pending")]


def test_node_and_deployment_query_helpers_parse_kubectl_responses():
    node = {"status": {"conditions": [{"type": "Ready", "status": "True"}]}, "spec": {"taints": [{"key": "chaos", "value": "test", "effect": "NoExecute"}]}}
    deployments = {"items": [{"metadata": {"name": "api", "namespace": "app"}, "spec": {"replicas": 3}, "status": {"readyReplicas": 2}}]}
    with patch.object(executor, "_kubectl", side_effect=[_result("True"), _result("false"), _result("node-a node-b")]), patch.object(executor, "_kubectl_json", side_effect=[deployments, node]):
        assert executor._node_is_ready("node-a") is True
        assert executor._node_is_schedulable("node-a") is True
        assert executor._get_node_names() == {"node-a", "node-b"}
        assert executor._get_deployment_readiness() == [("api", "app", 2, 3)]
        assert executor._node_taint_confirmed("node-a") is True


def test_stress_helpers_parse_metrics_probe_and_record_impact():
    with patch.object(executor, "_kubectl", return_value=_result("node-a 250m 25% 512Mi 50%")):
        assert executor._get_node_top("node-a") == {"cpu_cores": "250m", "cpu_pct": 25, "mem_bytes": "512Mi", "mem_pct": 50}
    canary = {"namespace": "app", "pod": "api"}
    with patch.object(executor, "_kubectl", return_value=_result("10.0.0.1")), patch.object(executor.time, "time", side_effect=[1, 1.01]):
        probe = executor._probe_node_stress_canary(canary)
    snapshot = {"baseline_workload": {"restart_total": 1}}
    executor._record_node_stress_impact(snapshot, {"ready_pods": 1, "running_pods": 2, "not_ready_pods": 1, "restart_total": 3}, probe, {"MemoryPressure": "True"}, 4.5)
    assert probe["dns_status"] == "ok"
    assert snapshot["max_restart_delta_during"] == 2
    assert snapshot["mem_pressure_fired"] is True
    assert snapshot["max_iowait_pct_during"] == 4.5


def test_deploy_stress_pod_handles_apply_failure_and_success(monkeypatch, tmp_path):
    created = tmp_path / "manifest.json"
    class Temp:
        name = str(created)
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def write(self, value): created.write_text(value); return len(value)
    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", lambda **_: Temp())
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    with patch.object(executor, "_kubectl", side_effect=[_result(), _result(), _result("Running")]):
        executor._deploy_stress_pod("stress", {"kind": "Pod"})
    assert not created.exists()
    with patch.object(executor, "_kubectl", side_effect=[_result(), _result(returncode=1, stderr="denied")]):
        with pytest.raises(RuntimeError, match="Failed to deploy"):
            executor._deploy_stress_pod("stress", {"kind": "Pod"})


def test_resolve_target_pod_and_crashloop_name_cover_direct_and_selector_paths():
    assert executor._crashloop_podchaos_name("namespace", "application") == "chaosforge-crashloop-namespace-application"
    assert executor._resolve_target_pod("ns", "app", "api", "api-abcdef1234-abcde") == "api-abcdef1234-abcde"
    with patch.object(executor, "_kubectl", return_value=_result("api-1")) as kubectl:
        assert executor._resolve_target_pod("ns", "app", "api", "deployment", {"app": "api", "tier": "web"}) == "api-1"
    assert "app=api,tier=web" in kubectl.call_args.args


def test_failure_detail_returns_top_level_nested_and_suppresses_client_errors():
    client = MagicMock()
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.execution_details.return_value = SimpleNamespace(properties=SimpleNamespace(failure_reason="bad request"))
    assert executor._get_experiment_failure_detail(client, "rg", "exp") == "bad request"
    error = SimpleNamespace(code="Denied", message="forbidden")
    target = SimpleNamespace(properties=SimpleNamespace(error=error))
    action = SimpleNamespace(targets=[target])
    client.experiments.execution_details.return_value = SimpleNamespace(properties=SimpleNamespace(failure_reason=None, run_information=SimpleNamespace(steps=[SimpleNamespace(branches=[SimpleNamespace(actions=[action])])])))
    assert executor._get_experiment_failure_detail(client, "rg", "exp") == "Denied: forbidden"
    client.experiments.list_all_executions.side_effect = RuntimeError("offline")
    assert executor._get_experiment_failure_detail(client, "rg", "exp", session=MagicMock()) is None


def test_studio_target_registration_collects_capability_failures_and_skips_install():
    with patch.object(executor.subprocess, "run", return_value=_result()), patch.object(executor, "_az_rest_put", side_effect=[None] + [RuntimeError("cap failed")] * 7), patch.object(executor, "_ensure_chaos_mesh_in_chaos_testing") as install:
        with pytest.raises(RuntimeError, match="cap failed"):
            executor._setup_studio_target("sub", "rg", "aks")
    install.assert_not_called()


def test_ensure_chaos_mesh_uses_current_release_and_install_failure_is_actionable():
    installer = MagicMock()
    installer.release_info.return_value = ChaosMeshReleaseInfo(
        HelmReleaseStatus.INSTALLED, "installed", "2.8.7"
    )
    with patch(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.studio_execution.ChaosMeshInstaller",
        return_value=installer,
    ):
        executor._ensure_chaos_mesh_in_chaos_testing(aks_context="ctx")
    installer.install.assert_not_called()

    installer.release_info.return_value = ChaosMeshReleaseInfo(
        HelmReleaseStatus.ABSENT, "missing"
    )
    with patch(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.studio_execution.ChaosMeshInstaller",
        return_value=installer,
    ), patch.object(executor, "_kubectl", return_value=_result(returncode=1)), patch.object(
        executor.subprocess,
        "run",
        side_effect=[_result("{}"), _result(returncode=1, stderr="helm denied")],
    ):
        with pytest.raises(RuntimeError, match="helm denied"):
            executor._ensure_chaos_mesh_in_chaos_testing(
                aks_context="ctx", action="install"
            )


def test_get_node_resource_group_identity_and_direct_apply_errors():
    with patch.object(executor.subprocess, "run", return_value=_result("MC_rg_aks")):
        assert executor._get_node_resource_group("sub", "rg", "aks") == "MC_rg_aks"
    with patch.object(executor.subprocess, "run", return_value=_result(returncode=1)):
        with pytest.raises(RuntimeError, match="Could not resolve node resource group"):
            executor._get_node_resource_group("sub", "rg", "aks")
    with patch.object(executor.subprocess, "run", return_value=_result(returncode=1)):
        assert executor._get_chaos_identity_id("sub", "rg").startswith("/subscriptions/sub")


def test_node_prechecks_cover_healthy_and_unhealthy_baselines(ui):
    common = {
        "_node_is_ready": True, "_node_is_schedulable": True, "_node_pod_count": 2,
        "_check_pdbs": [], "_get_unhealthy_pods": [],
        "_get_deployment_readiness": [("api", "app", 2, 2)],
    }
    with patch.multiple(executor, **{name: MagicMock(return_value=value) for name, value in common.items()}), patch.object(executor, "_kubectl", return_value=_result("node-a node-b")):
        ok, snapshot = executor._prechecks_node_drain("node-a", ui=ui, session=MagicMock(), cluster="aks")
        assert ok is True and snapshot["pod_count_before"] == 2
    with patch.multiple(executor, **{name: MagicMock(return_value=value) for name, value in common.items()}), patch.object(executor, "_node_has_chaos_taint", return_value=False), patch.object(executor, "_kubectl", return_value=_result("node-a node-b")):
        ok, snapshot = executor._prechecks_node_taint("node-a", ui=ui)
        assert ok is True and snapshot["deployments_before"] == [("api", "app", 2, 2)]
    with patch.object(executor, "_get_node_conditions", return_value={"Ready": "True", "DiskPressure": "False", "MemoryPressure": "False", "PIDPressure": "False"}), patch.object(executor, "_kubectl", side_effect=[_result(""), _result()]), patch.object(executor, "_get_node_top", return_value={"cpu_pct": 10, "cpu_cores": "100m", "mem_pct": 20, "mem_bytes": "1Gi"}), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_get_pod_restart_counts", return_value={}), patch.object(executor, "_node_pod_count", return_value=1), patch.object(executor, "_get_node_stress_workload_status", return_value={"total_pods": 1, "ready_pods": 1, "running_pods": 1, "not_ready_pods": 0, "restart_total": 0}), patch.object(executor, "_resolve_node_stress_canary", return_value=None):
        ok, snapshot = executor._prechecks_node_stress("node-a", "cpu", ui=ui)
    assert ok is True and snapshot["peak_cpu_pct"] == 10


def test_vmss_and_zone_prechecks_capture_baselines(ui):
    with patch.object(executor, "_node_is_ready", return_value=True), patch.object(executor, "_node_is_schedulable", return_value=True), patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(executor, "_node_pod_count", return_value=2), patch.object(executor, "_check_pdbs", return_value=[]), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_kubectl", return_value=_result("node-a node-b")):
        ok, snapshot = executor._prechecks_node_notready("node-a", "sub", "nrg", "vmss", "0", ui=ui)
    assert ok is True and snapshot["pod_count_before"] == 2
    targets = [{"node": "node-a", "vmss_name": "vmss", "instance_id": "0"}]
    with patch.object(executor, "_get_node_conditions", return_value={"Ready": "True"}), patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(executor, "_get_node_names", return_value={"node-a", "node-b"}), patch.object(executor, "_node_pod_count", return_value=1), patch.object(executor, "_kubectl", return_value=_result("")), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_deployment_readiness", return_value=[]):
        ok, snapshot = executor._prechecks_zone_failure(targets, "sub", "nrg", ui=ui)
    assert ok is True and snapshot["total_evictable"] == 1


def test_postchecks_cover_recovered_node_stress_vmss_and_zone_paths(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    healthy_conditions = {"Ready": "True", "MemoryPressure": "False", "DiskPressure": "False", "PIDPressure": "False"}
    with patch.object(executor, "_node_is_ready", return_value=True), patch.object(executor, "_node_is_schedulable", return_value=True), patch.object(executor, "_get_node_conditions", return_value=healthy_conditions), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_pending_pods_exist", return_value=[]), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_node_names", return_value={"node-a"}):
        executor._postchecks_node_drain("node-a", {"nodes_before": ["node-a"]}, ui=ui)
        executor._postchecks_node_taint("node-a", {"nodes_before": ["node-a"]}, ui=ui)
    stress_snapshot = {"baseline_top": {"cpu_pct": 10}, "peak_cpu_pct": 70, "baseline_workload": {"ready_pods": 1, "total_pods": 1}, "restarts_before": []}
    with patch.object(executor, "_get_node_top", return_value={"cpu_pct": 12, "cpu_cores": "100m", "mem_pct": 20, "mem_bytes": "1Gi"}), patch.object(executor, "_get_node_conditions", return_value=healthy_conditions), patch.object(executor, "_get_pod_restart_counts", return_value={}), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_kubectl", return_value=_result("")):
        executor._postchecks_node_stress("node-a", "cpu", stress_snapshot, ui=ui)
    with patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(executor, "_node_is_ready", return_value=True), patch.object(executor, "_node_is_schedulable", return_value=True), patch.object(executor, "_get_node_conditions", return_value=healthy_conditions), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_node_names", return_value={"node-a"}):
        executor._postchecks_node_notready("node-a", "sub", "nrg", "vmss", "0", {"nodes_before": ["node-a"]}, ui=ui)
    targets = [{"node": "node-a", "vmss_name": "vmss", "instance_id": "0"}]
    with patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(executor, "_get_node_conditions", return_value=healthy_conditions), patch.object(executor, "_pending_pods_exist", return_value=[]), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_node_names", return_value={"node-a"}):
        executor._postchecks_zone_failure(targets, "sub", "nrg", {"nodes_before": ["node-a"]}, ui=ui)


def test_apply_direct_and_cleanup_crashloop_use_temp_manifest_and_matching_resources(monkeypatch, tmp_path):
    manifest_path = tmp_path / "chaos.json"
    class Temp:
        name = str(manifest_path)
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def write(self, value): manifest_path.write_text(value); return len(value)
    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", lambda **_: Temp())
    with patch.object(executor, "_kubectl", return_value=_result()), patch.object(executor, "_live_wait") as wait:
        executor._apply_direct({"mode": "one"}, "PodChaos", "aks-custom", {"duration": 3})
    wait.assert_called_once()
    assert not manifest_path.exists()
    ctx = {"namespace": "app", "label_val": "api"}
    base = executor._crashloop_podchaos_name("app", "api")
    with patch.object(executor, "_kubectl", side_effect=[_result(f"other {base} {base}-1"), _result(), _result()]) as kubectl:
        executor._cleanup_crashloop(ctx)
    assert kubectl.call_count == 3


def test_read_chaos_pods_and_pod_metrics_helpers_cover_success_and_failure():
    status = {"items": [{"status": {"experiment": {"podRecords": {"app/api-1": {}}}}}]}
    with patch.object(executor, "_kubectl", return_value=_result(json.dumps(status))):
        assert executor._read_chaos_target_pods("podchaos", "ctx") == ["api-1"]
    workload = {"items": [{"metadata": {"name": "api", "namespace": "app"}, "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}], "containerStatuses": [{"restartCount": 2}]}}]}
    with patch.object(executor, "_kubectl_json", return_value=workload):
        assert executor._get_pod_restart_counts("node") == {("api", "app"): 2}
        assert executor._get_node_stress_workload_status("node") == {"total_pods": 1, "running_pods": 1, "ready_pods": 1, "not_ready_pods": 0, "restart_total": 2}
    assert executor._is_missing_exec_command("sh: getent: not found") is True
    assert executor._is_missing_exec_command("connection refused") is False


def test_vmss_target_registration_and_power_state_wrapper():
    with patch.object(executor, "_az_rest_put") as put, patch.object(executor.subprocess, "run", return_value=_result()):
        executor._setup_vmss_target("sub", "rg", "vmss")
    put.assert_called_once()
    with patch.object(executor.subprocess, "run", return_value=_result("VM running")):
        assert executor._get_vm_power_state("sub", "rg", "vmss", "0") == "running"
    with patch.object(executor.subprocess, "run", return_value=_result(returncode=1)):
        assert executor._get_vm_power_state("sub", "rg", "vmss", "0") == "unknown"


def test_studio_execution_polls_terminal_success_and_failure_without_live_services(monkeypatch, ui):
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    identity.DefaultAzureCredential = MagicMock
    mgmt = types.ModuleType("azure.mgmt")
    chaos = types.ModuleType("azure.mgmt.chaos")
    client = MagicMock()
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live")
    live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    with patch.dict(sys.modules, {"azure": azure, "azure.identity": identity, "azure.mgmt": mgmt, "azure.mgmt.chaos": chaos, "rich.live": live}), patch.object(executor, "_kubectl", return_value=_result("api Running")), patch.object(executor, "_save_state_field"), patch.object(executor, "verify_fault_active", return_value={"message": "active", "severity": "CHAOS"}):
        client.experiments.get_execution.return_value = SimpleNamespace(status="Succeeded")
        executor._run_studio_experiment("exp", "{}", "urn", "sub", "rg", "aks", {"experiment_id": "aks-pod-kill", "duration": 1, "_experiment_pre_created": True}, ui=ui)
        client.experiments.get_execution.return_value = SimpleNamespace(status="Failed")
        with patch.object(executor, "_get_experiment_failure_detail", return_value="denied"):
            with pytest.raises(RuntimeError, match="Reason: denied"):
                executor._run_studio_experiment("exp", "{}", "urn", "sub", "rg", "aks", {"experiment_id": "aks-pod-kill", "duration": 1, "_experiment_pre_created": True}, ui=ui)


def test_studio_execution_running_branch_probes_fault_and_captures_target(monkeypatch, ui):
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    azure, identity, mgmt, chaos = types.ModuleType("azure"), types.ModuleType("azure.identity"), types.ModuleType("azure.mgmt"), types.ModuleType("azure.mgmt.chaos")
    identity.DefaultAzureCredential = MagicMock
    client = MagicMock()
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.side_effect = [SimpleNamespace(status="Running"), SimpleNamespace(status="Succeeded")]
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live"); live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    crds = {"items": [{"spec": {"selector": {"namespaces": ["app"]}}, "metadata": {"creationTimestamp": "2026-01-01"}, "status": {"experiment": {"podRecords": {"app/api-1": {}}}}}]}
    state = {"experiment_id": "aks-pod-kill", "duration": 1, "namespace": "app", "deployment": "api", "aks_context": "ctx", "_experiment_pre_created": True}
    with patch.dict(sys.modules, {"azure": azure, "azure.identity": identity, "azure.mgmt": mgmt, "azure.mgmt.chaos": chaos, "rich.live": live}), patch.object(executor, "_kubectl", side_effect=[_result("api-1 Running"), _result(json.dumps(crds))]), patch.object(executor, "_save_state_field"), patch.object(executor, "verify_fault_active", return_value={"message": "injected", "severity": "CHAOS"}):
        executor._run_studio_experiment("exp", "{}", "urn", "sub", "rg", "aks", state, ui=ui)
    assert client.experiments.begin_start.called


def test_coredns_kill_run_resolves_kube_system_target_instead_of_none(monkeypatch, ui):
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    azure, identity, mgmt, chaos = types.ModuleType("azure"), types.ModuleType("azure.identity"), types.ModuleType("azure.mgmt"), types.ModuleType("azure.mgmt.chaos")
    identity.DefaultAzureCredential = MagicMock
    client = MagicMock()
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.return_value = SimpleNamespace(status="Succeeded")
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live"); live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    # experiment_id has no user-supplied namespace/deployment — historically
    # left namespace/deployment as None, producing "-n None" kubectl calls.
    state = {"experiment_id": "aks-coredns-kill", "duration": 1, "namespace": None, "deployment": None, "aks_context": "ctx", "_experiment_pre_created": True}
    printed = []
    with patch.dict(sys.modules, {"azure": azure, "azure.identity": identity, "azure.mgmt": mgmt, "azure.mgmt.chaos": chaos, "rich.live": live}), \
         patch.object(executor, "_kubectl", return_value=_result("coredns-1 Running")) as kubectl, \
         patch.object(executor, "_save_state_field"), \
         patch.object(executor, "verify_fault_active", return_value={"message": "active", "severity": "CHAOS"}), \
         patch("chaosforge.interfaces.cli.interactive.ui.console.console.print", side_effect=printed.append):
        executor._run_studio_experiment("exp", "{}", "urn", "sub", "rg", "aks", state, ui=ui)

    pod_list_call = kubectl.call_args_list[0].args
    assert "-n" in pod_list_call and pod_list_call[pod_list_call.index("-n") + 1] == "kube-system"
    assert "k8s-app=kube-dns" in pod_list_call
    banner = "\n".join(str(line) for line in printed)
    assert "namespace: [bold]kube-system[/bold]" in banner
    assert "target: [bold]CoreDNS[/bold]" in banner
    assert "target: [bold]None[/bold]" not in banner
    assert "namespace: [bold]None[/bold]" not in banner


def test_node_stress_execution_builds_cpu_and_memory_manifests_without_waiting(monkeypatch, tmp_path, ui):
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    live = types.ModuleType("rich.live")
    live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    state = {"experiment_id": "aks-node-cpu-stress", "duration": 1, "_state_path": str(tmp_path / "state.json"), "_node_precheck_snapshot": {"canary": None}}
    top = {"cpu_pct": 80, "cpu_cores": "800m", "mem_pct": 70, "mem_bytes": "1000Mi"}
    with patch.dict(sys.modules, {"rich.live": live}), patch.object(executor, "_kubectl", side_effect=[_result("2"), _result("Succeeded"), _result()]), patch.object(executor, "_deploy_stress_pod") as deploy, patch.object(executor, "_get_node_top", return_value=top), patch.object(executor, "_get_node_stress_workload_status", return_value=None), patch.object(executor, "_get_node_conditions", return_value={}), patch.object(executor, "_get_node_io_wait", return_value=None):
        executor._run_node_cpu_stress("node-a", state, ui=ui)
    assert "--cpu" in deploy.call_args.args[1]["spec"]["containers"][0]["command"]
    memory_state = {"experiment_id": "aks-node-memory-pressure", "duration": 1, "_state_path": str(tmp_path / "memory.json"), "_node_precheck_snapshot": {"canary": None, "baseline_top": top}}
    with patch.dict(sys.modules, {"rich.live": live}), patch.object(executor, "_kubectl", side_effect=[_result("4096Ki"), _result("Succeeded"), _result()]), patch.object(executor, "_deploy_stress_pod") as deploy, patch.object(executor, "_get_node_top", return_value=top), patch.object(executor, "_get_node_stress_workload_status", return_value=None), patch.object(executor, "_get_node_conditions", return_value={}), patch.object(executor, "_get_node_io_wait", return_value=None):
        executor._run_node_memory_pressure("node-a", memory_state, ui=ui)
    assert "--vm-bytes" in deploy.call_args.args[1]["spec"]["containers"][0]["command"]


def test_vmss_execution_paths_create_models_and_complete_with_mocked_sdk(monkeypatch, tmp_path, ui):
    class Model:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    azure, identity, mgmt, chaos, models = (types.ModuleType("azure"), types.ModuleType("azure.identity"), types.ModuleType("azure.mgmt"), types.ModuleType("azure.mgmt.chaos"), types.ModuleType("azure.mgmt.chaos.models"))
    identity.DefaultAzureCredential = MagicMock
    for name in ("Experiment", "ChaosExperimentStep", "ChaosExperimentBranch", "ContinuousAction", "KeyValuePair", "ChaosTargetListSelector", "TargetReference", "ManagedServiceIdentity"):
        setattr(models, name, Model)
    models.TargetReferenceType = SimpleNamespace(CHAOS_TARGET="target")
    models.ManagedServiceIdentityType = SimpleNamespace(USER_ASSIGNED="identity")
    client = MagicMock(); client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]; client.experiments.get_execution.return_value = SimpleNamespace(status="Succeeded")
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live"); live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    sdk = {"azure": azure, "azure.identity": identity, "azure.mgmt": mgmt, "azure.mgmt.chaos": chaos, "azure.mgmt.chaos.models": models, "rich.live": live}
    state = {"experiment_id": "aks-node-notready", "duration": 1, "_state_path": str(tmp_path / "vmss.json"), "vmss_name": "pool", "instance_id": "1", "_node_precheck_snapshot": {}}
    with patch.dict(sys.modules, sdk), patch.object(executor, "_get_node_names", return_value={"node-a"}), patch.object(executor, "_get_chaos_identity_id", return_value="id"), patch.object(executor, "_kubectl", return_value=_result()), patch.object(executor, "_node_is_ready", return_value=True), patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(executor, "_node_pod_count", return_value=1):
        executor._run_vmss_experiment("exp", {"parameters": {}}, "urn", "sub", "nrg", "arg", "aks", "node-a", state, ui=ui)
    targets = [{"node": "node-a", "vmss_name": "pool", "instance_id": "1"}, {"node": "node-b", "vmss_name": "pool", "instance_id": "2"}]
    zone_state = {"experiment_id": "aks-node-zone-failure", "duration": 1, "_state_path": str(tmp_path / "zone.json"), "_node_precheck_snapshot": {}, "_node_precheck_ok": True}
    with patch.dict(sys.modules, sdk), patch.object(executor, "_get_chaos_identity_id", return_value="id"), patch.object(executor, "_get_node_conditions", return_value={"Ready": "True"}), patch.object(executor, "_kubectl_json", return_value={"items": []}):
        executor._run_zone_failure("zone", {"parameters": {}}, "urn", "sub", "nrg", "arg", "aks", targets, zone_state, ui=ui)
    assert client.experiments.begin_create_or_update.called


@pytest.mark.parametrize("experiment_id, ctx, expected", [
    ("aks-packet-loss", {"loss_percentage": "40", "correlation": "20"}, ("loss", "40")),
    ("aks-bandwidth-limit", {"rate": "2mbps"}, ("bandwidth", "2mbps")),
    ("aks-packet-corruption", {"corrupt_percentage": "30", "correlation": "15"}, ("corrupt", "30")),
    ("aks-packet-duplication", {"duplicate_percentage": "30", "correlation": "15"}, ("duplicate", "30")),
])
def test_build_spec_applies_all_network_override_families(experiment_id, ctx, expected):
    spec, _, _ = executor._build_spec(experiment_id, {"namespace": "app", "deployment": "api", **ctx})
    assert spec[expected[0]][expected[0] if expected[0] != "bandwidth" else "rate"] == expected[1]


def test_build_time_dns_container_and_pod_pinning_variants():
    time_spec, _, _ = executor._build_spec("aks-clock-skew-backward", {"namespace": "app", "deployment": "api", "time_offset": "5m"})
    dns_spec, _, _ = executor._build_spec("aks-dns-failure", {"namespace": "app", "deployment": "api", "dns_pattern": "example.test"})
    pinned, _, _ = executor._build_spec("aks-pod-kill", {"namespace": "app", "deployment": "api", "target_mode": "pod", "exact_pod_name": "api-1"})
    assert time_spec["timeOffset"] == "-5m"
    assert dns_spec["patterns"] == ["example.test"]
    assert pinned["selector"]["fieldSelectors"] == {"metadata.name": "api-1"}


@pytest.mark.parametrize("experiment_id", [
    "aks-network-delay", "aks-packet-loss", "aks-bandwidth-limit",
    "aks-packet-corruption", "aks-packet-duplication", "aks-network-partition",
])
def test_network_outcome_and_impact_summary_render_each_fault_family(experiment_id):
    fake_console = MagicMock()
    console_module = types.ModuleType("chaosforge.interfaces.cli.interactive.ui.console")
    console_module.console = fake_console
    pre = {"rtt_ms": 10, "retrans": 1, "dsack": 1, "endpoints_ready": 3, "endpoints_total": 3, "restarts": 1, "probe_failures": 0}
    peak = {"rtt_ms": 50, "retrans": 4, "dsack": 3, "endpoints_ready": 0 if experiment_id == "aks-network-partition" else 2, "endpoints_total": 3, "restarts": 2, "probe_failures": 1}
    with patch.dict(sys.modules, {"chaosforge.interfaces.cli.interactive.ui.console": console_module}):
        executor._print_network_outcome(True, pre, peak, [])
        executor._print_net_impact_summary(experiment_id, pre, peak, 30, True, ["api-1"], True)
    assert fake_console.print.called


def test_confirmation_and_precheck_prompts_accept_and_reject_with_mocked_ui_modules(monkeypatch):
    prompt = MagicMock(return_value="y")
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.prompts.prompt", prompt)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.panels.title", MagicMock())
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"name": "Pod Kill", "kind": "PodChaos"}),
    )
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.status.warning", MagicMock())
    with patch.object(executor.console, "print"):
        executor._confirm_destructive_action("aks-pod-kill", "sub", "rg", "aks", "eastus", "app", "api", 30)
        executor._prompt_precheck_override("aks-pod-kill", "bad readiness")
        prompt.return_value = "n"
        with pytest.raises(RuntimeError, match="cancelled"):
            executor._confirm_destructive_action("aks-pod-kill", "sub", "rg", "aks", "eastus", "app", "api", 30)


def test_direct_node_drain_and_taint_execution_lifecycles_are_mocked(monkeypatch, tmp_path, ui):
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    live = types.ModuleType("rich.live"); live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    drain = {"experiment_id": "aks-node-drain", "duration": 1, "_state_path": str(tmp_path / "drain.json"), "_node_precheck_snapshot": {}}
    with patch.dict(sys.modules, {"rich.live": live}), patch.object(executor, "_get_node_names", return_value={"node-a"}), patch.object(executor, "_kubectl", return_value=_result()), patch.object(executor, "_node_pod_count", return_value=0), patch.object(executor, "_node_is_schedulable", return_value=False):
        executor._run_node_drain("node-a", drain, ui=ui)
    taint = {"experiment_id": "aks-node-taint", "duration": 1, "_state_path": str(tmp_path / "taint.json"), "_node_precheck_snapshot": {}}
    with patch.dict(sys.modules, {"rich.live": live}), patch.object(executor, "_get_node_names", return_value={"node-a"}), patch.object(executor, "_kubectl", return_value=_result()), patch.object(executor, "_node_pod_count", return_value=0), patch.object(executor, "_node_is_schedulable", return_value=True), patch.object(executor, "_node_taint_confirmed", return_value=True):
        executor._run_node_taint("node-a", taint, ui=ui)
    assert drain["pod_count_before"] == 0
    assert taint["pod_count_before"] == 0


def test_crashloop_runs_selected_pods_and_reports_restarts(monkeypatch, tmp_path, ui):
    times = iter([0, 0, 0, 2])
    monkeypatch.setattr(executor.time, "time", lambda: next(times))
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    path = tmp_path / "crash.json"
    class Temp:
        name = str(path)
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def write(self, value): path.write_text(value); return len(value)
    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", lambda **_: Temp())
    with patch.object(executor, "_kubectl", side_effect=lambda *args, **kwargs: _result("api-1\napi-2") if args[:2] == ("get", "pods") else _result()) as kubectl:
        executor._run_crashloop({"namespace": "app", "label_key": "app", "label_val": "api", "duration": 1, "chaos_mode": "all", "container_name": "web"}, ui=ui)
    assert any(call.args[0] == "apply" for call in kubectl.call_args_list)
    assert not path.exists()


@pytest.mark.parametrize("experiment_id", [
    "aks-node-drain", "aks-node-cpu-stress", "aks-crashloop",
    "aks-node-notready", "aks-coredns-kill", "aks-network-delay",
])
def test_destructive_warning_describes_each_experiment_family(experiment_id):
    warning = executor._destructive_warning(experiment_id)
    assert warning


def test_precheck_override_uses_canonical_ui_modules(monkeypatch):
    prompt = MagicMock(return_value="y")
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.prompts.prompt",
        prompt,
    )
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.panels.title",
        MagicMock(),
    )

    executor._prompt_precheck_override("aks-pod-kill", "failure")

    prompt.assert_called_once_with("Proceed despite failed pre-checks? (Y/N)")


def test_precheck_override_aborts_in_web_execution(monkeypatch):
    monkeypatch.setattr(
        "chaosforge.common.execution_mode.is_web_execution",
        lambda: True,
    )

    with pytest.raises(RuntimeError, match="Experiment aborted"):
        executor._prompt_precheck_override("aks-pod-kill", "replicas unavailable")


def test_destructive_confirmation_auto_confirms_web_execution(monkeypatch):
    monkeypatch.setattr(
        "chaosforge.common.execution_mode.is_web_execution",
        lambda: True,
    )
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"name": "Pod Kill", "kind": "PodChaos"}),
    )
    prompt = MagicMock(side_effect=AssertionError("Web confirmation must not read stdin"))
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.prompts.prompt", prompt)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.ui.panels.title", MagicMock())

    with patch.object(executor.console, "print") as print_call:
        executor._confirm_destructive_action(
            "aks-pod-kill", "sub", "rg", "aks", "eastus", "app", "api", 30
        )

    prompt.assert_not_called()
    assert any(
        call.args and "auto-confirming" in str(call.args[0])
        for call in print_call.call_args_list
    )


def test_destructive_confirmation_uses_canonical_ui_modules(monkeypatch):
    prompt = MagicMock(return_value="y")
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.prompts.prompt",
        prompt,
    )
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.ui.panels.title",
        MagicMock(),
    )
    monkeypatch.setattr(
        "chaosforge.application.metadata.get_experiment",
        MagicMock(return_value={"name": "Pod Kill", "kind": "PodChaos"}),
    )

    executor._confirm_destructive_action(
        "aks-pod-kill",
        "subscription",
        "resource-group",
        "cluster",
        "westus",
        "sample-app",
        "nginx",
        30,
    )

    prompt.assert_called_once_with("Proceed with Pod Kill? (Y/N)")


@pytest.mark.parametrize("experiment_id,state", [
    ("aks-node-drain", {"duration": 12}),
    ("aks-node-taint", {}),
    ("aks-node-cpu-stress", {"duration": 12}),
    ("aks-node-notready", {"duration": 12, "vmss_name": "pool", "instance_id": "3"}),
    ("aks-pod-kill", {"duration": 12}),
])
def test_dry_run_preview_describes_route_without_injection(experiment_id, state):
    with patch.object(executor, "_build_spec", return_value=({"mode": "one"}, "{}", "VmssShutdown")), patch.object(executor, "_safe_name", return_value="preview") as safe, patch("builtins.print") as output:
        executor._print_dry_run_preview(experiment_id, "node-a", state)
    assert output.called
    if experiment_id == "aks-pod-kill":
        safe.assert_not_called()


def test_cleanup_routes_stress_crashloop_and_mesh_crd_rollbacks(tmp_path, ui):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    stress = {"_state_path": str(state_path), "dry_run": False, "target_node": "node-a"}
    with patch.object(executor, "_load_state", return_value=stress), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "_cleanup_stress_pod") as cleanup, patch.object(executor, "_postchecks_node_stress"), patch.object(executor, "os") as os_mock, patch.object(executor.console, "print"):
        os_mock.path.exists.return_value = False
        executor.cleanup_experiment("aks-node-cpu-stress", "ctx", "ns", "dep")
    cleanup.assert_called_once_with("aks-node-cpu-stress", "node-a")

    state_path.write_text("{}")
    crash = {"_state_path": str(state_path), "dry_run": False}
    with patch.object(executor, "_load_state", return_value=crash), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "_cleanup_crashloop") as cleanup, patch.object(executor, "run_parallel_steady_state"), patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-crashloop", "ctx", "ns", "dep")
    cleanup.assert_called_once_with(crash)

    state_path.write_text("{}")
    mesh = {"_state_path": str(state_path), "dry_run": False, "studio_experiment_name": "audit"}
    with patch.object(executor, "_load_state", return_value=mesh), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "_kubectl", return_value=_result(returncode=1, stderr="busy")) as kubectl, patch.object(executor, "build_post_experiment_checks", return_value={}), patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-io-errors", "ctx", "ns", "dep")
    assert any(call.args[:2] == ("delete", "iochaos") for call in kubectl.call_args_list)


def test_cleanup_routes_vmss_postchecks_and_cluster_plane_checks(tmp_path, ui, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    session = MagicMock()
    node_state = {"_state_path": str(state_path), "dry_run": False, "target_node": "node", "subscription_id": "sub", "node_rg": "nrg", "vmss_name": "pool", "instance_id": "2"}
    with patch.object(executor, "_load_state", return_value=node_state), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor, "_postchecks_node_notready") as post, patch.object(executor.console, "print"):
        executor.cleanup_experiment("aks-node-notready", "ctx", "ns", "dep")
    post.assert_called_once()

    extended = types.ModuleType("chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended")
    extended.build_cluster_plane_chaos_post_checks = MagicMock(return_value={"healthy": object()})
    state_path.write_text("{}")
    plane_state = {"_state_path": str(state_path), "dry_run": False}
    with patch.dict(sys.modules, {extended.__name__: extended}), patch.object(executor, "_load_state", return_value=plane_state), patch.object(executor, "_reopen_session", return_value=session), patch.object(executor.console, "print"):
        session.run_checks.return_value = {"healthy": {"passed": True}}
        executor.cleanup_experiment("aks-coredns-kill", "ctx", "", "")
    extended.build_cluster_plane_chaos_post_checks.assert_called_once()


def test_prechecks_report_unhealthy_node_taint_and_notready_baselines(ui):
    unhealthy = [("bad-1", "app", "Pending")] * 6
    deployments = [("api", "app", 1, 2)]
    with patch.object(executor, "_node_is_ready", return_value=False), patch.object(executor, "_node_has_chaos_taint", return_value=True), patch.object(executor, "_node_is_schedulable", return_value=False), patch.object(executor, "_node_pod_count", return_value=2), patch.object(executor, "_check_pdbs", return_value=["pdb"]), patch.object(executor, "_get_unhealthy_pods", return_value=unhealthy), patch.object(executor, "_get_deployment_readiness", return_value=deployments), patch.object(executor, "_kubectl", return_value=_result("node")):
        ok, snapshot = executor._prechecks_node_taint("node", ui=ui, session=MagicMock(), cluster="aks")
    assert ok is False
    assert len(snapshot["unhealthy_before"]) == 6

    with patch.object(executor, "_node_is_ready", return_value=False), patch.object(executor, "_node_is_schedulable", return_value=False), patch.object(executor, "_get_vm_power_state", return_value="deallocated"), patch.object(executor, "_node_pod_count", return_value=2), patch.object(executor, "_check_pdbs", return_value=["pdb"]), patch.object(executor, "_get_unhealthy_pods", return_value=unhealthy), patch.object(executor, "_get_deployment_readiness", return_value=deployments), patch.object(executor, "_kubectl", return_value=_result("node")):
        ok, snapshot = executor._prechecks_node_notready("node", "sub", "nrg", "pool", "2", ui=ui, session=MagicMock(), cluster="aks")
    assert ok is False
    assert snapshot["deployments_before"] == deployments


def test_node_stress_precheck_covers_missing_namespace_metrics_and_canary(ui):
    with patch.object(executor, "_get_node_conditions", return_value={"Ready": "True"}), patch.object(executor, "_kubectl", side_effect=[_result("Running"), _result(returncode=1)]), patch.object(executor, "_get_node_top", return_value=None), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_get_pod_restart_counts", return_value={}), patch.object(executor, "_node_pod_count", return_value=0), patch.object(executor, "_get_node_stress_workload_status", return_value=None), patch.object(executor, "_resolve_node_stress_canary", return_value=None):
        ok, snapshot = executor._prechecks_node_stress("node", "memory", ui=ui, session=MagicMock())
    assert ok is False
    assert snapshot == {}


def test_postchecks_report_incomplete_stress_recovery_and_impact(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    snapshot = {
        "baseline_top": {"cpu_pct": 10}, "peak_cpu_pct": 90,
        "baseline_workload": {"ready_pods": 2, "total_pods": 2},
        "min_ready_pods_during": 1, "max_not_ready_pods_during": 1,
        "max_restart_delta_during": 2, "max_iowait_pct_during": 25,
        "disk_pressure_fired": True, "mem_pressure_fired": True,
        "pid_pressure_fired": True, "canary": {"namespace": "app", "pod": "api"},
        "canary_dns_failures": 2, "restarts_before": [["api", "app", 0]],
        "deployments_before": [["api", "app", 2, 2]], "unhealthy_before": [],
    }
    top = {"cpu_pct": 90, "cpu_cores": "900m", "mem_pct": 20, "mem_bytes": "1Gi"}
    with patch.object(executor, "_get_node_top", return_value=top), patch.object(executor, "_get_node_conditions", return_value={"Ready": "False", "MemoryPressure": "True", "DiskPressure": "True", "PIDPressure": "True"}), patch.object(executor, "_get_pod_restart_counts", return_value={("api", "app"): 2}), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]), patch.object(executor, "_get_unhealthy_pods", return_value=[("bad", "app", "Pending")]), patch.object(executor, "_kubectl", return_value=_result("bad")):
        executor._postchecks_node_stress("node", "cpu", snapshot, ui=ui, session=MagicMock())


def test_helper_failure_and_timeout_paths_are_actionable(monkeypatch):
    with patch("chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl", side_effect=RuntimeError("dispatcher unavailable")), patch.object(executor.subprocess, "run", return_value=_result("fallback")) as run:
        assert executor._kubectl("get", "pods").stdout == "fallback"
    run.assert_called_once()
    with patch.object(executor.subprocess, "run", side_effect=subprocess.TimeoutExpired(["az"], 30)):
        with pytest.raises(RuntimeError, match="Timed out"):
            executor._az_rest_put("https://example.test", "target", session=MagicMock())
    with patch.object(executor, "_kubectl", return_value=_result("")):
        executor._cleanup_stress_pod("aks-node-cpu-stress", "node")
        executor._cleanup_stress_pod("aks-node-cpu-stress", "")


def test_live_wait_and_deploy_failure_paths_are_mocked(monkeypatch):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    console = MagicMock()
    executor._live_wait(2, console)
    assert console.print.call_count == 3
    with patch.object(executor.tempfile, "NamedTemporaryFile", side_effect=OSError("no tmp")):
        with pytest.raises(OSError):
            executor._apply_direct({}, "PodChaos", "aks-pod-kill")


@pytest.mark.parametrize("mode,value,expected", [
    ("fixed", "2", 2), ("fixed-percent", "50", 2),
    ("random-max-percent", "50", 1), ("unexpected", "", 1),
])
def test_crashloop_selects_requested_pod_subset(mode, value, expected, monkeypatch, tmp_path, ui):
    ticks = iter([0, 0, 20, 20])
    monkeypatch.setattr(executor.time, "time", lambda: next(ticks))
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    class Temp:
        name = str(tmp_path / "crash.json")
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def write(self, value):
            (tmp_path / "crash.json").write_text(value)
            return len(value)
    monkeypatch.setattr(executor.tempfile, "NamedTemporaryFile", lambda **_: Temp())
    monkeypatch.setattr("secrets.randbelow", lambda *_: 0)
    with patch.object(executor, "_kubectl", side_effect=lambda *args, **kwargs: _result("a\nb\nc") if args[:2] == ("get", "pods") else _result()) as kubectl:
        executor._run_crashloop({"namespace": "app", "label_key": "app", "label_val": "api", "duration": 1, "chaos_mode": mode, "chaos_value": value}, ui=ui)
    applied = [call for call in kubectl.call_args_list if call.args[:2] == ("apply", "-f")]
    assert len(applied) == expected


def test_notready_postchecks_report_vm_and_node_recovery_timeout(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    state = {"nodes_before": ["node-a"], "unhealthy_before": [("old", "app", "Pending")], "deployments_before": [("api", "app", 2, 2)], "pod_count_before": 3, "notready_start_time": 1}
    with patch.object(executor, "_get_vm_power_state", return_value="deallocated"), patch.object(executor, "_node_is_ready", return_value=False), patch.object(executor, "_get_node_names", return_value={"node-a", "new-node"}), patch.object(executor.time, "time", return_value=31):
        executor._postchecks_node_notready("node-a", "sub", "nrg", "pool", "1", state, ui=ui, session=MagicMock())


def test_notready_postchecks_report_degraded_workloads_after_recovery(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    state = {"nodes_before": ["node-a"], "unhealthy_before": [("old", "app", "Pending")], "deployments_before": [("api", "app", 2, 2)], "pod_count_before": 3}
    with patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(executor, "_node_is_ready", return_value=True), patch.object(executor, "_node_is_schedulable", return_value=False), patch.object(executor, "_get_node_conditions", return_value={"MemoryPressure": "True", "DiskPressure": "False", "PIDPressure": "False"}), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]), patch.object(executor, "_get_unhealthy_pods", return_value=[("old", "app", "Pending"), ("new", "app", "CrashLoopBackOff")]), patch.object(executor, "_get_node_names", return_value={"node-a", "new-node"}):
        executor._postchecks_node_notready("node-a", "sub", "nrg", "pool", "1", state, ui=ui, session=MagicMock())


def test_zone_postchecks_report_unrecovered_nodes_pending_and_workload_damage(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    targets = [{"node": "node-a-123", "vmss_name": "pool", "instance_id": "1"}, {"node": "node-b-456", "vmss_name": "pool", "instance_id": "2"}]
    snapshot = {"nodes_notready_seen": ["node-a-123"], "deployments_before": [["api", "app", 2, 2]], "unhealthy_before": [], "nodes_before": ["node-a-123"]}
    pending_data = {"items": [{"metadata": {"name": "pending", "namespace": "app", "ownerReferences": []}}]}
    with patch.object(executor, "_get_vm_power_state", return_value="deallocated"), patch.object(executor, "_get_node_conditions", return_value={"Ready": "False"}), patch.object(executor, "_pending_pods_exist", return_value=["pending"]), patch.object(executor, "_kubectl_json", return_value=pending_data), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]), patch.object(executor, "_get_unhealthy_pods", return_value=[("bad", "app", "Pending")]), patch.object(executor, "_get_node_names", return_value={"node-a-123", "new-node"}):
        executor._postchecks_zone_failure(targets, "sub", "nrg", snapshot, ui=ui, session=MagicMock())


def test_zone_postchecks_confirm_full_recovery(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    targets = [{"node": "node-a-123", "vmss_name": "pool", "instance_id": "1"}]
    snapshot = {"nodes_notready_seen": ["node-a-123"], "deployments_before": [], "unhealthy_before": [], "nodes_before": ["node-a-123"]}
    with patch.object(executor, "_get_vm_power_state", return_value="running"), patch.object(executor, "_get_node_conditions", return_value={"Ready": "True"}), patch.object(executor, "_pending_pods_exist", return_value=[]), patch.object(executor, "_get_deployment_readiness", return_value=[]), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_node_names", return_value={"node-a-123"}):
        executor._postchecks_zone_failure(targets, "sub", "nrg", snapshot, ui=ui, session=MagicMock())


def test_drain_and_taint_postchecks_report_recovery_regressions(monkeypatch, ui):
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    drain_state = {"nodes_before": ["node"], "unhealthy_before": [("old", "app", "Pending")], "deployments_before": [("api", "app", 2, 2)], "pod_count_before": 2, "drain_start_time": 1}
    with patch.object(executor, "_node_is_ready", return_value=False), patch.object(executor, "_node_is_schedulable", return_value=False), patch.object(executor, "_get_node_conditions", return_value={}), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]), patch.object(executor, "_pending_pods_exist", return_value=["pending"]), patch.object(executor, "_get_unhealthy_pods", return_value=[("old", "app", "Pending"), ("new", "app", "CrashLoopBackOff")]), patch.object(executor, "_get_node_names", return_value={"node", "new"}), patch.object(executor.time, "time", return_value=31):
        executor._postchecks_node_drain("node", drain_state, ui=ui, session=MagicMock())

    taint_state = {"nodes_before": ["node"], "unhealthy_before": [], "deployments_before": [("api", "app", 2, 2)]}
    with patch.object(executor, "_node_is_ready", return_value=False), patch.object(executor, "_node_is_schedulable", return_value=False), patch.object(executor, "_get_node_conditions", return_value={}), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 1, 2)]), patch.object(executor, "_pending_pods_exist", return_value=["pending"]), patch.object(executor, "_get_unhealthy_pods", return_value=[("new", "app", "Pending")]), patch.object(executor, "_get_node_names", return_value={"node", "new"}):
        executor._postchecks_node_taint("node", taint_state, ui=ui, session=MagicMock())


def test_studio_network_execution_records_metrics_and_actual_targets(monkeypatch, tmp_path, ui):
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    azure, identity, mgmt, chaos = types.ModuleType("azure"), types.ModuleType("azure.identity"), types.ModuleType("azure.mgmt"), types.ModuleType("azure.mgmt.chaos")
    identity.DefaultAzureCredential = MagicMock
    client = MagicMock()
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.side_effect = [SimpleNamespace(status="Running"), SimpleNamespace(status="Succeeded")]
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live"); live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    metrics = {"severity": "CHAOS", "net_rows": [("RTT", "25ms"), ("Endpoints ready", "1/2"), ("Container restarts", "2")]}
    crds = {"items": [{"status": {"experiment": {"podRecords": {"app/api-1": {}}}}}]}
    state = {"experiment_id": "aks-network-delay", "duration": 1, "namespace": "app", "deployment": "api", "label_selectors_map": {"app": "api", "tier": "web"}, "aks_context": "ctx", "_state_path": str(tmp_path / "state.json")}
    with patch.dict(sys.modules, {"azure": azure, "azure.identity": identity, "azure.mgmt": mgmt, "azure.mgmt.chaos": chaos, "rich.live": live}), patch.object(executor, "_build_studio_experiment_object", return_value=object()), patch.object(executor, "_kubectl", side_effect=[_result("api-1 Running"), _result("{\"items\":[{\"status\":{\"containerStatuses\":[{\"restartCount\":1}]}}]}"), _result(json.dumps(crds))]), patch.object(executor, "verify_fault_active", return_value=metrics), patch.object(executor, "_save_state_field") as save:
        executor._run_studio_experiment("exp", "{}", "urn", "sub", "rg", "aks", state, ui=ui, session=MagicMock())
    assert client.experiments.begin_start.called
    assert any(call.args[1] == "_fault_confirmed" for call in save.call_args_list)


def test_vmss_execution_observes_fault_transition_and_terminal_result(monkeypatch, tmp_path, ui):
    class Model:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    azure, identity, mgmt, chaos, models = (types.ModuleType("azure"), types.ModuleType("azure.identity"), types.ModuleType("azure.mgmt"), types.ModuleType("azure.mgmt.chaos"), types.ModuleType("azure.mgmt.chaos.models"))
    identity.DefaultAzureCredential = MagicMock
    for name in ("Experiment", "ChaosExperimentStep", "ChaosExperimentBranch", "ContinuousAction", "KeyValuePair", "ChaosTargetListSelector", "TargetReference", "ManagedServiceIdentity"):
        setattr(models, name, Model)
    models.TargetReferenceType = SimpleNamespace(CHAOS_TARGET="target")
    models.ManagedServiceIdentityType = SimpleNamespace(USER_ASSIGNED="identity")
    client = MagicMock()
    client.experiments.get.return_value = SimpleNamespace(location="eastus")
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.side_effect = [SimpleNamespace(status="Running"), SimpleNamespace(status="Succeeded")]
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live"); live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    sdk = {"azure": azure, "azure.identity": identity, "azure.mgmt": mgmt, "azure.mgmt.chaos": chaos, "azure.mgmt.chaos.models": models, "rich.live": live}
    state = {"experiment_id": "aks-node-notready", "duration": 1, "_state_path": str(tmp_path / "vmss.json"), "vmss_name": "pool", "instance_id": "1", "_node_precheck_snapshot": {}}
    with patch.dict(sys.modules, sdk), patch.object(executor, "_get_node_names", return_value={"node-a"}), patch.object(executor, "_get_chaos_identity_id", return_value="id"), patch.object(executor, "_node_is_ready", side_effect=[False]), patch.object(executor, "_get_vm_power_state", return_value="stopping"), patch.object(executor, "_node_pod_count", return_value=2):
        executor._run_vmss_experiment("exp", {"parameters": {}}, "urn", "sub", "nrg", "arg", "aks", "node-a", state, ui=ui, session=MagicMock())
    assert client.experiments.begin_start.called


def test_zone_execution_observes_faulted_nodes_and_persists_snapshot(monkeypatch, tmp_path, ui):
    class Model:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class Live:
        def __init__(self, *_args, **_kwargs): self.console = MagicMock()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, *_args): pass
    azure, identity, mgmt, chaos, models = (types.ModuleType("azure"), types.ModuleType("azure.identity"), types.ModuleType("azure.mgmt"), types.ModuleType("azure.mgmt.chaos"), types.ModuleType("azure.mgmt.chaos.models"))
    identity.DefaultAzureCredential = MagicMock
    for name in ("Experiment", "ChaosExperimentStep", "ChaosExperimentBranch", "ContinuousAction", "KeyValuePair", "ChaosTargetListSelector", "TargetReference", "ManagedServiceIdentity"):
        setattr(models, name, Model)
    models.TargetReferenceType = SimpleNamespace(CHAOS_TARGET="target")
    models.ManagedServiceIdentityType = SimpleNamespace(USER_ASSIGNED="identity")
    client = MagicMock(); client.experiments.get.return_value = SimpleNamespace(location="eastus")
    client.experiments.list_all_executions.return_value = [SimpleNamespace(name="run")]
    client.experiments.get_execution.side_effect = [SimpleNamespace(status="Running"), SimpleNamespace(status="Succeeded")]
    chaos.ChaosManagementClient = MagicMock(return_value=client)
    live = types.ModuleType("rich.live"); live.Live = Live
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    sdk = {"azure": azure, "azure.identity": identity, "azure.mgmt": mgmt, "azure.mgmt.chaos": chaos, "azure.mgmt.chaos.models": models, "rich.live": live}
    targets = [{"node": "node-a", "vmss_name": "pool", "instance_id": "1"}]
    state = {"experiment_id": "aks-node-zone-failure", "duration": 1, "_state_path": str(tmp_path / "zone.json"), "_node_precheck_snapshot": {}, "_node_precheck_ok": True}
    with patch.dict(sys.modules, sdk), patch.object(executor, "_get_chaos_identity_id", return_value="id"), patch.object(executor, "_get_node_conditions", return_value={"Ready": "False"}), patch.object(executor, "_kubectl_json", return_value={"items": []}):
        executor._run_zone_failure("zone", {"parameters": {}}, "urn", "sub", "nrg", "arg", "aks", targets, state, ui=ui, session=MagicMock())
    assert state["_zone_snapshot"]["nodes_notready_seen"] == ["node-a"]


def test_node_stress_helper_fallbacks_cover_metrics_io_and_canary_selection(monkeypatch):
    with patch.object(executor, "_kubectl", return_value=_result("node cpu invalid mem invalid")):
        assert executor._get_node_top("node") is None
    assert executor._get_node_io_wait("node") is None
    with patch.object(executor, "_kubectl", return_value=_result("12.5")):
        assert executor._get_node_io_wait("node", "stress") == 12.5
    with patch.object(executor, "_kubectl", side_effect=RuntimeError("gone")):
        assert executor._get_node_io_wait("node", "stress") is None

    pods = {"items": [
        {"metadata": {"name": "daemon", "namespace": "app", "ownerReferences": [{"kind": "DaemonSet"}]}, "status": {"phase": "Running"}},
        {"metadata": {"name": "system", "namespace": "kube-system"}, "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}},
        {"metadata": {"name": "not-ready", "namespace": "app"}, "status": {"phase": "Running", "conditions": []}},
        {"metadata": {"name": "canary", "namespace": "app"}, "spec": {"containers": [{"name": "web"}]}, "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}},
    ]}
    with patch.object(executor, "_kubectl_json", return_value=pods), patch.object(executor, "_probe_node_stress_canary", return_value={"dns_status": "unavailable"}):
        assert executor._resolve_node_stress_canary("node") == {"namespace": "app", "pod": "canary", "container": "web"}
    with patch.object(executor, "_kubectl", side_effect=[_result(returncode=1, stderr="not found"), _result(returncode=1, stderr="dns timeout")]), patch.object(executor.time, "time", side_effect=[1, 1.01, 2, 2.01]):
        assert executor._probe_node_stress_canary({"namespace": "app", "pod": "canary"})["dns_status"] == "failed"


def test_node_taint_failure_and_postcheck_resolution_paths(monkeypatch, tmp_path, ui):
    state = {"experiment_id": "aks-node-taint", "duration": 1, "_state_path": str(tmp_path / "state.json"), "_node_precheck_snapshot": {}}
    with patch.object(executor, "_get_node_names", return_value={"node"}), patch.object(executor, "_kubectl", return_value=_result(returncode=1, stderr="denied")):
        with pytest.raises(RuntimeError, match="Node taint failed"):
            executor._run_node_taint("node", state, ui=ui)

    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    state = {"nodes_before": ["node"], "unhealthy_before": [("old", "app", "Pending")], "deployments_before": [("api", "app", 2, 2)], "pod_count_before": 1, "taint_start_time": 1}
    with patch.object(executor, "_node_is_ready", return_value=True), patch.object(executor, "_node_is_schedulable", return_value=True), patch.object(executor, "_node_taint_confirmed", return_value=False), patch.object(executor, "_get_node_conditions", return_value={}), patch.object(executor, "_get_deployment_readiness", return_value=[("api", "app", 2, 2)]), patch.object(executor, "_pending_pods_exist", return_value=[]), patch.object(executor, "_get_unhealthy_pods", return_value=[]), patch.object(executor, "_get_node_names", return_value={"node", "new"}), patch.object(executor.time, "time", return_value=10):
        executor._postchecks_node_taint("node", state, ui=ui, session=MagicMock())


def test_node_stress_helpers_record_unavailable_dns_and_probe_timeout(monkeypatch):
    snapshot = {}
    executor._record_node_stress_impact(
        snapshot,
        canary_probe={"summary": "dns unavailable", "dns_status": "unavailable"},
        node_conditions={"PIDPressure": "True"},
    )
    assert snapshot["canary_dns_unavailable"] is True
    assert snapshot["pid_pressure_fired"] is True

    times = iter([1, 1.2])
    with patch.object(executor, "_kubectl", side_effect=subprocess.TimeoutExpired(["kubectl"], 6)), patch.object(executor.time, "time", side_effect=lambda: next(times)):
        result = executor._probe_node_stress_canary({"namespace": "app", "pod": "canary"})
    assert result["dns_status"] == "failed"
    assert result["dns_elapsed_ms"] == 199
