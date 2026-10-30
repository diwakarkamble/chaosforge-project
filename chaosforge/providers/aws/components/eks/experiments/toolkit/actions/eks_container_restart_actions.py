"""
ChaosForge EKS Container Restart Actions.

A Kubernetes pod restart is implemented by terminating the selected
pod and allowing its owning controller to recreate it.
"""

from chaosk8s.pod.actions import terminate_pods


def restart_eks_container(
    pod_name,
    namespace="default",
    grace_period=-1,
):
    """
    Restart a selected EKS workload by terminating its pod.

    Kubernetes controllers such as Deployments, ReplicaSets and
    StatefulSets are responsible for recreating the pod.
    """

    if not pod_name:
        raise ValueError("EKS pod name is required.")

    if not namespace:
        namespace = "default"

    return terminate_pods(
        name_pattern=pod_name,
        ns=namespace,
        qty=1,
        mode="fixed",
        rand=False,
        grace_period=int(grace_period),
    )
