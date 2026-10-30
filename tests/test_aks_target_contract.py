from chaosforge.application.metadata import get_experiment
from chaosforge.lifecycle.checks.kubernetes_chaos import EKS_TO_AKS_EXPERIMENT


def test_mapped_aks_workload_experiments_support_deployment_or_pod_targeting():
    for experiment_id in set(EKS_TO_AKS_EXPERIMENT.values()):
        experiment = get_experiment("aks", experiment_id)
        inputs = {field["name"]: field for field in experiment["inputs"]}

        assert inputs["target_mode"]["type"] == "select", experiment_id
        assert inputs["deployment"]["visible_when"] == {"target_mode": "deployment"}, experiment_id
        assert inputs["pod"]["visible_when"] == {"target_mode": "pod"}, experiment_id


def test_aks_container_kill_retains_one_container_selector():
    experiment = get_experiment("aks", "aks-container-kill")
    containers = [field for field in experiment["inputs"] if field["name"] == "container_name"]

    assert len(containers) == 1
    assert containers[0]["type"] == "azure_aks_container"
