from chaosforge.engines.chaos_mesh.chaos_mesh_models import (
    ChaosMeshExecutionResult,
    ChaosMeshExperiment,
    ChaosMeshTarget,
    ChaosMeshWorkflow,
)


def test_chaos_mesh_target_defaults():
    target = ChaosMeshTarget()

    assert target.namespace is None
    assert target.label_selector == {}
    assert target.pod_selector == {}
    assert target.node_selector == {}


def test_chaos_mesh_experiment_to_manifest():
    experiment = ChaosMeshExperiment(
        kind="PodChaos",
        name="pod-delete-test",
        namespace="chaos-testing",
        spec={
            "action": "pod-kill",
            "mode": "one",
        },
        labels={
            "chaosforge.io/managed": "true",
        },
    )

    manifest = experiment.to_manifest()

    assert manifest["apiVersion"] == "chaos-mesh.org/v1alpha1"
    assert manifest["kind"] == "PodChaos"
    assert manifest["metadata"]["name"] == "pod-delete-test"
    assert manifest["metadata"]["namespace"] == "chaos-testing"
    assert manifest["metadata"]["labels"]["chaosforge.io/managed"] == "true"
    assert manifest["spec"]["action"] == "pod-kill"
    assert manifest["spec"]["mode"] == "one"


def test_chaos_mesh_experiment_without_optional_metadata():
    experiment = ChaosMeshExperiment(
        kind="StressChaos",
        name="cpu-stress",
        spec={
            "mode": "one",
        },
    )

    manifest = experiment.to_manifest()

    assert "labels" not in manifest["metadata"]
    assert "annotations" not in manifest["metadata"]


def test_chaos_mesh_workflow_to_manifest():
    workflow = ChaosMeshWorkflow(
        name="network-workflow",
        namespace="chaos-testing",
        entry="serial-entry",
        templates=[
            {
                "name": "serial-entry",
                "templateType": "Serial",
            }
        ],
    )

    manifest = workflow.to_manifest()

    assert manifest["apiVersion"] == "chaos-mesh.org/v1alpha1"
    assert manifest["kind"] == "Workflow"
    assert manifest["metadata"]["name"] == "network-workflow"
    assert manifest["spec"]["entry"] == "serial-entry"
    assert len(manifest["spec"]["templates"]) == 1


def test_chaos_mesh_workflow_schedule():
    workflow = ChaosMeshWorkflow(
        name="scheduled-chaos",
        schedule="*/10 * * * *",
    )

    manifest = workflow.to_manifest()

    assert manifest["spec"]["schedule"] == "*/10 * * * *"


def test_chaos_mesh_execution_result():
    result = ChaosMeshExecutionResult(
        success=True,
        resource_kind="PodChaos",
        resource_name="pod-delete-test",
        namespace="default",
        phase="Running",
        message="Chaos experiment submitted.",
    )

    assert result.success is True
    assert result.resource_kind == "PodChaos"
    assert result.resource_name == "pod-delete-test"
    assert result.namespace == "default"
    assert result.phase == "Running"
