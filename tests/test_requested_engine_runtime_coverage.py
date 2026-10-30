from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from chaosforge.engines.chaos_mesh.chaos_mesh_client import ChaosMeshClient
from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshInstaller,
    HelmReleaseStatus,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_models import ChaosMeshExecutionResult
from chaosforge.engines.chaos_mesh.chaos_mesh_preflight import (
    ChaosMeshPreflight,
    ChaosMeshPreflightResult,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_runner import ChaosMeshRunner
from chaosforge.engines.chaos_toolkit import runner as toolkit_runner
from chaosforge.models.execution import ExecutionState


def completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


@pytest.mark.parametrize(
    ("process", "expected", "message"),
    [
        (completed(stdout="STATUS: deployed"), HelmReleaseStatus.INSTALLED, "installed"),
        (completed(stderr="release: not found", returncode=1), HelmReleaseStatus.ABSENT, "not installed"),
        (completed(stderr="forbidden", returncode=1), HelmReleaseStatus.ERROR, "forbidden"),
        (completed(returncode=1), HelmReleaseStatus.ERROR, "status."),
    ],
)
def test_installer_release_status_classifies_helm_results(process, expected, message):
    installer = ChaosMeshInstaller(kubeconfig_path="config", kube_context="ctx")
    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        return_value=process,
    ) as run:
        status, detail = installer.release_status()
    assert status is expected
    assert message in detail
    assert run.call_args.args[0][-4:] == ["--kubeconfig", "config", "--kube-context", "ctx"]


def test_installer_repository_add_update_and_os_errors_are_reported():
    installer = ChaosMeshInstaller()
    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        side_effect=[completed(stdout="stable"), completed(stderr="denied", returncode=1)],
    ):
        with pytest.raises(RuntimeError, match="add.*denied"):
            installer._ensure_repository()

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        side_effect=[completed(stdout="chaos-mesh"), completed(stdout="bad", returncode=1)],
    ):
        with pytest.raises(RuntimeError, match="update.*bad"):
            installer._ensure_repository()

    with patch.object(installer, "_ensure_repository", side_effect=OSError("helm vanished")):
        result = installer.install()
    assert result.status == "BLOCKED"
    assert result.message == "Chaos Mesh installation failed: helm vanished"


def test_client_wait_callbacks_timeouts_and_delete_errors():
    mesh_client = ChaosMeshClient(custom_objects_api=MagicMock())
    resource = {"status": {"phase": "Running"}}
    mesh_client.get = MagicMock(return_value=resource)
    observed = []
    assert mesh_client.wait_for("PodChaos", "pod", predicate=None, on_poll=observed.append) == resource
    assert observed == [resource]

    api_error = ApiException(status=503, reason="unavailable")
    mesh_client.get = MagicMock(side_effect=api_error)
    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_client.time.monotonic",
        side_effect=[0, 0, 0.5, 2],
    ), patch("chaosforge.engines.chaos_mesh.chaos_mesh_client.time.sleep") as sleep:
        with pytest.raises(TimeoutError, match=r"(?s)Last API error.*unavailable"):
            mesh_client.wait_for("PodChaos", "pod", timeout_seconds=1, poll_interval_seconds=5)
    sleep.assert_called_once_with(0.5)

    mesh_client.get = MagicMock(side_effect=api_error)
    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_client.time.monotonic",
        side_effect=[0, 0, 2],
    ):
        with pytest.raises(TimeoutError, match="to be deleted.*Last API error"):
            mesh_client.wait_for_deleted("PodChaos", "pod", timeout_seconds=1)


def test_preflight_reports_unavailable_optional_and_required_apis():
    discovery = MagicMock()
    discovery.k8s_core_api = MagicMock()
    discovery.k8s_apps_api = None
    preflight = ChaosMeshPreflight(discovery)
    with patch.object(preflight, "_custom_objects_api", return_value=None):
        result = preflight.check("cluster", "PodChaos", "apps")
    assert result.status == "BLOCKED"
    assert result.blockers == ["Kubernetes CustomObjectsApi is not available."]

    custom = MagicMock()
    discovery.k8s_core_api.read_namespace.side_effect = RuntimeError("namespace gone")
    with patch.object(preflight, "_custom_objects_api", return_value=custom):
        result = preflight.check("cluster", "PodChaos", "apps")
    assert "Target namespace is unavailable: apps" in result.blockers
    assert {check["status"] for check in result.checks if check["name"] != "Kubernetes API"} == {
        "READY",
        "FAILED",
        "UNKNOWN",
    }
    assert len(result.warnings) == 2


def test_preflight_reports_controller_and_daemon_read_failures():
    discovery = MagicMock()
    discovery.k8s_apps_api.read_namespaced_deployment.side_effect = RuntimeError("no deployment")
    discovery.k8s_apps_api.read_namespaced_daemon_set.side_effect = RuntimeError("no daemonset")
    result = ChaosMeshPreflightResult("UNKNOWN", "cluster", "PodChaos")
    preflight = ChaosMeshPreflight(discovery)
    preflight._check_controller_manager(result)
    preflight._check_chaos_daemon(result)
    assert result.blockers == [
        "Chaos Mesh Controller Manager is unavailable.",
        "Chaos Mesh Daemon is unavailable.",
    ]
    assert [check["message"] for check in result.checks] == ["no deployment", "no daemonset"]


def test_mesh_runner_retries_conflict_observes_and_confirms_cleanup():
    manifest = {
        "kind": "HTTPChaos",
        "metadata": {"name": "fixed", "namespace": "apps"},
        "spec": {"port": 8080},
    }
    finished = {**manifest, "metadata": {"name": "unique", "namespace": "apps"},
                "status": {"phase": "Finished", "message": "complete"}}
    client = MagicMock()
    client.create.side_effect = [RuntimeError("409 AlreadyExists"), finished]
    client.wait_for.return_value = finished
    mapper = MagicMock()
    mapper.build_manifest.return_value = manifest
    observer = MagicMock(runtime_validation={"fault_observed": True, "samples": 2})
    experiment = SimpleNamespace(
        id="HTTP Duplicate", name="HTTP", service="eks", engine="Chaos Mesh",
        json_file="definition.json", variables={"cleanup_after_execution": True},
    )
    runner = ChaosMeshRunner(client=client, mapper=mapper)
    with patch.object(runner, "_generate_resource_name", return_value="unique"):
        result = runner.execute(experiment, observer=observer)
    assert result.success is True
    assert result.resource_name == "unique"
    assert result.validation == {"fault_observed": True, "samples": 2}
    assert result.cleanup == {"attempted": True, "deleted": True, "confirmed_absent": True}
    assert client.create.call_count == 2
    observer.observe_during.assert_called()
    client.wait_for_deleted.assert_called_once_with(
        kind="HTTPChaos", name="unique", namespace="apps",
        timeout_seconds=60.0, poll_interval_seconds=2.0,
    )


def test_mesh_runner_helper_defaults_and_missing_delete_identifiers():
    experiment = SimpleNamespace(name="fallback", variables={
        "timeout_seconds": "bad", "poll_interval_seconds": None,
        "manifest": {"kind": "PodChaos", "metadata": "invalid"},
    })
    assert ChaosMeshRunner._status_timeout(experiment) == 60.0
    assert ChaosMeshRunner._status_poll_interval(experiment) == 2.0
    assert ChaosMeshRunner._resource_kind(experiment) == "PodChaos"
    assert ChaosMeshRunner._resource_name(experiment) == "fallback"
    assert ChaosMeshRunner._namespace(experiment) == "default"
    assert ChaosMeshRunner._is_terminal_failure({"status": {"phase": "Error"}}) is True
    assert ChaosMeshRunner._is_terminal_failure({"status": "unknown"}) is False
    client = MagicMock()
    runner = ChaosMeshRunner(client=client)
    result = ChaosMeshExecutionResult(
        success=True, resource_kind="", resource_name="", namespace="default"
    )
    assert runner.delete(result) is result
    result.resource_kind = "PodChaos"
    assert runner.delete(result) is result
    client.delete.assert_not_called()


def test_library_journal_output_is_report_safe():
    assert toolkit_runner._journal_output({
        "run": [{"activity": {"name": "inject"}, "status": "succeeded"}],
        "rollbacks": [{"activity": {"name": "restore"}, "status": "succeeded"}],
    }) == ["Action inject: succeeded\n", "Rollback restore: succeeded\n"]


def test_toolkit_journal_reasons_and_direct_recovery_messages():
    before = {"steady_state_met": False, "probes": [
        {"tolerance_met": False, "activity": {"name": "health"}}
    ]}
    assert "health" in toolkit_runner._deviation_reason({"steady_states": {"before": before}})
    after = {"steady_state_met": False, "probes": [
        {"tolerance_met": False, "activity": {"name": "recovery"}}
    ]}
    assert "recovery" in toolkit_runner._deviation_reason({
        "run": [{}], "steady_states": {"before": {"steady_state_met": True}, "after": after}
    })
    assert toolkit_runner._journal_has_failed_action({
        "rollbacks": [{"status": "failed", "exception": ["delete failed"]}]
    }) is True

    experiment = SimpleNamespace(engine="AWS FIS", variables={"region": "us-east-1"})
    recovery = {"success": True, "messages": ["stopped experiment", "restored target"]}
    with patch(
        "chaosforge.providers.aws.fis.actions.recover_interrupted_experiment",
        return_value=recovery,
    ) as recover:
        lines = []
        assert toolkit_runner._attempt_direct_recovery(experiment, lines) is True
    recover.assert_called_once_with("", "us-east-1")
    assert "restored target" in "".join(lines)

    lines = []
    assert toolkit_runner._attempt_direct_recovery(
        SimpleNamespace(engine="other", variables={}), lines
    ) is False
    assert "No provider fallback" in "".join(lines)


def test_toolkit_execute_interrupted_library_run_uses_fallback_cleanup():
    experiment = SimpleNamespace(
        id="test", service="eks", name="pod kill", engine="Other",
        json_file="experiment.json", variables={},
    )
    with patch.object(toolkit_runner, "load_experiment", return_value={}), \
         patch.object(toolkit_runner, "ensure_experiment_is_valid"), \
         patch.object(toolkit_runner, "run_experiment", return_value={"status": "interrupted", "interrupted": True, "rollbacks": []}), \
         patch.object(toolkit_runner.os.path, "exists", return_value=False):
        context = toolkit_runner.ExperimentRunner().execute(experiment)
    assert context.state == ExecutionState.CLEANUP_FAILED
    assert context.recovery["passed"] is False
    assert "recovery could not be confirmed" in experiment.error_message
