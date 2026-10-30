from __future__ import annotations

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshInstaller,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_preflight import ChaosMeshPreflight
from chaosforge.engines.chaos_mesh.version_policy import assess_installer


class ChaosMeshExecutionGate:
    """
    Ensures Chaos Mesh is ready before an experiment is executed.

    Planning/preflight remains read-only. Installation happens only at
    execution time and only when Helm confirms that the Chaos Mesh
    release is absent.
    """

    def __init__(
        self,
        discovery,
        installer=None,
        preflight=None,
        mapper=None,
    ) -> None:
        self.discovery = discovery
        self.installer = installer or ChaosMeshInstaller()
        self.preflight = preflight or ChaosMeshPreflight(discovery)
        self.mapper = mapper or ChaosMeshExperimentMapper()

    def ensure_ready(self, experiment) -> None:
        variables = getattr(experiment, "variables", {}) or {}

        cluster = variables.get("eks_cluster")

        if not cluster:
            raise RuntimeError(
                "Chaos Mesh execution requires 'eks_cluster' "
                "in experiment variables."
            )

        manifest = self.mapper.build_manifest(experiment)

        kind = manifest["kind"]

        namespace = (
            manifest.get("metadata", {}).get("namespace")
            or "default"
        )

        preflight_result = self.preflight.check(
            cluster=cluster,
            kind=kind,
            namespace=namespace,
        )

        # The preflight configures AWSDiscovery with the Kubernetes
        # kubeconfig/context used for this EKS cluster. Pass the same
        # authentication details to Helm.
        if self.installer is not None:
            self.installer.kubeconfig_path = getattr(
                self.discovery,
                "eks_kubeconfig_path",
                None,
            )
            self.installer.kube_context = getattr(
                self.discovery,
                "eks_kube_context",
                None,
            )

        assessment = assess_installer(
            self.installer, variables.get("aws_region", ""), cluster
        )
        action = getattr(experiment, "chaos_mesh_version_action", None)
        if assessment.state == "incompatible":
            raise RuntimeError(assessment.message)
        if assessment.state == "error":
            raise RuntimeError(assessment.message)
        if assessment.state == "newer":
            action = "continue"
        elif assessment.state == "current":
            action = "continue"
        elif action not in assessment.choices or action == "cancel":
            raise RuntimeError(
                f"Chaos Mesh {assessment.state} version decision is required for cluster '{cluster}'."
            )

        if assessment.state == "older" and action == "upgrade":
            upgrade_result = self.installer.upgrade()
            if upgrade_result.status == "BLOCKED":
                raise RuntimeError(upgrade_result.message)
            final_preflight = self.preflight.check(
                cluster=cluster, kind=kind, namespace=namespace
            )
            if not final_preflight.executable:
                raise RuntimeError(
                    "Chaos Mesh upgrade completed, but the environment is still not ready: "
                    + "; ".join(final_preflight.blockers)
                )
            return

        if assessment.state == "absent" and action == "install":
            install_result = self.installer.ensure_installed()
            if install_result.status == "BLOCKED":
                raise RuntimeError(install_result.message)
            final_preflight = self.preflight.check(
                cluster=cluster, kind=kind, namespace=namespace
            )
            if not final_preflight.executable:
                raise RuntimeError(
                    "Chaos Mesh installation completed, but the environment is still not ready: "
                    + "; ".join(final_preflight.blockers)
                )
            return

        if preflight_result.executable:
            return
        raise RuntimeError(
            "Chaos Mesh Helm release is installed, but the environment is not ready: "
            + "; ".join(preflight_result.blockers)
        )
