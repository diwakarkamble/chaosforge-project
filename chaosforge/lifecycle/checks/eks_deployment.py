from typing import Any

from chaosforge.lifecycle.checks.base import ExperimentCheck


class EKSDeploymentCheck(ExperimentCheck):
    """
    Capture and validate the state of an EKS deployment.

    The Kubernetes API client is supplied by the existing
    AWS discovery layer. This check does not create a new
    AWS or Kubernetes connection.
    """

    name = "eks-deployment"

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

    def validate(
        self,
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        cluster = target["eks_cluster"]
        namespace = target["namespace"]
        deployment_name = target["deployment_name"]

        try:
            current = self.capture(
                {
                    "eks_cluster": cluster,
                    "namespace": namespace,
                    "deployment_name": deployment_name,
                }
            )

        except Exception as exc:  # noqa: BLE001
            return {
                "passed": False,
                "exists": False,
                "cluster": cluster,
                "namespace": namespace,
                "deployment": deployment_name,
                "error": str(exc),
            }

        desired_matches = (
            current["desired_replicas"]
            == baseline["desired_replicas"]
        )

        ready_matches = (
            current["ready_replicas"]
            == baseline["ready_replicas"]
        )

        available_matches = (
            current["available_replicas"]
            == baseline["available_replicas"]
        )

        passed = (
            current["exists"]
            and desired_matches
            and ready_matches
            and available_matches
        )

        return {
            "passed": passed,
            "exists": current["exists"],
            "cluster": cluster,
            "namespace": namespace,
            "deployment": deployment_name,
            "baseline": baseline,
            "current": current,
            "checks": {
                "desired_replicas": desired_matches,
                "ready_replicas": ready_matches,
                "available_replicas": available_matches,
            },
        }
