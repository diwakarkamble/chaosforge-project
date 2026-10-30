from __future__ import annotations

from typing import Any


class ChaosMeshTargetResolver:
    """
    Resolves ChaosForge EKS targets into Chaos Mesh selectors.

    Uses the existing AWSDiscovery EKS discovery methods.
    """

    def __init__(self, discovery):
        self.discovery = discovery

    def resolve_namespace(
        self,
        cluster: str,
        namespace: str,
    ) -> dict[str, Any]:
        if not cluster:
            raise ValueError("EKS cluster is required.")

        if not namespace:
            raise ValueError("Kubernetes namespace is required.")

        namespaces = self.discovery.list_eks_namespaces(
            cluster
        )

        match = next(
            (
                item
                for item in namespaces
                if item.get("name") == namespace
            ),
            None,
        )

        if match is None:
            raise LookupError(
                f"Namespace '{namespace}' was not found "
                f"in EKS cluster '{cluster}'."
            )

        return {
            "cluster": cluster,
            "namespace": namespace,
        }

    def resolve_deployment(
        self,
        cluster: str,
        namespace: str,
        deployment: str,
    ) -> dict[str, Any]:
        if not deployment:
            raise ValueError(
                "Kubernetes deployment is required."
            )

        self.resolve_namespace(
            cluster,
            namespace,
        )

        deployments = self.discovery.list_eks_deployments(
            cluster,
            namespace,
        )

        match = next(
            (
                item
                for item in deployments
                if item.get("name") == deployment
            ),
            None,
        )

        if match is None:
            raise LookupError(
                f"Deployment '{deployment}' was not found "
                f"in namespace '{namespace}'."
            )

        return {
            "cluster": cluster,
            "namespace": namespace,
            "deployment": deployment,
        }

    def deployment_selector(self, cluster, namespace, deployment):
        """Return the labels that select pods owned by one deployment."""
        self.resolve_deployment(cluster, namespace, deployment)
        self.discovery._configure_eks_kubernetes_client(cluster)
        resource = self.discovery.k8s_apps_api.read_namespaced_deployment(
            name=deployment, namespace=namespace
        )
        return dict(resource.spec.selector.match_labels or {})

    def resolve_pod(
        self,
        cluster: str,
        namespace: str,
        pod: str,
    ) -> dict[str, Any]:
        if not pod:
            raise ValueError(
                "Kubernetes pod is required."
            )

        self.resolve_namespace(
            cluster,
            namespace,
        )

        pods = self.discovery.list_eks_pods(
            cluster,
            namespace,
        )

        match = next(
            (
                item
                for item in pods
                if item.get("name") == pod
            ),
            None,
        )

        if match is None:
            raise LookupError(
                f"Pod '{pod}' was not found "
                f"in namespace '{namespace}'."
            )

        return {
            "cluster": cluster,
            "namespace": namespace,
            "pod": pod,
        }

    def resolve_node(
        self,
        cluster: str,
        node: str,
    ) -> dict[str, Any]:
        if not node:
            raise ValueError(
                "Kubernetes node is required."
            )

        nodes = self.discovery.list_eks_nodes(
            cluster
        )

        match = next(
            (
                item
                for item in nodes
                if item.get("name") == node
            ),
            None,
        )

        if match is None:
            raise LookupError(
                f"Node '{node}' was not found "
                f"in EKS cluster '{cluster}'."
            )

        return {
            "cluster": cluster,
            "node": node,
        }

    @staticmethod
    def pod_selector(
        namespace: str | None = None,
        pod: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        selector: dict[str, Any] = {}

        if namespace:
            selector["namespaces"] = [
                namespace
            ]

        if pod and namespace:
            selector["pods"] = {
                namespace: [pod]
            }

        if labels:
            selector["labelSelectors"] = dict(
                labels
            )

        return selector

    @staticmethod
    def node_selector(
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        selector: dict[str, Any] = {}

        if labels:
            selector["labelSelectors"] = dict(
                labels
            )

        return selector
