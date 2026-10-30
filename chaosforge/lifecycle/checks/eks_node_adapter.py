from typing import Any

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class EKSNodeAdapter(ResourceAdapter):
    """
    Adapter for reading an EKS Kubernetes node through the
    existing AWS discovery Kubernetes client.
    """

    name = "eks-node-adapter"

    def __init__(self, discovery):
        self.discovery = discovery

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        cluster = target["eks_cluster"]
        node_name = target["node_name"]

        self.discovery._configure_eks_kubernetes_client(cluster)

        node = self.discovery.k8s_core_api.read_node(
            name=node_name
        )

        conditions = {}
        if node.status and node.status.conditions:
            for condition in node.status.conditions:
                conditions[condition.type] = condition.status

        unschedulable = bool(
            node.spec.unschedulable
            if node.spec
            else False
        )

        ready = conditions.get("Ready")

        return {
            "exists": True,
            "cluster": cluster,
            "node": node_name,
            "unschedulable": unschedulable,
            "ready": ready,
            "conditions": conditions,
        }
