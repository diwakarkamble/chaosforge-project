from types import SimpleNamespace
from unittest.mock import MagicMock

from chaosforge.engines.chaos_mesh.chaos_mesh_runner import ChaosMeshRunner


def make_experiment(manifest):
    return SimpleNamespace(
        id="test-chaos-mesh",
        name="test-chaos-mesh",
        service="eks",
        json_file="",
        variables={
            "manifest": manifest,
        },
    )


def test_execute_creates_manifest():
    client = MagicMock()

    client.create.return_value = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": "pod-kill-test",
            "namespace": "default",
        },
        "status": {
            "phase": "Running",
        },
    }

    runner = ChaosMeshRunner(client=client)

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": "pod-kill-test",
            "namespace": "default",
        },
        "spec": {
            "action": "pod-kill",
            "mode": "one",
        },
    }

    result = runner.execute(
        make_experiment(manifest)
    )

    assert result.success is True
    assert result.resource_kind == "PodChaos"
    assert result.resource_name == "pod-kill-test"
    assert result.namespace == "default"
    assert result.phase == "Running"

    client.create.assert_called_once_with(manifest)

    client.delete.assert_called_once_with(
        kind="PodChaos",
        name="pod-kill-test",
        namespace="default",
    )


def test_execute_rejects_missing_manifest():
    runner = ChaosMeshRunner(
        client=MagicMock()
    )

    experiment = SimpleNamespace(
        name="invalid",
        variables={},
    )

    result = runner.execute(experiment)

    assert result.success is False
    assert "variables['manifest']" in result.error


def test_execute_rejects_incomplete_manifest():
    runner = ChaosMeshRunner(
        client=MagicMock()
    )

    experiment = SimpleNamespace(
        name="invalid",
        variables={
            "manifest": {
                "kind": "PodChaos",
            }
        },
    )

    result = runner.execute(experiment)

    assert result.success is False
    assert "missing required fields" in result.error


def test_execute_captures_client_error():
    client = MagicMock()

    client.create.side_effect = RuntimeError(
        "Kubernetes API unavailable"
    )

    runner = ChaosMeshRunner(client=client)

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": "pod-kill-test",
            "namespace": "chaos-testing",
        },
        "spec": {
            "action": "pod-kill",
            "mode": "one",
        },
    }

    result = runner.execute(
        make_experiment(manifest)
    )

    assert result.success is False
    assert result.resource_kind == "PodChaos"
    assert result.resource_name == "pod-kill-test"
    assert result.namespace == "chaos-testing"
    assert result.error == (
        "Kubernetes API unavailable"
    )


def test_execute_cleans_up_created_resource_after_keyboard_interrupt():
    client = MagicMock()
    client.create.return_value = {
        "metadata": {"name": "pod-kill-test", "namespace": "default"},
    }
    client.wait_for.side_effect = KeyboardInterrupt
    runner = ChaosMeshRunner(client=client)
    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {"name": "pod-kill-test", "namespace": "default"},
        "spec": {"action": "pod-kill", "mode": "one"},
    }

    experiment = make_experiment(manifest)
    experiment.variables["cleanup_after_execution"] = True

    result = runner.execute(experiment)

    assert result.success is False
    assert "KeyboardInterrupt interrupted execution" in result.error
    client.delete.assert_called_once_with(
        kind="PodChaos",
        name="pod-kill-test",
        namespace="default",
    )


def test_delete_removes_created_resource():
    client = MagicMock()

    runner = ChaosMeshRunner(client=client)

    from chaosforge.engines.chaos_mesh.chaos_mesh_models import (
        ChaosMeshExecutionResult,
    )

    result = ChaosMeshExecutionResult(
        success=True,
        resource_kind="PodChaos",
        resource_name="pod-kill-test",
        namespace="default",
    )

    returned = runner.delete(result)

    assert returned is result
    assert returned.success is True

    client.delete.assert_called_once_with(
        kind="PodChaos",
        name="pod-kill-test",
        namespace="default",
    )


def test_delete_marks_failure_when_api_delete_fails():
    client = MagicMock()

    client.delete.side_effect = RuntimeError(
        "delete failed"
    )

    runner = ChaosMeshRunner(client=client)

    from chaosforge.engines.chaos_mesh.chaos_mesh_models import (
        ChaosMeshExecutionResult,
    )

    result = ChaosMeshExecutionResult(
        success=True,
        resource_kind="PodChaos",
        resource_name="pod-kill-test",
        namespace="default",
    )

    returned = runner.delete(result)

    assert returned.success is False
    assert returned.error == "delete failed"


def test_execute_uses_default_namespace():
    client = MagicMock()

    client.create.return_value = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "StressChaos",
        "metadata": {
            "name": "stress-test",
        },
    }

    runner = ChaosMeshRunner(client=client)

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "StressChaos",
        "metadata": {
            "name": "stress-test",
        },
        "spec": {
            "mode": "one",
        },
    }

    result = runner.execute(
        make_experiment(manifest)
    )

    assert result.success is True
    assert result.namespace == "default"


def test_execute_preserves_resource_response():
    client = MagicMock()

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "NetworkChaos",
        "metadata": {
            "name": "network-delay",
            "namespace": "default",
        },
        "spec": {
            "action": "delay",
            "mode": "one",
        },
    }

    response = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "NetworkChaos",
        "metadata": {
            "name": "network-delay",
            "namespace": "default",
            "uid": "abc-123",
        },
        "spec": {
            "action": "delay",
            "mode": "one",
        },
        "status": {
            "phase": "Running",
            "message": "Chaos injected",
        },
    }

    client.create.return_value = response

    runner = ChaosMeshRunner(client=client)

    result = runner.execute(
        make_experiment(manifest)
    )

    assert result.success is True
    assert result.resource == response
    assert result.resource["metadata"]["uid"] == "abc-123"
    assert result.phase == "Running"
    assert result.message == "Chaos injected"

    client.create.assert_called_once_with(
        manifest
    )

    client.create.return_value = response

    runner = ChaosMeshRunner(client=client)

    result = runner.execute(
        make_experiment(response)
    )

    assert result.resource == response
    assert result.phase == "Running"
    assert result.message == "Chaos injected"


def test_execute_waits_for_finished_when_requested():
    client = MagicMock()

    created = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": "pod-kill-test",
            "namespace": "default",
        },
        "spec": {
            "action": "pod-kill",
            "mode": "one",
        },
        "status": {
            "phase": "Running",
        },
    }

    finished = {
        **created,
        "status": {
            "phase": "Finished",
            "message": "Chaos completed",
        },
    }

    client.create.return_value = created
    client.wait_for.return_value = finished

    experiment = make_experiment(created)
    experiment.variables["wait_for_completion"] = True
    experiment.variables["timeout_seconds"] = 30
    experiment.variables["poll_interval_seconds"] = 0

    runner = ChaosMeshRunner(client=client)

    result = runner.execute(experiment)

    assert result.success is True
    assert result.phase == "Finished"
    assert result.message == "Chaos completed"
    assert result.resource == finished

    client.wait_for.assert_called_once()
    wait_kwargs = client.wait_for.call_args.kwargs

    assert wait_kwargs["kind"] == "PodChaos"
    assert wait_kwargs["name"] == "pod-kill-test"
    assert wait_kwargs["namespace"] == "default"
    assert wait_kwargs["timeout_seconds"] == 30.0
    assert wait_kwargs["poll_interval_seconds"] == 0.0


def test_execute_dry_run_builds_preview_without_creating_resource():
    client = MagicMock()
    runner = ChaosMeshRunner(client=client)
    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {"name": "preview", "namespace": "apps"},
        "spec": {"action": "pod-failure", "mode": "one"},
    }
    experiment = make_experiment(manifest)
    experiment.variables["dry_run"] = "true"

    result = runner.execute(experiment)

    assert result.success is True
    assert result.phase == "Preview"
    assert result.manifest == manifest
    client.create.assert_not_called()


def test_execute_completes_when_shared_observer_confirms_live_fault():
    client = MagicMock()
    created = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {"name": "pod-kill-test", "namespace": "default"},
        "spec": {"action": "pod-kill", "mode": "one"},
        "status": {"phase": "Running"},
    }
    client.create.return_value = created
    client.wait_for.side_effect = lambda **kwargs: (
        kwargs["on_poll"](created),
        created,
    )[1]
    observer = MagicMock()
    observer.runtime_validation = {"fault_observed": False}

    def observe(*_args):
        observer.runtime_validation["fault_observed"] = True

    observer.observe_during.side_effect = observe
    runner = ChaosMeshRunner(client=client)

    result = runner.execute(make_experiment(created), observer=observer)

    assert result.success is True
    client.wait_for.assert_called_once()
    client.delete.assert_called_once_with(
        kind="PodChaos", name="pod-kill-test", namespace="default"
    )


def test_execute_reports_failed_chaos():
    client = MagicMock()

    created = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": "pod-kill-test",
            "namespace": "default",
        },
        "spec": {
            "action": "pod-kill",
            "mode": "one",
        },
        "status": {
            "phase": "Running",
        },
    }

    failed = {
        **created,
        "status": {
            "phase": "Failed",
            "message": "Chaos injection failed",
        },
    }

    client.create.return_value = created
    client.wait_for.return_value = failed

    experiment = make_experiment(created)
    experiment.variables["wait_for_completion"] = True

    runner = ChaosMeshRunner(client=client)

    result = runner.execute(experiment)

    assert result.success is False
    assert result.phase == "Failed"
    assert result.message == "Chaos injection failed"
    assert result.error == "Chaos injection failed"


def test_execute_reports_status_wait_error():
    client = MagicMock()

    created = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "NetworkChaos",
        "metadata": {
            "name": "network-delay",
            "namespace": "default",
        },
        "spec": {
            "action": "delay",
            "mode": "one",
        },
    }

    client.create.return_value = created
    client.wait_for.side_effect = RuntimeError(
        "Chaos Mesh status polling failed"
    )

    experiment = make_experiment(created)
    experiment.variables["wait_for_completion"] = True

    runner = ChaosMeshRunner(client=client)

    result = runner.execute(experiment)

    assert result.success is False
    assert result.resource_kind == "NetworkChaos"
    assert result.resource_name == "network-delay"
    assert result.namespace == "default"
    assert result.error == "Chaos Mesh status polling failed"

def test_generate_resource_name_is_unique():
    runner = ChaosMeshRunner()

    name1 = runner._generate_resource_name(
        "pod-failure",
        "PodChaos",
    )

    name2 = runner._generate_resource_name(
        "pod-failure",
        "PodChaos",
    )

    assert name1 != name2
    assert name1.startswith("chaosforge-pod-failure-podchaos-")
    assert name2.startswith("chaosforge-pod-failure-podchaos-")
