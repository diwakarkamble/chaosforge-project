"""
ChaosForge EKS Node Cordon Actions.

Provides ChaosForge-specific wrappers around the Chaos Toolkit
Kubernetes node actions.
"""

from chaosk8s.node.actions import cordon_node, uncordon_node


def cordon_eks_node(node_name):
    """
    Cordon the selected EKS node.
    """

    if not node_name:
        raise ValueError("EKS node name is required.")

    return cordon_node(name=node_name)


def uncordon_eks_node(node_name):
    """
    Uncordon the selected EKS node.
    """

    if not node_name:
        raise ValueError("EKS node name is required.")

    return uncordon_node(name=node_name)
