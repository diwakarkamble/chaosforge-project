"""Read-only permission reports derived from campaign and catalog metadata."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from chaosforge.application.iam import iam_actions
from chaosforge.catalog import ExperimentCatalog
from chaosforge.providers.azure.chaos_studio.classic_faults import CLASSIC_FAULTS


class PermissionReportService:
    """Build cloud-neutral permission reports without inspecting or changing cloud state."""

    def __init__(self, catalog: ExperimentCatalog | None = None):
        self.catalog = catalog or ExperimentCatalog()

    def generate(self, campaign: Any) -> dict[str, Any]:
        """Return the permissions implied by a campaign's selected experiments."""
        provider = str(getattr(campaign, "cloud_provider", "aws")).lower()
        if provider == "azure":
            return self._azure_report(campaign)
        return self._aws_report(campaign)

    report = generate

    def render_json(self, campaign: Any, *, indent: int = 2) -> str:
        """Render a machine-readable report."""
        return json.dumps(self.generate(campaign), indent=indent, sort_keys=True)

    def render_markdown(self, campaign: Any) -> str:
        """Render a copy-friendly Markdown report."""
        report = self.generate(campaign)
        if report["provider"] == "aws":
            lines = ["# AWS Required Permissions"]
            lines.extend(self._render_aws_section(
                "ChaosForge Runtime Identity",
                "AWS identity running ChaosForge", report["iam"].get("runtime", []),
            ))
            lines.extend(self._render_aws_section(
                "AWS FIS Execution Role",
                "Role assumed by AWS FIS", report["iam"].get("fis_execution", []),
            ))
        else:
            lines = ["# Azure Required Permissions"]
            lines.extend(self._render_azure_section(
                "Chaos Studio Identity", "chaosforge-managed-identity ($CHAOS_STUDIO_UAMI_PRINCIPAL_ID)",
                report["rbac"]["chaos_studio_uami"],
            ))
            lines.extend(self._render_azure_section(
                "ChaosForge Runtime Identity", "DefaultAzureCredential identity running ChaosForge ($RUNTIME_PRINCIPAL_ID)",
                report["rbac"]["runtime"],
            ))
            if report["rbac"]["bootstrap"]:
                lines.extend(self._render_azure_section(
                    "Optional: First-Time Chaos Studio Identity Setup",
                    "Administrator or automation identity ($BOOTSTRAP_PRINCIPAL_ID)",
                    report["rbac"]["bootstrap"],
                ))
        if len(lines) == 1:
            lines.extend(["", "No modeled permission requirements."])
        if report["warnings"]:
            lines.extend(["", "## Warnings", *[f"- {warning}" for warning in report["warnings"]]])
        return "\n".join(lines)

    @staticmethod
    def _render_provenance(requirement):
        names = [experiment["name"] for experiment in requirement.get("experiments", [])]
        return ["Required by: " + ", ".join(names)] if names else []

    def _render_aws_section(self, title, identity, requirements):
        if not requirements:
            return []
        lines = ["", f"## {title}", identity]
        for requirement in requirements:
            lines.extend(["", f"### {requirement['label']}", f"Scope: `{requirement['scope']}`"])
            lines.extend(self._render_provenance(requirement))
            if requirement["actions"]:
                lines.extend(["", "```json", json.dumps(requirement["policy"], indent=2), "```"])
            if requirement.get("trust_policy"):
                lines.extend(["", "FIS trust policy:", "", "```json", json.dumps(requirement["trust_policy"], indent=2), "```"])
            if requirement.get("note"):
                lines.extend(["", f"Note: {requirement['note']}"])
        return lines

    def _render_azure_section(self, title, identity, requirements):
        if not requirements:
            return []
        lines = ["", f"## {title}", identity]
        for requirement in requirements:
            lines.extend(["", f"### {requirement['role']}", f"Scope: `{requirement['scope']}`"])
            lines.extend(self._render_provenance(requirement))
            commands = requirement.get("commands") or [requirement["command"]]
            for command in commands:
                lines.extend(["", "```sh", command, "```"])
        return lines

    def render_terminal(self, campaign: Any) -> str:
        """Render a plain-text terminal report; callers own terminal output."""
        return self.render_markdown(campaign)

    def _aws_report(self, campaign: Any) -> dict[str, Any]:
        actions_by_service: dict[str, set[str]] = defaultdict(set)
        requirements: dict[str, dict[tuple[str, str], list[dict[str, str]]]] = defaultdict(dict)
        warnings: list[str] = []
        for experiment in campaign.experiments:
            metadata = self.catalog.get_experiment(experiment.service, experiment.id)
            if metadata is None:
                warnings.append(f"No catalog metadata found for {experiment.service}/{experiment.id}.")
                continue
            actions = iam_actions(metadata)
            if actions:
                actions_by_service[experiment.service].update(actions)
            provenance = self._provenance(experiment)
            if experiment.service == "fis" and experiment.id == "fis-create-experiment":
                role_arn = str(experiment.variables.get("role_arn") or "<FIS_EXECUTION_ROLE_ARN>")
                self._add_aws_requirement(
                    requirements, "runtime", "AWS FIS control plane", "*",
                    [action for action in actions if action != "iam:PassRole"], provenance, resource="*",
                )
                self._add_aws_requirement(
                    requirements, "runtime", "Pass the FIS execution role", role_arn,
                    ["iam:PassRole"], provenance, resource=role_arn,
                )
                fis_service = str(experiment.variables.get("service_id") or "")
                fis_action = str(experiment.variables.get("experiment_id") or "")
                self._add_aws_requirement(
                    requirements, "fis_execution", "AWS FIS execution role", role_arn,
                    self._fis_actions(fis_service, fis_action), provenance,
                    note=self._fis_note(fis_service, fis_action, experiment.variables),
                    resource=str(experiment.variables.get("target_arn") or "*"),
                )
                continue
            if actions:
                self._add_aws_requirement(
                    requirements, "runtime", "ChaosForge runtime identity", "*", actions, provenance,
                    resource="*",
                )
        statements = []
        for service, actions in sorted(actions_by_service.items()):
            statements.append({"Sid": f"{self._sid(service)}Permissions", "Effect": "Allow", "Action": sorted(actions), "Resource": "*"})
            warnings.append(f"{service}: catalog IAM metadata has no resource-scoped mapping; Resource is '*'.")
        return {
            "provider": "aws",
            "policy": {"Version": "2012-10-17", "Statement": statements},
            "iam": {section: self._aws_requirements(values) for section, values in requirements.items()},
            "warnings": warnings,
        }

    @staticmethod
    def _provenance(experiment):
        return {
            "service": experiment.service,
            "id": experiment.id,
            "name": experiment.name,
            "reversibility": getattr(experiment, "reversibility", "reversible"),
        }

    @staticmethod
    def _add_aws_requirement(requirements, section, label, scope, actions, provenance, note="", resource="*"):
        key = (label, scope)
        item = requirements[section].setdefault(
            key, {"actions": set(), "experiments": [], "notes": [], "resources": set()}
        )
        item["actions"].update(actions)
        item["resources"].add(resource)
        if provenance not in item["experiments"]:
            item["experiments"].append(provenance)
        if note and note not in item["notes"]:
            item["notes"].append(note)

    @staticmethod
    def _aws_requirements(values):
        return [
            {
                "label": label,
                "scope": scope,
                "actions": sorted(value["actions"]),
                "experiments": value["experiments"],
                "note": "\n".join(value["notes"]),
                "policy": {
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Action": sorted(value["actions"]),
                        "Resource": sorted(value["resources"]),
                    }],
                } if value["actions"] else None,
                "trust_policy": {
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"Service": "fis.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }],
                } if label == "AWS FIS execution role" else None,
            }
            for (label, scope), value in sorted(values.items())
        ]

    @staticmethod
    def _fis_actions(service, action):
        actions = {
            ("ec2", "stop-instances"): ["ec2:DescribeInstances", "ec2:StartInstances", "ec2:StopInstances"],
            ("ec2", "reboot-instances"): ["ec2:DescribeInstances", "ec2:RebootInstances"],
            ("ec2", "terminate-instances"): ["ec2:DescribeInstances", "ec2:TerminateInstances"],
            ("s3", "pause-replication"): ["s3:PauseReplication", "s3:ResumeReplication"],
            ("lambda", "invocation-delay"): ["lambda:InvokeFunction"],
            ("lambda", "invocation-error"): ["lambda:InvokeFunction"],
            ("lambda", "http-response"): ["lambda:InvokeFunction"],
        }
        return actions.get((service, action), [])

    @staticmethod
    def _fis_note(service, action, variables):
        if service == "lambda" and action in {"invocation-delay", "invocation-error", "http-response"}:
            bucket = variables.get("fis_config_bucket", "<FIS_CONFIGURATION_BUCKET>")
            return f"Lambda FIS also requires s3:PutObject and s3:DeleteObject on arn:aws:s3:::{bucket}/FisConfigs/*"
        if service == "s3" and action == "pause-replication":
            return "AWS FIS requires the S3 replication permissions documented for aws:s3:bucket-pause-replication."
        return ""

    def _azure_report(self, campaign: Any) -> dict[str, Any]:
        roles: dict[str, dict[tuple[str, str], list[dict[str, str]]]] = defaultdict(dict)
        warnings: list[str] = []
        for experiment in campaign.experiments:
            metadata = self.catalog.get_experiment(experiment.service, experiment.id)
            if metadata is None:
                warnings.append(f"No catalog metadata found for {experiment.service}/{experiment.id}.")
                continue
            scope = self._scope(experiment)
            key = (experiment.service, experiment.id)
            if key in CLASSIC_FAULTS or key == ("azure_redis", "azure-redis-reboot"):
                role = (
                    CLASSIC_FAULTS[key][2]
                    if key in CLASSIC_FAULTS
                    else "Redis Cache Contributor"
                )
                self._add_requirement(roles, "chaos_studio_uami", role, scope, experiment)
                self._add_requirement(roles, "bootstrap", "Owner or User Access Administrator", scope, experiment)
                self._add_requirement(
                    roles, "bootstrap", "Managed Identity Contributor",
                    self._resource_group_scope(experiment), experiment,
                )
            elif experiment.service == "aks":
                subscription_scope = self._subscription_scope(experiment)
                self._add_requirement(roles, "runtime", "Contributor", subscription_scope, experiment)
                warnings.append("AKS experiments require conservative Contributor access at subscription scope; narrow this after validating the cluster and managed-resource scopes.")
            elif metadata.get("engine") in {"Azure SDK", "Chaos Toolkit"}:
                self._add_requirement(roles, "runtime", "Contributor", scope, experiment)
        plan = {section: self._requirements(section, values) for section, values in roles.items()}
        for section in ("runtime", "chaos_studio_uami", "bootstrap"):
            plan.setdefault(section, [])
        return {"provider": "azure", "rbac": plan, "warnings": sorted(set(warnings))}

    @staticmethod
    def _scope(experiment: Any) -> str:
        return str(getattr(experiment, "variables", {}).get("resource_id") or "$RESOURCE_ID")

    @staticmethod
    def _subscription_scope(experiment: Any) -> str:
        variables = getattr(experiment, "variables", {})
        subscription_id = variables.get("subscription_id")
        if subscription_id:
            return f"/subscriptions/{subscription_id}"
        resource_id = str(variables.get("resource_id") or "")
        parts = resource_id.strip("/").split("/")
        if len(parts) > 1 and parts[0].lower() == "subscriptions":
            return f"/subscriptions/{parts[1]}"
        return "/subscriptions/$SUBSCRIPTION_ID"

    @staticmethod
    def _resource_group_scope(experiment: Any) -> str:
        variables = getattr(experiment, "variables", {})
        resource_id = str(variables.get("resource_id") or "")
        parts = resource_id.strip("/").split("/")
        try:
            group_index = next(
                index
                for index, part in enumerate(parts)
                if part.lower() == "resourcegroups"
            )
            return "/" + "/".join(parts[: group_index + 2])
        except StopIteration:
            subscription_scope = PermissionReportService._subscription_scope(experiment)
            return f"{subscription_scope}/resourceGroups/$IDENTITY_RESOURCE_GROUP"

    @staticmethod
    def _add_requirement(roles, section, role, scope, experiment):
        entry = {
            "service": experiment.service,
            "id": experiment.id,
            "name": experiment.name,
            "reversibility": getattr(experiment, "reversibility", "reversible"),
        }
        experiments = roles[section].setdefault((role, scope), [])
        if entry not in experiments:
            experiments.append(entry)

    @staticmethod
    def _requirements(section: str, values: dict[tuple[str, str], list[dict[str, str]]]) -> list[dict[str, Any]]:
        principal = "$RUNTIME_PRINCIPAL_ID" if section == "runtime" else "$CHAOS_STUDIO_UAMI_PRINCIPAL_ID" if section == "chaos_studio_uami" else "$BOOTSTRAP_PRINCIPAL_ID"
        requirements = []
        for (role, scope), experiments in sorted(values.items()):
            if role == "Owner or User Access Administrator":
                alternatives = ["User Access Administrator", "Owner"]
                requirements.append(
                    {
                        "role": " or ".join(alternatives),
                        "alternatives": alternatives,
                        "scope": scope,
                        "principal_id": principal,
                        "principal_type": "ServicePrincipal",
                        "experiments": experiments,
                        "commands": [
                            f"az role assignment create --assignee-object-id {principal} "
                            "--assignee-principal-type ServicePrincipal "
                            f"--role '{alternative}' --scope {scope}"
                            for alternative in alternatives
                        ],
                    }
                )
                continue
            requirements.append(
                {
                    "role": role,
                    "scope": scope,
                    "principal_id": principal,
                    "principal_type": "ServicePrincipal",
                    "experiments": experiments,
                    "command": f"az role assignment create --assignee-object-id {principal} --assignee-principal-type ServicePrincipal --role '{role}' --scope {scope}",
                }
            )
        return requirements

    @staticmethod
    def _sid(service: str) -> str:
        return "".join(part.capitalize() for part in service.replace("-", "_").split("_"))
