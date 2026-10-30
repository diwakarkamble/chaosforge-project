"""Turn an E2E manifest and command-line filters into independent test cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chaosforge.application.component_fis import bind_component_fis, fis_target_selector
from chaosforge.application.metadata_loader import load_metadata
from chaosforge.application.safety import reversibility
from chaosforge.providers.aws.fis.catalog import FISCatalog
from e2e.webui.functional.catalog import (
    EXPERIMENT_DEFAULTS,
    FUNCTIONAL_DEFAULTS,
    TAG_CATALOG,
    catalog_experiments,
    experiment_metadata,
    graph_resource_fields,
    graph_skip_reason,
    validate_tag_catalog,
)
from e2e.webui.functional.manifest import SUPPORTED_CLOUDS, SUPPORTED_MODES, ManifestError
from e2e.webui.functional.providers.azure import resolve_chaos_identity

E2E_COMPONENT_OWNER = {
    # Direct Chaos Mesh is exposed through the EKS UI component, while its
    # catalog service remains chaos_mesh for routing and form submission.
    "chaos_mesh": "eks",
}


@dataclass(frozen=True)
class FunctionalCase:
    cloud: str
    service: str
    experiment: str
    selector: str
    target_variable: str
    inputs: dict[str, Any]
    target: dict[str, Any]
    execute: bool
    skip_reason: str = ""
    resource_fields: tuple[dict[str, Any], ...] = ()

    @property
    def id(self) -> str:
        return f"{self.cloud}-{self.service}-{self.experiment}-{self.target['target_type']}"


@dataclass(frozen=True)
class CampaignGroup:
    cloud: str
    cases: tuple[FunctionalCase, ...]

    @property
    def id(self) -> str:
        return f"{self.cloud}-combined-{len(self.cases)}-experiments"


def parse_components(value: str) -> set[str] | None:
    names = {item.strip() for item in value.split(",") if item.strip()}
    return None if not names or names == {"all"} else names


def parse_tags(values: list[str]) -> dict[str, str]:
    tags = {}
    for value in values:
        key, separator, tag_value = value.partition("=")
        if not separator or not key.strip() or not tag_value.strip():
            raise ManifestError(f"E2E tag must use KEY=VALUE format: {value!r}")
        tags[key.strip()] = tag_value.strip()
    return tags


def parse_experiments(values: list[str]) -> dict[str, set[str]]:
    """Parse component-qualified experiment filters without cross-component ambiguity."""
    selected: dict[str, set[str]] = {}
    for value in values:
        for item in value.split(","):
            component, separator, experiment = item.strip().partition(":")
            if not separator or not component.strip() or not experiment.strip():
                raise ManifestError(
                    f"E2E experiment must use COMPONENT:EXPERIMENT format: {item!r}"
                )
            selected.setdefault(component.strip(), set()).add(experiment.strip())
    return selected


def plan_cases(
    manifest: dict[str, Any], *, cloud_filter: str = "all", component_filter: set[str] | None = None,
    mode_override: str | None = None, tag_override: dict[str, str] | None = None,
    execute_override: bool = False, aws_fis_role_arn: str = "",
) -> list[FunctionalCase]:
    if cloud_filter not in {*SUPPORTED_CLOUDS, "all"}:
        raise ManifestError(f"Unsupported E2E cloud filter {cloud_filter!r}.")
    if mode_override and mode_override not in SUPPORTED_MODES:
        raise ManifestError(f"Unsupported E2E mode {mode_override!r}.")
    defaults = manifest.get("defaults") or {}
    planned = []
    known = set()
    for cloud, services in manifest["components"].items():
        for service, config in services.items():
            known.add(service)
            if cloud_filter not in {"all", cloud} or (component_filter and service not in component_filter):
                continue
            mode = mode_override or config.get("mode") or defaults.get("mode", "tags")
            tags = tag_override or config.get("tags") or defaults.get("tags") or {}
            targets = _targets_for(config, mode, tags)
            for target in targets:
                target.update({
                    "cloud": cloud,
                    "service": service,
                    "selector": config["selector"],
                    "target_variable": config["target_variable"],
                    "region": config.get("region", ""),
                    "resource_type": config.get("resource_type", ""),
                    "subscription_id": config.get("subscription_id", ""),
                    "resource_group": config.get("resource_group", ""),
                })
                for experiment in config["experiments"]:
                    inputs = dict(config.get("inputs") or {})
                    metadata = experiment_metadata(service, str(experiment)) or {}
                    _apply_execution_role(
                        metadata.get("inputs", []), inputs, aws_fis_role_arn, service, str(experiment)
                    )
                    planned.append(FunctionalCase(
                        cloud, service, str(experiment), config["selector"], config["target_variable"],
                        inputs, target,
                        bool(execute_override or config.get("execute", defaults.get("execute", False))),
                    ))
    if component_filter:
        unsupported = component_filter - known
        if unsupported:
            raise ManifestError(f"E2E components are absent from manifest: {', '.join(sorted(unsupported))}")
    return planned


def plan_tag_cases(
    *, cloud_filter="all", component_filter=None, tags, aws_region, azure_chaos_identity,
    vm_shutdown_duration, vm_abrupt_shutdown, azure_subscription="", aws_fis_role_arn="", input_values=None, strict_inputs=False, execute_override=False,
    skip_irreversible=False, experiment_filter=None,
):
    if cloud_filter not in {*SUPPORTED_CLOUDS, "all"}:
        raise ManifestError(f"Unsupported E2E cloud filter {cloud_filter!r}.")
    if not tags:
        raise ManifestError("E2E tag mode requires at least one --e2e-tag KEY=VALUE option.")
    validate_tag_catalog()
    clouds = TAG_CATALOG if cloud_filter == "all" else {cloud_filter: TAG_CATALOG.get(cloud_filter, {})}
    experiment_filter = experiment_filter or {}
    selected_components = component_filter or {
        service for services in clouds.values() for service in services
    }
    unknown_components = {
        service
        for service in experiment_filter
        if E2E_COMPONENT_OWNER.get(service, service) not in selected_components
    }
    if unknown_components:
        raise ManifestError(
            "E2E experiment filters reference components excluded by --e2e-components: "
            + ", ".join(sorted(unknown_components))
        )
    identity = None
    cases = []
    input_values = input_values or {"defaults": {}, "components": {}}
    known = set()
    for cloud, services in clouds.items():
        planned_services = list(services.items())
        for service in experiment_filter:
            owner = E2E_COMPONENT_OWNER.get(service)
            if owner in services and service not in services:
                planned_services.append((service, services[owner]))
        for service, config in planned_services:
            known.add(service)
            owner = E2E_COMPONENT_OWNER.get(service, service)
            if component_filter and owner not in component_filter:
                continue
            if experiment_filter and service not in experiment_filter:
                continue
            if cloud == "aws" and not aws_region:
                raise ManifestError("E2E tag mode requires --e2e-aws-region when AWS components are selected.")
            target = {
                "cloud": cloud,
                "service": service,
                "target_type": "tags",
                "target": dict(tags),
                "region": aws_region if cloud == "aws" else "",
                "resource_type": config.get("resource_type", ""),
                "subscription_id": azure_subscription,
                "resource_group": "",
            }
            experiments = sorted(
                catalog_experiments(service, config),
                key=lambda item: reversibility(service, item["id"]) == "irreversible",
            )
            requested = experiment_filter.get(service)
            available = {item["id"] for item in experiments}
            fis_actions = _fis_actions(service, requested - available if requested else set())
            unsupported_fis = _unsupported_fis_actions(service, requested - available if requested else set())
            unavailable = requested - available - set(fis_actions) - set(unsupported_fis) if requested else set()
            if unavailable:
                raise ManifestError(
                    f"E2E experiment filters are not available for {service}: "
                    + ", ".join(sorted(unavailable))
                )
            if unsupported_fis:
                raise ManifestError(
                    f"E2E AWS FIS actions are not tag-resolvable for {service}: "
                    + ", ".join(sorted(unsupported_fis))
                )
            for experiment in experiments:
                if requested and experiment["id"] not in requested:
                    continue
                if skip_irreversible and reversibility(service, experiment["id"]) == "irreversible":
                    continue
                metadata = experiment_metadata(service, experiment["id"]) or experiment
                fields = metadata.get("inputs", [])
                resource_fields = graph_resource_fields(cloud, service, fields) or _configured_root_field(cloud, service, config)
                if service in E2E_COMPONENT_OWNER or service == "eks":
                    # Tags resolve the EKS cluster. Namespace/workload selectors
                    # must remain explicit E2E inputs, never inferred from tags.
                    resource_fields = resource_fields[:1]
                if not resource_fields:
                    # A tag-mode experiment needs a resolver-backed root; never let the UI choose one.
                    continue
                root = resource_fields[0]
                case_target = {
                    **target,
                    "resolver_service": owner,
                    "resource_type": root.get("resource_type", config.get("resource_type", "")),
                    "selector": f"#{root['name']}",
                    "target_variable": root["name"],
                    "resource_fields": resource_fields,
                }
                declared_fields = {field["name"] for field in fields if field.get("name")}
                inputs = {
                    **_metadata_defaults(fields),
                    **{name: value for name, value in FUNCTIONAL_DEFAULTS.items() if name in declared_fields},
                    **EXPERIMENT_DEFAULTS.get((service, experiment["id"]), {}),
                    **{name: value for name, value in input_values["defaults"].items() if name in declared_fields},
                    **_component_experiment_inputs(
                        input_values, service, owner, experiment["id"]
                    ),
                }
                case_target["resource_overrides"] = {
                    field["name"]: inputs[field["name"]]
                    for field in resource_fields
                    if field["name"] in inputs
                }
                if any(str(field.get("type", "")).endswith("_chaos_identity") for field in fields):
                    if identity is None:
                        identity = resolve_chaos_identity(azure_chaos_identity, azure_subscription)
                    identity_status, identity_id, identity_error = identity
                    if identity_status != "found":
                        raise ManifestError(
                            f"E2E tag mode requires one resolvable --e2e-azure-chaos-identity for "
                            f"{service}/{experiment['id']}. {identity_error}"
                        )
                    inputs["chaos_identity_id"] = identity_id
                if experiment["id"] == "azure-vm-shutdown":
                    inputs["duration"] = vm_shutdown_duration
                    inputs["abrupt_shutdown"] = vm_abrupt_shutdown
                _apply_execution_role(fields, inputs, aws_fis_role_arn, service, experiment["id"])
                missing = _missing_required_inputs(service, experiment["id"], inputs, resource_fields)
                skip_reason = graph_skip_reason(service)
                if service == "eks":
                    required_children = [
                        field["name"]
                        for field in fields
                        if field.get("parent") and field.get("required")
                    ]
                    missing_children = [name for name in required_children if not inputs.get(name)]
                    if missing_children:
                        message = (
                            "EKS tag-mode requires explicit Kubernetes inputs: "
                            + ", ".join(missing_children)
                        )
                        if strict_inputs:
                            raise ManifestError(f"{service}/{experiment['id']}: {message}")
                        skip_reason = message
                    else:
                        skip_reason = ""
                if missing:
                    message = (
                        f"required E2E inputs are missing and cannot be inferred: {', '.join(missing)}"
                    )
                    if strict_inputs:
                        raise ManifestError(f"{service}/{experiment['id']}: {message}")
                    skip_reason = "; ".join(filter(None, (skip_reason, message)))
                cases.append(FunctionalCase(
                    cloud,
                    service,
                    experiment["id"],
                    f"#{root['name']}",
                    root["name"],
                    inputs,
                    case_target,
                    execute_override,
                    skip_reason,
                    tuple(resource_fields),
                ))
            for action_id in fis_actions:
                cases.append(_plan_fis_case(
                    service, action_id, target, aws_fis_role_arn, input_values, execute_override
                ))
    cases.sort(key=_is_irreversible_case)
    if component_filter:
        unsupported = component_filter - known
        if unsupported:
            raise ManifestError(
                f"E2E tag-mode components are not in the safe catalog: {', '.join(sorted(unsupported))}"
            )
    if not cases:
        raise ManifestError("E2E tag-mode filters produced no supported component cases.")
    return cases


def _missing_required_inputs(service, experiment_id, values, resource_fields=()):
    metadata = experiment_metadata(service, experiment_id)
    if metadata is None:
        raise ManifestError(f"Built-in E2E catalog references unknown experiment {service}/{experiment_id}.")
    graph_names = {field["name"] for field in resource_fields}
    return [
        field["name"]
        for field in metadata.get("inputs", [])
        if field.get("required")
        and field.get("name") not in values
        and "default" not in field
        and field.get("name") not in graph_names
        and not _is_resource_field(field)
        and not str(field.get("type", "")).endswith("_chaos_identity")
    ]


def _resource_fields(cloud, fields):
    return [field for field in fields if _is_resource_field(field, cloud)]


def _is_resource_field(field, cloud=None):
    kind = field.get("type")
    if kind == "aws_resource":
        return cloud in {None, "aws"}
    if kind == "azure_component_resource" or str(kind).startswith("azure_") and kind != "azure_component_chaos_identity":
        return cloud in {None, "azure"}
    return False


def _configured_root_field(cloud, service, config):
    """Support explicit root fixtures while dynamic catalog entries require metadata."""
    if not config.get("selector") or not config.get("target_variable"):
        return []
    return [{
        "name": config["target_variable"],
        "type": "aws_resource" if cloud == "aws" else "azure_component_resource",
        "resource_type": service,
    }]


def _metadata_defaults(fields):
    return {field["name"]: field["default"] for field in fields if "default" in field}


def _component_experiment_inputs(input_values, service, owner, experiment_id):
    components = input_values["components"]
    return (
        components.get(service, {}).get("experiments", {}).get(experiment_id, {})
        or components.get(owner, {}).get("experiments", {}).get(experiment_id, {})
    )


def _fis_actions(service, requested):
    """Return explicitly selected component-bound AWS FIS actions only."""
    return sorted(
        [
        action for action in requested
        if (experiment := FISCatalog().get_experiment(service, action))
        and _fis_target_is_tag_resolvable(service, experiment)
        ],
        key=lambda action: reversibility("fis", "fis-create-experiment", {
            "service_id": service, "experiment_id": action,
        }) == "irreversible",
    )


def _is_irreversible_case(case):
    variables = case.inputs
    if case.service == "fis":
        variables = {
            "service_id": case.target["fis_service_id"],
            "experiment_id": case.target["fis_experiment_id"],
        }
    return reversibility(case.service, case.experiment, variables) == "irreversible"


def _unsupported_fis_actions(service, requested):
    return [
        action for action in requested
        if (experiment := FISCatalog().get_experiment(service, action))
        and not _fis_target_is_tag_resolvable(service, experiment)
    ]


def _fis_target_is_tag_resolvable(service, experiment):
    selector = fis_target_selector(service, experiment)
    return selector == service or (
        service == "elasticache" and selector == "elasticache-replication-group"
    )


def _plan_fis_case(service, action_id, target, aws_fis_role_arn, input_values, execute_override):
    metadata = bind_component_fis(load_metadata("fis")["experiments"][0], service, action_id)
    fields = metadata["inputs"]
    inputs = {
        **_metadata_defaults(fields),
        "experiment_name": f"ChaosForge E2E {service} {action_id}",
        "description": f"ChaosForge functional E2E {service}/{action_id}",
        **input_values["defaults"],
        **input_values["components"].get(service, {}).get("experiments", {}).get(action_id, {}),
    }
    _apply_execution_role(fields, inputs, aws_fis_role_arn, service, action_id)
    inputs.pop("created_by", None)
    case_target = {
        **target,
        "service": "fis",
        "resolver_service": service,
        "selector": "#target_arn",
        "target_variable": "target_arn",
        "fis_service_id": service,
        "fis_experiment_id": action_id,
    }
    return FunctionalCase(
        "aws", "fis", "fis-create-experiment", "#target_arn", "target_arn", inputs,
        case_target, execute_override,
    )


def _apply_execution_role(fields, values, aws_fis_role_arn, service, experiment_id):
    """Require an explicit AWS FIS role whenever the selected metadata needs one."""
    if not any(field.get("name") == "role_arn" and field.get("required") for field in fields):
        return
    if aws_fis_role_arn:
        values["role_arn"] = aws_fis_role_arn
    if not values.get("role_arn"):
        raise ManifestError(
            f"{service}/{experiment_id} requires an AWS FIS execution role. "
            "Provide --e2e-aws-fis-role-arn or configure role_arn in the selected E2E inputs."
        )


def group_cases_by_cloud(cases: list[FunctionalCase]) -> list[CampaignGroup]:
    grouped = {}
    for case in cases:
        grouped.setdefault(case.cloud, []).append(case)
    return [CampaignGroup(cloud, tuple(group)) for cloud, group in grouped.items()]


def _targets_for(config: dict[str, Any], mode: str, tags: dict[str, str]) -> list[dict[str, Any]]:
    if mode == "tags":
        if not tags:
            raise ManifestError("E2E tag mode requires at least one tag.")
        return [{"target_type": "tags", "target": tags}]
    targets = []
    for resource in config["resources"]:
        if not isinstance(resource, dict):
            raise ManifestError("E2E explicit resources must be objects.")
        for key in ("resource_id", "name"):
            if resource.get(key):
                targets.append({"target_type": key, "target": resource[key]})
                break
        else:
            raise ManifestError("E2E explicit resource requires name or resource_id.")
    return targets
