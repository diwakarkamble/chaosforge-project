from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from chaosforge.engines.chaos_mesh.chaos_mesh_capabilities import (
    get_chaos_mesh_capability,
)


@dataclass
class ChaosMeshPreflightResult:
    status: str
    cluster: str
    kind: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def executable(self) -> bool:
        return self.status == "READY"


class ChaosMeshPreflight:
    """
    Read-only preflight checks for Chaos Mesh execution on EKS.

    The service does not install, modify, or delete anything.
    It only inspects Kubernetes resources and reports whether
    the requested Chaos Mesh capability appears available.
    """

    API_GROUP = "chaos-mesh.org"
    API_VERSION = "v1alpha1"

    # These defaults are intentionally configurable. The exact
    # workload names/selectors should be verified against the
    # installed Chaos Mesh deployment before real-cluster use.
    CONTROLLER_MANAGER_NAMESPACE = "chaos-mesh"
    CONTROLLER_MANAGER_NAME = "chaos-controller-manager"
    DAEMONSET_NAME = "chaos-daemon"

    CRD_PLURALS: ClassVar[dict[str, str]] = {
        "PodChaos": "podchaos",
        "NetworkChaos": "networkchaos",
        "DNSChaos": "dnschaos",
        "HTTPChaos": "httpchaos",
        "StressChaos": "stresschaos",
        "IOChaos": "iochaos",
        "TimeChaos": "timechaos",
        "KernelChaos": "kernelchaos",
        "AWSChaos": "awschaos",
        "JVMChaos": "jvmchaos",
        "BlockChaos": "blockchaos",
        "PhysicalMachineChaos": "physicalmachinechaos",
        "Workflow": "workflows",
        "Schedule": "schedules",
    }

    def __init__(self, discovery):
        self.discovery = discovery

    def check(
        self,
        cluster: str,
        kind: str,
        namespace: str | None = None,
    ) -> ChaosMeshPreflightResult:
        result = ChaosMeshPreflightResult(
            status="UNKNOWN",
            cluster=cluster,
            kind=kind,
        )

        if not cluster:
            result.status = "BLOCKED"
            result.blockers.append("EKS cluster is required.")
            return result

        capability = get_chaos_mesh_capability(kind)

        if capability is None:
            result.status = "BLOCKED"
            result.blockers.append(
                f"Unsupported Chaos Mesh preflight kind: {kind}"
            )
            return result

        try:
            self.discovery._configure_eks_kubernetes_client(cluster)

            result.checks.append({
                "name": "Kubernetes API",
                "status": "READY",
            })

        except Exception as exc:  # noqa: BLE001
            result.status = "BLOCKED"
            result.blockers.append(
                f"Kubernetes API is not available: {exc}"
            )
            result.checks.append({
                "name": "Kubernetes API",
                "status": "FAILED",
                "message": str(exc),
            })
            return result

        api = self.discovery.k8s_core_api

        if capability.requires_crd:
            custom_objects_api = self._custom_objects_api()

            if custom_objects_api is None:
                result.status = "BLOCKED"
                result.blockers.append(
                    "Kubernetes CustomObjectsApi is not available."
                )
                result.checks.append({
                    "name": "CustomObjectsApi",
                    "status": "FAILED",
                })
                return result

            crd_name = f"{self.CRD_PLURALS[kind]}.{self.API_GROUP}"

            try:
                custom_objects_api.get_cluster_custom_object(
                    group="apiextensions.k8s.io",
                    version="v1",
                    plural="customresourcedefinitions",
                    name=crd_name,
                )

                result.checks.append({
                    "name": f"{kind} CRD",
                    "status": "READY",
                    "resource": crd_name,
                })

            except Exception as exc:  # noqa: BLE001
                result.checks.append({
                    "name": f"{kind} CRD",
                    "status": "FAILED",
                    "resource": crd_name,
                    "message": str(exc),
                })
                result.blockers.append(
                    f"Required Chaos Mesh CRD is unavailable: {crd_name}"
                )

        if namespace and capability.supports_namespace:
            try:
                api.read_namespace(name=namespace)

                result.checks.append({
                    "name": "Target Namespace",
                    "status": "READY",
                    "namespace": namespace,
                })

            except Exception as exc:  # noqa: BLE001
                result.checks.append({
                    "name": "Target Namespace",
                    "status": "FAILED",
                    "namespace": namespace,
                    "message": str(exc),
                })
                result.blockers.append(
                    f"Target namespace is unavailable: {namespace}"
                )

        if capability.requires_controller_manager:
            self._check_controller_manager(result)

        if capability.requires_chaos_daemon:
            self._check_chaos_daemon(result)

        if result.blockers:
            result.status = "BLOCKED"
        else:
            result.status = "READY"

        return result

    def _check_controller_manager(
        self,
        result: ChaosMeshPreflightResult,
    ) -> None:
        apps_api = getattr(self.discovery, "k8s_apps_api", None)

        if apps_api is None:
            result.warnings.append(
                "Kubernetes AppsV1Api is not available; "
                "controller-manager health could not be verified."
            )
            result.checks.append({
                "name": "Chaos Controller Manager",
                "status": "UNKNOWN",
            })
            return

        try:
            deployment = apps_api.read_namespaced_deployment(
                name=self.CONTROLLER_MANAGER_NAME,
                namespace=self.CONTROLLER_MANAGER_NAMESPACE,
            )

            desired = deployment.spec.replicas or 0
            ready = deployment.status.ready_replicas or 0

            if desired > 0 and ready >= desired:
                result.checks.append({
                    "name": "Chaos Controller Manager",
                    "status": "READY",
                    "namespace": self.CONTROLLER_MANAGER_NAMESPACE,
                    "name_value": self.CONTROLLER_MANAGER_NAME,
                    "desired_replicas": desired,
                    "ready_replicas": ready,
                })
                return

            result.checks.append({
                "name": "Chaos Controller Manager",
                "status": "FAILED",
                "namespace": self.CONTROLLER_MANAGER_NAMESPACE,
                "name_value": self.CONTROLLER_MANAGER_NAME,
                "desired_replicas": desired,
                "ready_replicas": ready,
            })
            result.blockers.append(
                "Chaos Mesh Controller Manager is not ready."
            )

        except Exception as exc:  # noqa: BLE001
            result.checks.append({
                "name": "Chaos Controller Manager",
                "status": "FAILED",
                "namespace": self.CONTROLLER_MANAGER_NAMESPACE,
                "name_value": self.CONTROLLER_MANAGER_NAME,
                "message": str(exc),
            })
            result.blockers.append(
                "Chaos Mesh Controller Manager is unavailable."
            )

    def _check_chaos_daemon(
        self,
        result: ChaosMeshPreflightResult,
    ) -> None:
        apps_api = getattr(self.discovery, "k8s_apps_api", None)

        if apps_api is None:
            result.warnings.append(
                "Kubernetes AppsV1Api is not available; "
                "Chaos Daemon health could not be verified."
            )
            result.checks.append({
                "name": "Chaos Daemon",
                "status": "UNKNOWN",
            })
            return

        try:
            daemonset = apps_api.read_namespaced_daemon_set(
                name=self.DAEMONSET_NAME,
                namespace=self.CONTROLLER_MANAGER_NAMESPACE,
            )

            desired = daemonset.status.desired_number_scheduled or 0
            ready = daemonset.status.number_ready or 0

            if desired > 0 and ready >= desired:
                result.checks.append({
                    "name": "Chaos Daemon",
                    "status": "READY",
                    "namespace": self.CONTROLLER_MANAGER_NAMESPACE,
                    "name_value": self.DAEMONSET_NAME,
                    "desired": desired,
                    "ready": ready,
                })
                return

            result.checks.append({
                "name": "Chaos Daemon",
                "status": "FAILED",
                "namespace": self.CONTROLLER_MANAGER_NAMESPACE,
                "name_value": self.DAEMONSET_NAME,
                "desired": desired,
                "ready": ready,
            })
            result.blockers.append(
                "Chaos Mesh Daemon is not ready."
            )

        except Exception as exc:  # noqa: BLE001
            result.checks.append({
                "name": "Chaos Daemon",
                "status": "FAILED",
                "namespace": self.CONTROLLER_MANAGER_NAMESPACE,
                "name_value": self.DAEMONSET_NAME,
                "message": str(exc),
            })
            result.blockers.append(
                "Chaos Mesh Daemon is unavailable."
            )

    def _custom_objects_api(self):
        """
        Create a CustomObjectsApi using the Kubernetes configuration
        already selected by AWSDiscovery.

        AWSDiscovery configures the EKS-specific kubeconfig context
        before this method is called, so this client uses the same
        Kubernetes credentials and cluster context.
        """
        try:
            from kubernetes import client

            return client.CustomObjectsApi()

        except (ImportError, AttributeError):
            return None
