from typing import Any

from chaosforge.lifecycle.checks.base import ExperimentCheck
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.eks_adapter import EKSDeploymentAdapter
from chaosforge.lifecycle.checks.eks_container_restart_adapter import (
    EKSContainerRestartAdapter,
)
from chaosforge.lifecycle.checks.eks_node_adapter import EKSNodeAdapter
from chaosforge.lifecycle.checks.eks_pod_adapter import EKSPodAdapter


class EKSDeploymentCheck(ExperimentCheck):
    """
    Lifecycle check for an EKS deployment.

    Resource access is handled by EKSDeploymentAdapter while
    validation is delegated to CommonResourceCheck with
    EKS-specific replica predicates.
    """

    name = "eks-deployment"

    def __init__(self, discovery):
        adapter = EKSDeploymentAdapter(discovery)

        self.common_check = CommonResourceCheck(
            adapter,
            predicates={
                "exists": lambda current, baseline: (
                    current.get("exists") == baseline.get("exists")
                ),
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "desired_replicas": lambda current, baseline: (
                    current.get("desired_replicas")
                    == baseline.get("desired_replicas")
                ),
                "ready_replicas": lambda current, baseline: (
                    current.get("ready_replicas")
                    == baseline.get("ready_replicas")
                ),
                "available_replicas": lambda current, baseline: (
                    current.get("available_replicas")
                    == baseline.get("available_replicas")
                ),
            },
            name=self.name,
        )

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        return self.common_check.capture(target)

    def validate(
        self,
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.common_check.validate(
            target,
            baseline,
        )

        result.update(
            {
                "cluster": target["eks_cluster"],
                "namespace": target["namespace"],
                "deployment": target["deployment_name"],
            }
        )

        return result


class EKSPodCheck(ExperimentCheck):
    """
    Lifecycle check for an EKS pod.

    Resource access is handled by EKSPodAdapter.
    """

    name = "eks-pod"

    def __init__(self, discovery):
        adapter = EKSPodAdapter(discovery)

        self.common_check = CommonResourceCheck(
            adapter,
            predicates={
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
            },
            name=self.name,
        )

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        return self.common_check.capture(target)

    def validate(
        self,
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.common_check.validate(
            target,
            baseline,
        )

        result.update(
            {
                "cluster": target["eks_cluster"],
                "namespace": target["namespace"],
                "pod": target["pod"],
            }
        )

        return result


class EKSNodeCheck(ExperimentCheck):
    """
    Lifecycle check for an EKS Kubernetes node.
    """

    name = "eks-node"

    def __init__(self, discovery):
        adapter = EKSNodeAdapter(discovery)

        self.common_check = CommonResourceCheck(
            adapter,
            predicates={
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "unschedulable": lambda current, baseline: (
                    current.get("unschedulable")
                    == baseline.get("unschedulable")
                ),
                "ready": lambda current, baseline: (
                    current.get("ready")
                    == baseline.get("ready")
                ),
            },
            name=self.name,
        )

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        return self.common_check.capture(target)

    def validate(
        self,
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.common_check.validate(
            target,
            baseline,
        )

        result.update(
            {
                "cluster": target["eks_cluster"],
                "node": target["node_name"],
            }
        )

        return result


class EKSContainerRestartCheck(ExperimentCheck):
    """
    Lifecycle check for EKS container/pod restart chaos.

    The original pod may be replaced, so recovery is validated
    through the original pod owner.
    """

    name = "eks-container-restart"

    def __init__(self, discovery):
        adapter = EKSContainerRestartAdapter(discovery)

        self.common_check = CommonResourceCheck(
            adapter,
            predicates={
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "workload_recovered": lambda current, baseline: (
                    current.get("recovered") is True
                ),
            },
            name=self.name,
        )

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        return self.common_check.capture(target)

    def validate(
        self,
        target: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.common_check.validate(
            target,
            baseline,
        )

        result.update(
            {
                "cluster": target["eks_cluster"],
                "namespace": target["namespace"],
                "pod": target["pod_name"],
            }
        )

        return result
