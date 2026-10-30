from typing import Any

from kubernetes.client.rest import ApiException

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class EKSContainerRestartAdapter(ResourceAdapter):
    """
    Adapter for validating recovery after an EKS pod restart.

    The original pod may be replaced, so recovery is evaluated
    using the original pod owner rather than the original pod name.
    """

    name = "eks-container-restart-adapter"

    def __init__(self, discovery):
        self.discovery = discovery
        self._owner_kind = None
        self._owner_name = None

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        cluster = target["eks_cluster"]
        namespace = target["namespace"]
        pod_name = target["pod_name"]

        self.discovery._configure_eks_kubernetes_client(cluster)

        owner_kind = self._owner_kind
        owner_name = self._owner_name

        # The original pod exists during the baseline capture.
        # After restart/termination it may no longer exist, so use
        # the owner captured during the baseline when necessary.
        try:
            pod = self.discovery.k8s_core_api.read_namespaced_pod(
                name=pod_name,
                namespace=namespace,
            )

            owner_references = (
                pod.metadata.owner_references
                if pod.metadata
                else None
            )

            if owner_references:
                owner = owner_references[0]
                owner_kind = owner.kind
                owner_name = owner.name

                # Persist the owner discovered from the baseline.
                self._owner_kind = owner_kind
                self._owner_name = owner_name

        except ApiException:
            # The original pod may have been deleted/replaced.
            # Continue using the owner captured during baseline.
            pass

        matching_pods = []

        if owner_kind and owner_name:
            matching_pods = self.discovery.find_eks_pods_by_owner(
                cluster,
                namespace,
                owner_kind,
                owner_name,
            )

        running_pods = [
            item
            for item in matching_pods
            if item.get("status") == "Running"
        ]

        recovered = bool(running_pods)

        return {
            "exists": bool(matching_pods) or bool(running_pods),
            "cluster": cluster,
            "namespace": namespace,
            "original_pod": pod_name,
            "owner_kind": owner_kind,
            "owner_name": owner_name,
            "matching_pods": matching_pods,
            "running_pods": running_pods,
            "recovered": recovered,
        }
