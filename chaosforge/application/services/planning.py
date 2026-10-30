from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

from chaosforge.application.duration import duration_seconds, is_iso8601_duration
from chaosforge.application.metadata_loader import load_metadata
from chaosforge.engines.chaos_mesh.chaos_mesh_preflight import ChaosMeshPreflight
from chaosforge.models.planning import PlanResult


def _aws_discovery(region):
    from chaosforge.providers.aws.discovery import AWSDiscovery

    return AWSDiscovery(region)


class PlanService:
    """
    Build a read-only execution plan for a ChaosForge campaign.

    This service MUST NOT execute experiments or mutate AWS resources.
    """

    def __init__(
        self,
        discovery_factory=None,
        chaos_mesh_preflight_factory=ChaosMeshPreflight,
    ):
        self.discovery_factory = discovery_factory or _aws_discovery
        self.chaos_mesh_preflight_factory = chaos_mesh_preflight_factory

    def plan_campaign(self, campaign, *, allow_chaos_mesh_setup=False) -> PlanResult:
        result = PlanResult()

        if campaign is None:
            result.blockers.append("No campaign supplied.")
            return result.finalize()

        for experiment in campaign.experiments:
            self._plan_experiment(
                experiment, result, allow_chaos_mesh_setup=allow_chaos_mesh_setup
            )

        self._finalize_campaign_impact(result)
        self._finalize_duration(result)

        return result.finalize()

    def plan_experiment(self, experiment) -> PlanResult:
        result = PlanResult()

        if experiment is None:
            result.blockers.append("No experiment supplied.")
            return result.finalize()

        self._plan_experiment(experiment, result)
        self._finalize_campaign_impact(result)
        self._finalize_duration(result)

        return result.finalize()

    def _plan_experiment(
        self,
        experiment,
        result: PlanResult,
        *,
        allow_chaos_mesh_setup=False,
    ) -> None:
        metadata = load_metadata(experiment.service)

        experiment_plan = {
            "id": experiment.id,
            "service": experiment.service,
            "name": experiment.name,
            "engine": experiment.engine,
            "status": "PLANNED",
        }

        if metadata is None:
            result.blockers.append(
                f"Metadata not found for service '{experiment.service}'."
            )
            experiment_plan["status"] = "BLOCKED"
            result.experiments.append(experiment_plan)
            return

        definition = next(
            (
                item
                for item in metadata.get("experiments", [])
                if item.get("id") == experiment.id
            ),
            None,
        )

        if definition is None:
            result.blockers.append(
                f"Experiment '{experiment.id}' was not found "
                f"for service '{experiment.service}'."
            )
            experiment_plan["status"] = "BLOCKED"
            result.experiments.append(experiment_plan)
            return

        experiment_plan["description"] = definition.get(
            "description",
            "",
        )
        experiment_plan["variables"] = dict(
            experiment.variables or {}
        )

        result.experiments.append(experiment_plan)

        region = (experiment.variables or {}).get("aws_region")

        if not region:
            region = self._default_region(definition)

        if not region:
            result.blockers.append(
                f"Experiment '{experiment.id}' does not specify "
                "an AWS region."
            )
            experiment_plan["status"] = "BLOCKED"
            return

        try:
            discovery = self.discovery_factory(region)

            targets = self._resolve_targets(
                experiment,
                definition,
                discovery,
            )

        except Exception as exc:  # noqa: BLE001
            result.blockers.append(
                f"Unable to resolve targets for "
                f"'{experiment.id}': {exc}"
            )
            experiment_plan["status"] = "BLOCKED"
            return

        if not targets:
            result.blockers.append(
                f"No targets could be resolved for "
                f"experiment '{experiment.id}'."
            )
            experiment_plan["status"] = "BLOCKED"
            return

        for target in targets:
            result.targets.append(
                {
                    "experiment_id": experiment.id,
                    "service": experiment.service,
                    "region": region,
                    **target,
                }
            )

        self._run_chaos_mesh_preflight(
            experiment,
            definition,
            discovery,
            result,
            experiment_plan,
            allow_setup=allow_chaos_mesh_setup,
        )

        self._add_permissions(definition, result)
        self._add_capabilities(experiment, result)
        self._add_recovery(definition, experiment, result)

    def _run_chaos_mesh_preflight(
        self,
        experiment,
        definition: dict[str, Any],
        discovery,
        result: PlanResult,
        experiment_plan: dict[str, Any],
        *,
        allow_setup=False,
    ) -> None:
        if (experiment.engine or "").strip() != "Chaos Mesh":
            return

        variables = experiment.variables or {}
        cluster = variables.get("eks_cluster")

        kind = self._load_chaos_mesh_kind(
            experiment,
            definition,
        )

        if not cluster:
            result.blockers.append(
                f"Chaos Mesh experiment '{experiment.id}' "
                "requires an EKS cluster."
            )
            experiment_plan["status"] = "BLOCKED"
            return

        if not kind:
            result.blockers.append(
                f"Chaos Mesh experiment '{experiment.id}' "
                "does not define a Chaos Mesh kind."
            )
            experiment_plan["status"] = "BLOCKED"
            return

        preflight = self.chaos_mesh_preflight_factory(discovery)
        preflight_result = preflight.check(
            cluster=cluster,
            kind=kind,
            namespace=variables.get("namespace"),
        )

        experiment_plan["chaos_mesh_preflight"] = {
            "status": preflight_result.status,
            "kind": kind,
            "cluster": cluster,
            "checks": list(preflight_result.checks),
            "blockers": list(preflight_result.blockers),
            "warnings": list(preflight_result.warnings),
        }

        for warning in preflight_result.warnings:
            result.warnings.append(
                f"Chaos Mesh '{experiment.id}': {warning}"
            )

        if not preflight_result.executable:
            remediable = all(
                blocker.startswith("Required Chaos Mesh CRD is unavailable:")
                or blocker.startswith("Chaos Mesh Controller Manager")
                or blocker.startswith("Chaos Mesh Daemon")
                for blocker in preflight_result.blockers
            )
            if allow_setup and remediable:
                experiment_plan["chaos_mesh_preflight"]["status"] = "SETUP_REQUIRED"
                result.warnings.append(
                    f"Chaos Mesh '{experiment.id}': installation or upgrade is required before execution."
                )
                return
            experiment_plan["status"] = "BLOCKED"

            for blocker in preflight_result.blockers:
                result.blockers.append(
                    f"Chaos Mesh '{experiment.id}': {blocker}"
                )

    @staticmethod
    def _load_chaos_mesh_kind(
        experiment,
        definition: dict[str, Any] | None = None,
    ) -> str | None:
        # The planner has already loaded the canonical experiment
        # definition. Use it as the primary source of truth.
        if isinstance(definition, dict):
            chaos_mesh = definition.get(
                "chaos_mesh",
                {},
            )

            if isinstance(chaos_mesh, dict):
                kind = chaos_mesh.get("kind")

                if kind:
                    return str(kind)

        # Backward-compatible fallback for callers that do not
        # provide the already-loaded definition.
        json_file = getattr(experiment, "json_file", None)

        if not json_file:
            return None

        try:
            with open(json_file, "r", encoding="utf-8") as file:
                experiment_definition = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None

        chaos_mesh = experiment_definition.get(
            "chaos_mesh",
            {},
        )

        if not isinstance(chaos_mesh, dict):
            return None

        kind = chaos_mesh.get("kind")

        if not kind:
            return None

        return str(kind)

    @staticmethod
    def _default_region(
        definition: dict[str, Any],
    ) -> str | None:
        for item in definition.get("inputs", []):
            if item.get("name") == "aws_region":
                return item.get("default")

        return None

    def _resolve_targets(
        self,
        experiment,
        definition: dict[str, Any],
        discovery,
    ) -> list[dict[str, Any]]:
        variables = experiment.variables or {}

        resource_inputs = [
            item
            for item in definition.get("inputs", [])
            if item.get("type") == "aws_resource"
            and all(
                variables.get(condition, item.get("default", "")) == expected
                for condition, expected in item.get("visible_when", {}).items()
            )
        ]

        if not resource_inputs:
            return [
                {
                    "resource_type": "experiment",
                    "resource_id": experiment.id,
                    "name": experiment.name,
                }
            ]

        resolved = []

        for item in resource_inputs:
            resource_type = item.get("resource_type")
            variable_name = item.get("name")

            if not resource_type or not variable_name:
                continue

            requested = variables.get(variable_name)

            if requested in (None, ""):
                raise ValueError(
                    f"Required resource input "
                    f"'{variable_name}' was not supplied."
                )

            resources = self._discover_resources(
                resource_type,
                variables,
                item,
                discovery,
            )

            selected = self._match_selected_resources(
                resources,
                requested,
            )

            if not selected:
                raise ValueError(
                    f"Resource '{requested}' for input "
                    f"'{variable_name}' was not found."
                )

            for resource in selected:
                resolved.append(
                    self._build_target(
                        resource_type,
                        resource,
                    )
                )

        return self._deduplicate_targets(resolved)

    def _discover_resources(
        self,
        resource_type: str,
        variables: dict[str, Any],
        definition: dict[str, Any],
        discovery,
    ) -> list[dict[str, Any]]:
        parent = definition.get("parent")

        if resource_type == "eks-node":
            cluster_name = variables.get(parent or "eks_cluster")

            if not cluster_name:
                raise ValueError(
                    "EKS node target requires an EKS cluster."
                )

            return discovery.list_eks_nodes(cluster_name)

        if resource_type == "eks-namespace":
            cluster_name = variables.get(parent or "eks_cluster")

            if not cluster_name:
                raise ValueError(
                    "EKS namespace target requires an EKS cluster."
                )

            return discovery.list_eks_namespaces(cluster_name)

        if resource_type == "eks-deployment":
            namespace_value = variables.get(parent or "namespace")

            if not namespace_value:
                raise ValueError(
                    "EKS deployment target requires a namespace."
                )

            cluster_name = variables.get("eks_cluster")

            if not cluster_name:
                raise ValueError(
                    "EKS deployment target requires an EKS cluster."
                )

            return discovery.list_eks_deployments(
                cluster_name,
                namespace_value,
            )

        if resource_type == "eks-pod":
            namespace_value = variables.get(parent or "namespace")

            if not namespace_value:
                raise ValueError(
                    "EKS pod target requires a namespace."
                )

            cluster_name = variables.get("eks_cluster")

            if not cluster_name:
                raise ValueError(
                    "EKS pod target requires an EKS cluster."
                )

            return discovery.list_eks_pods(
                cluster_name,
                namespace_value,
            )

        resources = discovery.discover(resource_type)

        if resources is None:
            return []

        return resources

    @staticmethod
    def _match_selected_resources(
        resources: list[dict[str, Any]],
        requested: Any,
    ) -> list[dict[str, Any]]:
        if not resources:
            return []

        if isinstance(requested, str):
            requested_values = {
                value.strip()
                for value in requested.split(",")
                if value.strip()
            }
        elif isinstance(requested, (list, tuple, set)):
            requested_values = {
                str(value)
                for value in requested
            }
        else:
            requested_values = {str(requested)}

        selected = []

        for resource in resources:
            candidates = {
                str(resource.get("id", "")),
                str(resource.get("arn", "")),
                str(resource.get("name", "")),
            }

            if candidates & requested_values:
                selected.append(resource)

        return selected

    @staticmethod
    def _build_target(
        resource_type: str,
        resource: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "resource_type": resource_type,
            "resource_id": (
                resource.get("id")
                or resource.get("arn")
                or resource.get("name")
            ),
            "name": resource.get("name"),
            "details": resource,
        }

    @staticmethod
    def _deduplicate_targets(
        targets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique = []
        seen = set()

        for target in targets:
            key = (
                target.get("resource_type"),
                target.get("resource_id"),
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(target)

        return unique

    @staticmethod
    def _add_permissions(
        definition: dict[str, Any],
        result: PlanResult,
    ) -> None:
        iam = definition.get("iam", {})

        for access_type in ("read", "modify", "delete"):
            for action in iam.get(access_type, []):
                result.permissions.append(
                    {
                        "action": action,
                        "access": access_type,
                        "status": "REQUIRED",
                    }
                )

    @staticmethod
    def _add_capabilities(
        experiment,
        result: PlanResult,
    ) -> None:
        engine = getattr(
            experiment,
            "engine",
            None,
        )

        if engine:
            result.capabilities.append(
                {
                    "type": "execution_engine",
                    "name": engine,
                    "status": "REQUIRED",
                }
            )

    @staticmethod
    def _add_recovery(
        definition: dict[str, Any],
        experiment,
        result: PlanResult,
    ) -> None:
        recovery = definition.get("recovery")

        if recovery:
            result.recovery["behavior"] = recovery
            result.recovery["details"].append(
                {
                    "experiment_id": experiment.id,
                    "recovery": recovery,
                }
            )
            return

        experiment_json = definition.get("json")

        if experiment_json:
            experiment_path = os.path.join(
                "experiments",
                experiment.service,
                experiment_json,
            )

            try:
                with open(
                    experiment_path,
                    "r",
                    encoding="utf-8",
                ) as file:
                    experiment_definition = json.load(file)
            except (OSError, json.JSONDecodeError):
                experiment_definition = {}
        else:
            experiment_definition = {}

        recovery = experiment_definition.get("recovery")

        if recovery:
            result.recovery["behavior"] = recovery
            result.recovery["details"].append(
                {
                    "experiment_id": experiment.id,
                    "recovery": recovery,
                }
            )
            return

        rollbacks = experiment_definition.get("rollbacks", [])

        if rollbacks:
            rollback_names = [
                rollback.get("name")
                for rollback in rollbacks
                if rollback.get("name")
            ]

            result.recovery["behavior"] = (
                "Experiment rollback actions"
            )

            result.recovery["details"].append(
                {
                    "experiment_id": experiment.id,
                    "rollback_actions": rollback_names,
                }
            )
            return

        result.recovery["details"].append(
            {
                "experiment_id": experiment.id,
                "recovery": (
                    "Provider/framework recovery behavior."
                ),
            }
        )

    @staticmethod
    def _finalize_campaign_impact(
        result: PlanResult,
    ) -> None:
        total_targets = len(result.targets)

        by_service = Counter(
            target.get("service")
            for target in result.targets
            if target.get("service")
        )

        result.impact["capacity"] = {
            "selected_resources": total_targets,
            "basis": "resolved_resource_count",
            "affected_percent": None,
            "status": (
                "CALCULABLE"
                if total_targets
                else "UNKNOWN"
            ),
            "by_service": dict(by_service),
            "note": (
                "Affected percentage requires a known total "
                "service capacity and is not inferred from "
                "resource count."
            ),
        }

        result.impact["availability_zones"] = sorted(
            {
                target["details"].get("availability_zone")
                for target in result.targets
                if target.get("details", {}).get(
                    "availability_zone"
                )
            }
        )

    @staticmethod
    def _finalize_duration(
        result: PlanResult,
    ) -> None:
        durations = []

        for experiment in result.experiments:
            variables = experiment.get("variables", {})

            for key in (
                "wait_seconds",
                "duration",
                "duration_seconds",
                "duration_in_seconds",
                "timeout",
            ):
                value = variables.get(key)

                if value is None:
                    continue

                try:
                    durations.append(
                        duration_seconds(value)
                        if is_iso8601_duration(value)
                        else float(value)
                    )
                except (TypeError, ValueError):
                    continue

                break

        if durations:
            result.duration = {
                "estimated_seconds": sum(durations),
                "status": (
                    "ESTIMATED_FROM_EXPERIMENT_INPUTS"
                ),
            }
        else:
            result.duration = {
                "estimated_seconds": None,
                "status": "UNKNOWN",
            }
