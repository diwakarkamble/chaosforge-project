from chaosforge.application.metadata import get_experiment
from chaosforge.engines.chaos_mesh.target_contract import WORKLOAD_EXPERIMENTS


def test_all_workload_chaos_mesh_experiments_use_deployment_or_pod_targeting():
    for experiment_id in WORKLOAD_EXPERIMENTS:
        experiment = get_experiment("chaos_mesh", experiment_id)
        inputs = {field["name"]: field for field in experiment["inputs"]}

        assert inputs["target_mode"]["default"] == "pod", experiment_id
        assert inputs["deployment"]["visible_when"] == {"target_mode": "deployment"}, experiment_id
        assert inputs["pod"]["visible_when"] == {"target_mode": "pod"}, experiment_id
        assert inputs["duration"]["type"] == "iso8601_duration", experiment_id
        assert inputs["duration"]["default"] == "PT60S", experiment_id
        assert inputs["mode"]["type"] == "chaos_mode", experiment_id
        assert inputs["chaos_value"]["visible_when"] == {"target_mode": "deployment"}, experiment_id


def test_non_workload_chaos_mesh_experiments_keep_their_specialized_targets():
    for experiment_id in {
        "chaos-mesh-aws",
        "chaos-mesh-physical-machine",
        "chaos-mesh-workflow",
        "chaos-mesh-schedule",
        "chaos-mesh-status-check",
    }:
        experiment = get_experiment("chaos_mesh", experiment_id)

        assert "target_mode" not in {field["name"] for field in experiment["inputs"]}


def test_container_kill_uses_one_container_selector():
    experiment = get_experiment("chaos_mesh", "chaos-mesh-container-kill")
    containers = [field for field in experiment["inputs"] if "container" in field["name"]]

    assert containers == [
        {
            "name": "container_name",
            "label": "Container",
            "type": "aws_resource",
            "resource_type": "eks-container",
            "parent": "namespace",
            "return": "name",
            "required": True,
        }
    ]
