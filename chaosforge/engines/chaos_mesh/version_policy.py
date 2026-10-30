"""Campaign-scoped Chaos Mesh version assessment and execution policy."""

from __future__ import annotations

from dataclasses import dataclass

from chaosforge.engines.chaos_mesh.chaos_mesh_installer import CHAOS_MESH_VERSION

AKS_WITHOUT_CHAOS_MESH = {
    "aks-node-drain",
    "aks-node-taint",
    "aks-node-cpu-stress",
    "aks-node-memory-pressure",
    "aks-node-notready",
    "aks-node-zone-failure",
}


@dataclass(frozen=True)
class ChaosMeshVersionAssessment:
    key: str
    cluster: str
    region: str
    state: str
    installed_version: str | None
    target_version: str = CHAOS_MESH_VERSION
    message: str = ""

    @property
    def requires_decision(self):
        return self.state in {"absent", "older"}

    @property
    def blocked(self):
        return self.state in {"incompatible", "error"}

    @property
    def choices(self):
        if self.state == "absent":
            return ("install", "cancel")
        if self.state == "older":
            return ("upgrade", "continue", "cancel")
        return ()

    def as_dict(self):
        return {
            "key": self.key,
            "cluster": self.cluster,
            "region": self.region,
            "state": self.state,
            "installed_version": self.installed_version,
            "target_version": self.target_version,
            "message": self.message,
            "requires_decision": self.requires_decision,
            "blocked": self.blocked,
            "choices": list(self.choices),
        }


def cluster_key(region, cluster):
    return f"{region or ''}:{cluster}"


def compare_versions(installed, target=CHAOS_MESH_VERSION):
    installed_parts = _version_parts(installed)
    target_parts = _version_parts(target)
    if installed_parts[:2] != target_parts[:2]:
        return "incompatible"
    if installed_parts == target_parts:
        return "current"
    return "older" if installed_parts < target_parts else "newer"


def assess_installer(installer, region, cluster):
    key = cluster_key(region, cluster)
    info = installer.release_info()
    if info.status.value == "ABSENT":
        return ChaosMeshVersionAssessment(
            key, cluster, region, "absent", None,
            message=f"Chaos Mesh is not installed. Install {CHAOS_MESH_VERSION} before execution.",
        )
    if info.status.value == "ERROR":
        return ChaosMeshVersionAssessment(
            key, cluster, region, "error", None, message=info.message
        )
    if not info.version:
        return ChaosMeshVersionAssessment(
            key, cluster, region, "error", None,
            message="The installed Chaos Mesh Helm chart version could not be determined.",
        )
    state = compare_versions(info.version)
    messages = {
        "current": f"Chaos Mesh {info.version} matches ChaosForge.",
        "older": f"Chaos Mesh {info.version} is installed; ChaosForge is validated against {CHAOS_MESH_VERSION}.",
        "newer": f"Chaos Mesh {info.version} is newer than the validated {CHAOS_MESH_VERSION}; it will not be downgraded.",
        "incompatible": f"Chaos Mesh {info.version} is outside the supported 2.8.x line validated by ChaosForge.",
    }
    return ChaosMeshVersionAssessment(
        key, cluster, region, state, info.version, message=messages[state]
    )


def chaos_mesh_targets(campaign):
    targets = {}
    for experiment in getattr(campaign, "experiments", []):
        variables = getattr(experiment, "variables", {}) or {}
        if getattr(experiment, "engine", "") == "Chaos Mesh":
            cluster = variables.get("eks_cluster")
            region = variables.get("aws_region", "")
            key = cluster_key(region, cluster) if cluster else None
            target = {
                "key": key, "region": region, "cluster": cluster,
                "kubeconfig_path": None, "kube_context": None,
                "release_name": "chaos-mesh", "namespace": "chaos-mesh",
                "configure_eks": True,
            }
        elif (
            getattr(experiment, "service", "") == "aks"
            and getattr(experiment, "id", "") not in AKS_WITHOUT_CHAOS_MESH
        ):
            cluster = variables.get("aks_context")
            key = f"azure:{cluster}" if cluster else None
            target = {
                "key": key, "region": "azure", "cluster": cluster,
                "kubeconfig_path": None, "kube_context": cluster,
                "release_name": "chaos-mesh-studio", "namespace": "chaos-testing",
                "configure_eks": False,
            }
        else:
            continue
        if not cluster:
            continue
        targets.setdefault(key, target)
    return targets


def assess_campaign(campaign, discovery_factory=None, installer_factory=None):
    if discovery_factory is None:
        from chaosforge.providers.aws.discovery import AWSDiscovery

        discovery_factory = AWSDiscovery
    if installer_factory is None:
        from chaosforge.engines.chaos_mesh.chaos_mesh_installer import ChaosMeshInstaller

        installer_factory = ChaosMeshInstaller
    assessments = []
    for target in chaos_mesh_targets(campaign).values():
        if target["configure_eks"]:
            discovery = discovery_factory(target["region"] or None)
            discovery._configure_eks_kubernetes_client(target["cluster"])
            target["kubeconfig_path"] = getattr(discovery, "eks_kubeconfig_path", None)
            target["kube_context"] = getattr(discovery, "eks_kube_context", None)
        installer = installer_factory(
            kubeconfig_path=target["kubeconfig_path"],
            kube_context=target["kube_context"],
            release_name=target["release_name"],
            namespace=target["namespace"],
        )
        assessment = assess_installer(
            installer, target["region"], target["cluster"]
        )
        if assessment.key != target["key"]:
            assessment = ChaosMeshVersionAssessment(
                target["key"], assessment.cluster, assessment.region,
                assessment.state, assessment.installed_version,
                assessment.target_version, assessment.message,
            )
        assessments.append(assessment)
    return assessments


def apply_execution_actions(campaign, assessments, decisions):
    assessment_by_key = {item.key: item for item in assessments}
    for experiment in getattr(campaign, "experiments", []):
        variables = getattr(experiment, "variables", {}) or {}
        if getattr(experiment, "engine", "") == "Chaos Mesh":
            key = cluster_key(
                variables.get("aws_region", ""), variables.get("eks_cluster", "")
            )
        elif (
            getattr(experiment, "service", "") == "aks"
            and getattr(experiment, "id", "") not in AKS_WITHOUT_CHAOS_MESH
        ):
            key = f"azure:{variables.get('aks_context', '')}"
        else:
            continue
        assessment = assessment_by_key.get(key)
        if assessment is None:
            continue
        action = execution_action(assessment, decisions)
        if action is None or action == "cancel":
            raise ValueError(f"A Chaos Mesh version decision is required for {assessment.cluster}.")
        experiment.chaos_mesh_version_action = action
        experiment.chaos_mesh_installed_version = assessment.installed_version


def saved_decision(action, assessment):
    return {
        "action": action,
        "installed_version": assessment.installed_version,
        "target_version": assessment.target_version,
    }


def decision_is_current(decision, assessment):
    return bool(
        decision
        and decision.get("action") in assessment.choices
        and decision.get("installed_version") == assessment.installed_version
        and decision.get("target_version") == assessment.target_version
    )


def execution_action(assessment, decisions):
    if assessment.state == "current":
        return "continue"
    if assessment.state == "newer":
        return "continue"
    decision = (decisions or {}).get(assessment.key)
    if decision_is_current(decision, assessment):
        return decision["action"]
    return None


def _version_parts(value):
    text = str(value or "").strip().lstrip("v")
    parts = text.split(".")
    if len(parts) < 2:
        raise ValueError(f"Invalid Chaos Mesh version: {value}")
    try:
        numbers = tuple(int(part.split("-", 1)[0]) for part in parts[:3])
    except ValueError:
        raise ValueError(f"Invalid Chaos Mesh version: {value}") from None
    return numbers + (0,) * (3 - len(numbers))
