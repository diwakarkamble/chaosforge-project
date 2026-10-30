from __future__ import annotations

import re
import uuid
from typing import Any

from chaosforge.engines.chaos_mesh.chaos_mesh_client import ChaosMeshClient
from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_manifest_builder import (
    ChaosMeshManifestBuilder,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_models import (
    ChaosMeshExecutionResult,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_target_resolver import (
    ChaosMeshTargetResolver,
)
from chaosforge.providers.aws.discovery import AWSDiscovery


class ChaosMeshRunner:
    """
    Executes Chaos Mesh experiments through the Kubernetes API.
    """

    def __init__(
        self,
        client: ChaosMeshClient | None = None,
        builder: ChaosMeshManifestBuilder | None = None,
        mapper: ChaosMeshExperimentMapper | None = None,
        discovery: AWSDiscovery | None = None,
    ):
        self.client = client or ChaosMeshClient()
        self.builder = builder or ChaosMeshManifestBuilder()

        self.discovery = discovery

        target_resolver = None

        if discovery is not None:
            target_resolver = ChaosMeshTargetResolver(
                discovery
            )

        self.mapper = mapper or ChaosMeshExperimentMapper(
            builder=self.builder,
            target_resolver=target_resolver,
        )

    def execute(
        self,
        experiment: Any,
        observer=None,
    ) -> ChaosMeshExecutionResult:

        manifest = None
        resource = None
        kind = ""
        resource_name = ""
        namespace = "default"
        created = False

        wait_requested = self._status_wait_requested(experiment)
        cleanup_requested = self._cleanup_requested(experiment)

        try:
            variables = getattr(experiment, "variables", {}) or {}
            if self.discovery is not None and variables.get("eks_cluster"):
                self.discovery._configure_eks_kubernetes_client(
                    variables["eks_cluster"]
                )
                # The CR client must use the same EKS context as discovery,
                # prechecks, and fault observation, never ambient kubeconfig.
                self.client.custom_objects_api = self.discovery.k8s_custom_api
                self.client._api_client = self.discovery.k8s_api_client

            manifest = self.mapper.build_manifest(experiment)

            if str(variables.get("dry_run", "")).lower() == "true":
                return ChaosMeshExecutionResult(
                    success=True,
                    resource_kind=manifest["kind"],
                    resource_name=manifest.get("metadata", {}).get("name", ""),
                    namespace=manifest.get("metadata", {}).get("namespace", "default"),
                    phase="Preview",
                    message="Dry run preview; no Chaos Mesh resource was created.",
                    manifest=manifest,
                )

            kind = manifest["kind"]

            namespace = (
                manifest.get("metadata", {}).get("namespace")
                or "default"
            )

            resource_name = (
                manifest.get("metadata", {}).get("name")
                or ""
            )

            # Preserve the mapper-generated name by default.
            # Only generate a unique name when Kubernetes reports that
            # the requested name already exists.
            try:
                resource = self.client.create(manifest)

            except Exception as create_exc:
                if not self._is_already_exists_error(create_exc):
                    raise

                experiment_id = str(
                    getattr(experiment, "id", "")
                    or "experiment"
                )

                resource_name = self._generate_resource_name(
                    experiment_id=experiment_id,
                    kind=kind,
                )

                manifest.setdefault("metadata", {})
                manifest["metadata"]["name"] = resource_name

                resource = self.client.create(manifest)

            created = True

            metadata = resource.get("metadata", {})

            resource_name = metadata.get(
                "name",
                resource_name,
            )

            namespace = metadata.get(
                "namespace",
                namespace,
            )

            if observer is not None:
                observer.observe_during(
                    getattr(experiment, "variables", {}) or {},
                    manifest,
                    resource,
                )

            if wait_requested or cleanup_requested or observer is not None:
                resource = self.client.wait_for(
                    kind=kind,
                    name=resource_name,
                    namespace=namespace,
                    predicate=lambda item: (
                        self._is_terminal_success(item)
                        or self._is_terminal_failure(item)
                        # PodChaos remains active until explicitly deleted.
                        # Once the shared Kubernetes observer proves the fault
                        # occurred, cleanup can begin and post-validation can
                        # verify workload recovery.
                        or bool(
                            observer
                            and observer.runtime_validation.get("fault_observed")
                        )
                    ),
                    timeout_seconds=self._status_timeout(
                        experiment
                    ),
                    poll_interval_seconds=self._status_poll_interval(
                        experiment
                    ),
                    on_poll=(
                        lambda item: observer.observe_during(
                            getattr(experiment, "variables", {}) or {},
                            manifest,
                            item,
                        )
                        if observer is not None
                        else None
                    ),
                )

            status = resource.get("status", {})

            phase = (
                status.get("phase")
                if isinstance(status, dict)
                else None
            )

            message = (
                status.get("message")
                if isinstance(status, dict)
                else None
            )

            validation = (
                dict(observer.runtime_validation)
                if observer is not None
                else {}
            )
            success = True

            if wait_requested or cleanup_requested or observer is not None:
                success = self._is_terminal_success(resource) or bool(
                    observer and validation.get("fault_observed")
                )
            if observer is not None and not validation.get("fault_observed"):
                success = False
                message = message or "The configured fault was not observed."

            result = ChaosMeshExecutionResult(
                success=success,
                resource_kind=kind,
                resource_name=resource_name,
                namespace=namespace,
                phase=phase,
                message=message,
                resource=resource,
                error=(
                    message
                    if not success
                    else None
                ),
                manifest=manifest,
                validation=validation,
            )

        except BaseException as exc:
            # A Ctrl-C can arrive after the custom resource was created. Treat
            # it as a failed execution rather than skipping the cleanup below.
            # The lifecycle caller receives the failed result once Kubernetes
            # confirms that the fault resource has been removed.
            error = str(exc) or f"{type(exc).__name__} interrupted execution"
            result = ChaosMeshExecutionResult(
                success=False,
                resource_kind=kind or self._resource_kind(
                    experiment
                ),
                resource_name=resource_name or self._resource_name(
                    experiment
                ),
                namespace=namespace or self._namespace(
                    experiment
                ),
                error=error,
                manifest=manifest or {},
            )

        # Cleanup is part of the Chaos Mesh runner lifecycle.
        # StatusCheck is represented by a Workflow resource and must remain
        # available while Chaos Mesh reconciles the StatusCheck workflow node.
        is_status_check = (
            getattr(experiment, "id", None)
            == "chaos-mesh-status-check"
        )

        if (
            created
            and resource_name
            and kind
            and kind != "Schedule"
            and not is_status_check
        ):
            result = self.delete(result)

        return result

    @staticmethod
    def _cleanup_requested(experiment: Any) -> bool:
        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}

        return bool(
            variables.get(
                "cleanup_after_execution",
                False,
            )
        )

    @staticmethod
    def _is_already_exists_error(exc: Exception) -> bool:
        text = str(exc).lower()

        return (
            "alreadyexists" in text
            or "already exists" in text
            or "409" in text
        )
    def _generate_resource_name(self, experiment_id: str, kind: str) -> str:
        """
        Generate a unique Kubernetes-safe Chaos Mesh resource name.

        Kubernetes resource names must be lowercase DNS-compatible names.
        Keep the experiment identity readable while ensuring every execution
        gets a unique resource.
        """
        base = f"chaosforge-{experiment_id}-{kind}"

        # Kubernetes DNS-1123 compatible characters only.
        base = re.sub(r"[^a-z0-9-]+", "-", base.lower())
        base = re.sub(r"-+", "-", base).strip("-")

        # 8-character UUID gives enough uniqueness for executions.
        suffix = uuid.uuid4().hex[:8]

        # Kubernetes names are limited to 253 characters.
        max_base_length = 253 - len(suffix) - 1
        base = base[:max_base_length].rstrip("-")

        return f"{base}-{suffix}"

    @staticmethod
    def _status_wait_requested(experiment: Any) -> bool:
        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}

        return bool(
            variables.get(
                "wait_for_completion",
                False,
            )
        )

    @staticmethod
    def _status_timeout(experiment: Any) -> float:
        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}

        value = variables.get(
            "timeout_seconds",
            60.0,
        )

        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 60.0

    @staticmethod
    def _status_poll_interval(experiment: Any) -> float:
        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}

        value = variables.get(
            "poll_interval_seconds",
            2.0,
        )

        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 2.0

    @staticmethod
    def _is_terminal_success(resource: dict[str, Any]) -> bool:
        phase = (
            resource.get("status", {}).get("phase")
            if isinstance(resource.get("status"), dict)
            else None
        )

        return phase in {
            "Finished",
            "Succeeded",
        }

    @staticmethod
    def _is_terminal_failure(resource: dict[str, Any]) -> bool:
        phase = (
            resource.get("status", {}).get("phase")
            if isinstance(resource.get("status"), dict)
            else None
        )

        return phase in {
            "Failed",
            "Error",
        }

    def delete(
        self,
        result: ChaosMeshExecutionResult,
    ) -> ChaosMeshExecutionResult:

        if not result.resource_kind:
            return result

        if not result.resource_name:
            return result

        try:
            self.client.delete(
                kind=result.resource_kind,
                name=result.resource_name,
                namespace=result.namespace,
            )

            # DELETE is asynchronous when Kubernetes finalizers are present.
            # Wait until Kubernetes confirms that the resource is gone.
            self.client.wait_for_deleted(
                kind=result.resource_kind,
                name=result.resource_name,
                namespace=result.namespace,
                timeout_seconds=self._cleanup_timeout(),
                poll_interval_seconds=self._status_poll_interval_from_result(),
            )

            result.cleanup = {
                "attempted": True,
                "deleted": True,
                "confirmed_absent": True,
            }

            return result

        except Exception as exc:  # noqa: BLE001
            result.success = False
            result.error = str(exc)
            result.cleanup = {
                "attempted": True,
                "deleted": False,
                "confirmed_absent": False,
                "error": str(exc),
            }

            return result

    @staticmethod
    def _cleanup_timeout() -> float:
        return 60.0

    @staticmethod
    def _status_poll_interval_from_result() -> float:
        return 2.0

    @staticmethod
    def _resource_kind(
        experiment: Any,
    ) -> str:

        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}

        manifest = variables.get(
            "manifest"
        )

        if isinstance(manifest, dict):
            return str(
                manifest.get(
                    "kind",
                    "",
                )
            )

        return ""

    @staticmethod
    def _resource_name(
        experiment: Any,
    ) -> str:

        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}

        manifest = variables.get(
            "manifest"
        )

        if isinstance(manifest, dict):

            metadata = manifest.get(
                "metadata",
                {},
            )

            if isinstance(metadata, dict):
                return str(
                    metadata.get(
                        "name",
                        "",
                    )
                )

        return str(
            getattr(
                experiment,
                "name",
                "",
            )
        )

    @staticmethod
    def _namespace(
        experiment: Any,
    ) -> str:

        variables = getattr(
            experiment,
            "variables",
            {},
        ) or {}

        manifest = variables.get(
            "manifest"
        )

        if isinstance(manifest, dict):

            metadata = manifest.get(
                "metadata",
                {},
            )

            if isinstance(metadata, dict):
                return str(
                    metadata.get(
                        "namespace",
                        "default",
                    )
                )

        return "default"
