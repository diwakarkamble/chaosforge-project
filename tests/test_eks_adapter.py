from types import SimpleNamespace

from chaosforge.lifecycle.checks.eks_adapter import EKSDeploymentAdapter
from chaosforge.lifecycle.checks.eks_pod_adapter import EKSPodAdapter


class FakeAppsApi:
    def read_namespaced_deployment(
        self,
        *,
        name,
        namespace,
    ):
        assert name == "demo"
        assert namespace == "default"

        return SimpleNamespace(
            spec=SimpleNamespace(
                replicas=10,
            ),
            status=SimpleNamespace(
                ready_replicas=10,
                available_replicas=10,
                updated_replicas=10,
            ),
        )


class FakeDiscovery:
    def __init__(self):
        self.k8s_apps_api = FakeAppsApi()
        self.configured_cluster = None

    def _configure_eks_kubernetes_client(self, cluster):
        self.configured_cluster = cluster


def test_eks_deployment_adapter_capture():
    discovery = FakeDiscovery()
    adapter = EKSDeploymentAdapter(discovery)

    result = adapter.capture(
        {
            "eks_cluster": "test-cluster",
            "namespace": "default",
            "deployment_name": "demo",
        }
    )

    assert discovery.configured_cluster == "test-cluster"

    assert result == {
        "exists": True,
        "cluster": "test-cluster",
        "namespace": "default",
        "deployment": "demo",
        "desired_replicas": 10,
        "ready_replicas": 10,
        "available_replicas": 10,
        "updated_replicas": 10,
    }

class FakeCoreApi:
    def read_namespaced_pod(
        self,
        *,
        name,
        namespace,
    ):
        assert name == "demo-pod"
        assert namespace == "default"

        return SimpleNamespace(
            metadata=SimpleNamespace(
                owner_references=[
                    SimpleNamespace(
                        kind="ReplicaSet",
                        name="demo-rs",
                    )
                ]
            ),
            status=SimpleNamespace(
                phase="Running",
            ),
        )


class FakePodDiscovery:
    def __init__(self):
        self.k8s_core_api = FakeCoreApi()
        self.configured_cluster = None

    def _configure_eks_kubernetes_client(self, cluster):
        self.configured_cluster = cluster


def test_eks_pod_adapter_capture():
    discovery = FakePodDiscovery()
    adapter = EKSPodAdapter(discovery)

    result = adapter.capture(
        {
            "eks_cluster": "test-cluster",
            "namespace": "default",
            "pod": "demo-pod",
        }
    )

    assert discovery.configured_cluster == "test-cluster"

    assert result == {
        "exists": True,
        "cluster": "test-cluster",
        "namespace": "default",
        "pod": "demo-pod",
        "phase": "Running",
        "owner_kind": "ReplicaSet",
        "owner_name": "demo-rs",
    }
