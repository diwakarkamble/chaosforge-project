from typing import Any

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class EKSDeploymentAdapter(ResourceAdapter):
    """
    Adapter for reading an EKS deployment through the existing
    AWS discovery Kubernetes client.

    The adapter converts the Kubernetes deployment into a
    normalized resource snapshot used by lifecycle checks.
    """

    name = "eks-deployment-adapter"

    def __init__(self, discovery):
        self.discovery = discovery

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        cluster = target["eks_cluster"]
        namespace = target["namespace"]
        deployment_name = target["deployment_name"]

        self.discovery._configure_eks_kubernetes_client(cluster)

        deployment = self.discovery.k8s_apps_api.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
        )

        spec = deployment.spec
        status = deployment.status

        return {
            "exists": True,
            "cluster": cluster,
            "namespace": namespace,
            "deployment": deployment_name,
            "desired_replicas": spec.replicas or 0,
            "ready_replicas": status.ready_replicas or 0,
            "available_replicas": status.available_replicas or 0,
            "updated_replicas": status.updated_replicas or 0,
        }
