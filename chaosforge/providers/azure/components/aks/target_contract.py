"""Shared deployment-or-pod target contract for AKS workload faults."""

from chaosforge.lifecycle.checks.kubernetes_chaos import EKS_TO_AKS_EXPERIMENT

WORKLOAD_EXPERIMENTS = frozenset(EKS_TO_AKS_EXPERIMENT.values())


def bind_workload_target_contract(experiment):
    """Expose the same target choice already supported by the AKS CLI flow."""
    if experiment.get("id") not in WORKLOAD_EXPERIMENTS:
        return experiment
    inputs = experiment.get("inputs", [])
    if any(field.get("name") == "target_mode" for field in inputs):
        return experiment
    namespace_index = next(
        index for index, field in enumerate(inputs) if field.get("name") == "namespace"
    )
    deployment = next(field for field in inputs if field.get("name") == "deployment")
    deployment["visible_when"] = {"target_mode": "deployment"}
    deployment["required"] = False
    pod = {
        "name": "pod",
        "label": "Pod",
        "type": "azure_aks_pod",
        "required": False,
        "visible_when": {"target_mode": "pod"},
    }
    inputs = [field for field in inputs if field.get("name") != "deployment"]
    inputs[namespace_index + 1:namespace_index + 1] = [
        {
            "name": "target_mode",
            "label": "Target Mode",
            "type": "select",
            "required": True,
            "default": "deployment",
            "options": [
                {"value": "deployment", "label": "By Deployment - target pods via deployment label selector"},
                {"value": "pod", "label": "By Pod - target a single specific pod directly"},
            ],
        },
        deployment,
        pod,
    ]
    experiment["inputs"] = inputs
    return experiment
