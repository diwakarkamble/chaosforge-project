from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChaosMeshTarget:
    """
    Target selector used by a Chaos Mesh experiment.
    """

    namespace: str | None = None
    label_selector: dict[str, str] = field(default_factory=dict)
    pod_selector: dict[str, Any] = field(default_factory=dict)
    node_selector: dict[str, str] = field(default_factory=dict)


@dataclass
class ChaosMeshExperiment:
    """
    Generic internal representation of a Chaos Mesh CRD.

    The model deliberately keeps spec payload flexible because different
    Chaos Mesh CRDs have different schemas.
    """

    kind: str
    name: str
    namespace: str = "default"
    api_version: str = "chaos-mesh.org/v1alpha1"
    spec: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        """
        Convert the internal model into a Kubernetes manifest.
        """

        metadata: dict[str, Any] = {
            "name": self.name,
            "namespace": self.namespace,
        }

        if self.labels:
            metadata["labels"] = dict(self.labels)

        if self.annotations:
            metadata["annotations"] = dict(self.annotations)

        return {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": metadata,
            "spec": dict(self.spec),
        }


@dataclass
class ChaosMeshWorkflow:
    """
    Internal representation of a Chaos Mesh Workflow.
    """

    name: str
    namespace: str = "default"
    entry: str | None = None
    templates: list[dict[str, Any]] = field(default_factory=list)
    schedule: str | None = None

    def to_manifest(self) -> dict[str, Any]:
        """
        Convert the workflow into a Kubernetes manifest.
        """

        spec: dict[str, Any] = {
            "entry": self.entry,
            "templates": list(self.templates),
        }

        if self.schedule:
            spec["schedule"] = self.schedule

        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "Workflow",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
            },
            "spec": spec,
        }


@dataclass
class ChaosMeshExecutionResult:
    """
    Normalized result returned by the Chaos Mesh execution layer.
    """

    success: bool
    resource_kind: str
    resource_name: str
    namespace: str
    phase: str | None = None
    message: str | None = None
    resource: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    cleanup: dict[str, Any] = field(default_factory=dict)
