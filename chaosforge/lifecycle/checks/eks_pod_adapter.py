from typing import Any

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class EKSPodAdapter(ResourceAdapter):
    """
    Adapter for reading an EKS pod through the existing
    AWS discovery Kubernetes client.

    The adapter converts the Kubernetes pod into a
    normalized resource snapshot used by lifecycle checks.
    """

    name = "eks-pod-adapter"

    def __init__(self, discovery):
        self.discovery = discovery

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        """
        Capture the current pod state.
        """
        cluster = target["eks_cluster"]
        namespace = target["namespace"]
        pod_name = target["pod"]

        self.discovery._configure_eks_kubernetes_client(cluster)

        pod = self.discovery.k8s_core_api.read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
        )

        phase = (
            pod.status.phase
            if pod.status
            else "Unknown"
        )

        owner_kind = None
        owner_name = None

        owner_references = (
            pod.metadata.owner_references
            if pod.metadata
            else None
        )

        if owner_references:
            owner = owner_references[0]
            owner_kind = owner.kind
            owner_name = owner.name

        return {
            "exists": True,
            "cluster": cluster,
            "namespace": namespace,
            "pod": pod_name,
            "phase": phase,
            "owner_kind": owner_kind,
            "owner_name": owner_name,
        }
