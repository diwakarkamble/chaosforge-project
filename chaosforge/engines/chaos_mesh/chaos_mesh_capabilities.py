from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChaosMeshCapability:
    """
    Describes one Chaos Mesh capability exposed by ChaosForge.
    """

    kind: str
    category: str
    description: str
    supports_duration: bool = True
    supports_selector: bool = True
    supports_namespace: bool = True
    supports_workflow: bool = True
    requires_controller_manager: bool = True
    requires_chaos_daemon: bool = True
    requires_kubernetes_api: bool = True
    requires_crd: bool = True
    notes: str | None = None


CHAOS_MESH_CAPABILITIES: dict[str, ChaosMeshCapability] = {
    "PodChaos": ChaosMeshCapability(
        kind="PodChaos",
        category="pod",
        description="Inject pod-level faults such as pod kill and pod failure.",
    ),
    "NetworkChaos": ChaosMeshCapability(
        kind="NetworkChaos",
        category="network",
        description="Inject network faults such as latency, loss, partition, duplicate, corrupt, and bandwidth constraints.",
    ),
    "DNSChaos": ChaosMeshCapability(
        kind="DNSChaos",
        category="network",
        description="Inject DNS faults such as DNS error and DNS random response.",
    ),
    "HTTPChaos": ChaosMeshCapability(
        kind="HTTPChaos",
        category="network",
        description="Inject HTTP-level faults such as abort, delay, replace, request header, and response manipulation.",
    ),
    "StressChaos": ChaosMeshCapability(
        kind="StressChaos",
        category="resource",
        description="Inject CPU and memory stress into selected workloads.",
    ),
    "IOChaos": ChaosMeshCapability(
        kind="IOChaos",
        category="io",
        description="Inject I/O faults such as latency, error, and attribute changes.",
    ),
    "TimeChaos": ChaosMeshCapability(
        kind="TimeChaos",
        category="system",
        description="Inject clock/time offset into selected processes or containers.",
    ),
    "KernelChaos": ChaosMeshCapability(
        kind="KernelChaos",
        category="system",
        description="Inject kernel-level faults into selected nodes.",
        supports_selector=True,
        notes="Requires appropriate Chaos Mesh privileges and kernel support.",
    ),
    "AWSChaos": ChaosMeshCapability(
        kind="AWSChaos",
        category="cloud",
        description="Inject supported AWS-specific faults through Chaos Mesh.",
        supports_selector=False,
        notes="Exact AWS actions depend on the Chaos Mesh AWSChaos specification and installed version.",
    ),
    "JVMChaos": ChaosMeshCapability(
        kind="JVMChaos",
        category="application",
        description="Inject faults into Java Virtual Machine applications.",
        notes="Requires applicable JVM instrumentation/agent support.",
    ),
    "BlockChaos": ChaosMeshCapability(
        kind="BlockChaos",
        category="storage",
        description="Inject block-level storage faults.",
        supports_selector=True,
        notes="Availability depends on the Chaos Mesh deployment and target environment.",
    ),
    "PhysicalMachineChaos": ChaosMeshCapability(
        kind="PhysicalMachineChaos",
        category="machine",
        description="Inject faults against physical machine targets.",
        supports_namespace=False,
        notes="Not normally applicable to standard EKS pod workloads.",
    ),
    "Workflow": ChaosMeshCapability(
        kind="Workflow",
        category="orchestration",
        description="Compose multiple Chaos Mesh actions into serial, parallel, and conditional workflows.",
        supports_duration=False,
        supports_selector=False,
        supports_workflow=False,
        requires_chaos_daemon=False,
    ),
    "Schedule": ChaosMeshCapability(
        kind="Schedule",
        category="orchestration",
        description="Schedule Chaos Mesh experiments for recurring or future execution.",
        supports_duration=False,
        supports_selector=False,
        supports_workflow=False,
        requires_chaos_daemon=False,
    ),
    "StatusCheck": ChaosMeshCapability(
        kind="StatusCheck",
        category="validation",
        description="Check workload or resource status as part of Chaos Mesh workflows.",
        supports_duration=False,
        supports_selector=False,
        supports_workflow=True,
        requires_chaos_daemon=False,
    ),
}


def get_chaos_mesh_capability(kind: str) -> ChaosMeshCapability | None:
    """
    Return a capability definition by Chaos Mesh kind.
    """

    return CHAOS_MESH_CAPABILITIES.get(kind)


def list_chaos_mesh_capabilities() -> list[ChaosMeshCapability]:
    """
    Return all registered Chaos Mesh capabilities.
    """

    return list(CHAOS_MESH_CAPABILITIES.values())


def is_supported_chaos_mesh_kind(kind: str) -> bool:
    """
    Return whether ChaosForge has registered the supplied Chaos Mesh kind.
    """

    return kind in CHAOS_MESH_CAPABILITIES


def capability_summary() -> list[dict[str, Any]]:
    """
    Return a JSON-friendly capability summary.
    """

    return [
        {
            "kind": capability.kind,
            "category": capability.category,
            "description": capability.description,
            "supports_duration": capability.supports_duration,
            "supports_selector": capability.supports_selector,
            "supports_namespace": capability.supports_namespace,
            "supports_workflow": capability.supports_workflow,
            "requires_controller_manager": capability.requires_controller_manager,
            "requires_chaos_daemon": capability.requires_chaos_daemon,
            "requires_kubernetes_api": capability.requires_kubernetes_api,
            "requires_crd": capability.requires_crd,
            "notes": capability.notes,
        }
        for capability in CHAOS_MESH_CAPABILITIES.values()
    ]
