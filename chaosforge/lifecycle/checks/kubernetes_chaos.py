"""Shared Kubernetes validation profiles for equivalent AKS and EKS faults."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from chaosforge.application.duration import duration_seconds, is_iso8601_duration
from chaosforge.lifecycle.checks.base import ExperimentCheck

EKS_TO_AKS_EXPERIMENT = {
    "fis-eks-pod-delete": "aks-pod-kill",
    "chaos-mesh-pod-failure": "aks-pod-failure",
    "chaos-mesh-pod-kill": "aks-pod-kill",
    "chaos-mesh-container-kill": "aks-container-kill",
    "chaos-mesh-network-delay": "aks-network-delay",
    "chaos-mesh-network-loss": "aks-packet-loss",
    "chaos-mesh-network-duplicate": "aks-packet-duplication",
    "chaos-mesh-network-corrupt": "aks-packet-corruption",
    "chaos-mesh-network-partition": "aks-network-partition",
    "chaos-mesh-network-bandwidth": "aks-bandwidth-limit",
    "chaos-mesh-cpu-stress": "aks-cpu-stress",
    "chaos-mesh-memory-stress": "aks-memory-stress",
    "chaos-mesh-dns-error": "aks-dns-failure",
    "chaos-mesh-http-abort": "aks-http-abort",
    "chaos-mesh-http-delay": "aks-http-delay",
    "chaos-mesh-io-latency": "aks-io-latency",
    "chaos-mesh-io-fault": "aks-io-errors",
}

KUBE_SYSTEM_EXPERIMENTS = frozenset(
    {"aks-coredns-kill", "aks-coredns-cpu", "aks-kube-proxy-kill"}
)


def _duration_seconds(value) -> int:
    """Return seconds from direct Chaos Mesh's portable duration input."""
    if is_iso8601_duration(value):
        return duration_seconds(value)
    text = str(value or "").strip().lower()
    if text.isdigit():
        return int(text)
    if text.endswith("s") and text[:-1].isdigit():
        return int(text[:-1])
    return 0


def build_pre_validation_checks(**kwargs):
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.safety import (
        build_steady_state_checks,
    )

    return build_steady_state_checks(**kwargs)


def run_pre_validation(*args, **kwargs):
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.safety import (
        run_parallel_steady_state,
    )

    return run_parallel_steady_state(*args, **kwargs)


def observe_fault(*args, **kwargs):
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.safety import (
        verify_fault_active,
    )

    return verify_fault_active(*args, **kwargs)


def build_post_validation_checks(*args, **kwargs):
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.safety import (
        build_post_experiment_checks,
    )

    return build_post_experiment_checks(*args, **kwargs)


def build_cluster_plane_post_validation_checks(*args, **kwargs):
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
        build_cluster_plane_chaos_post_checks,
    )

    return build_cluster_plane_chaos_post_checks(*args, **kwargs)


def equivalent_aks_experiment(experiment_id: str, variables=None) -> str | None:
    if experiment_id == "chaos-mesh-time":
        offset = str((variables or {}).get("time_offset") or "+5m")
        return "aks-clock-skew-backward" if offset.startswith("-") else "aks-clock-skew-forward"
    if experiment_id.startswith("aks-"):
        return experiment_id
    return EKS_TO_AKS_EXPERIMENT.get(experiment_id)


ADVISORY_CHECKS = frozenset(
    {
        "cert-manager ACME Issuer Domain (Advisory)",
        "cert-manager Certificate Expiry Window",
        "Node Time Sync (NTP/Chrony)",
        "DNS Pattern Blast Radius",
        "CPU Requests & Limits",
        "CPU Baseline (current usage)",
        "CPU Headroom (node)",
        "Memory Requests & Limits",
        "Memory Baseline (current usage)",
        "Memory Headroom (node)",
        "Probe Timeouts vs Delay (impact analysis)",
        "Probe Timeouts vs Packet Loss (impact analysis)",
        "Baseline HTTP Response Time",
        "Baseline Ping RTT",
        "Baseline DNS Resolution",
        "Baseline DNS Resolution (UDP)",
        "Pod Restart Baseline",
        "TCP Retransmit Baseline (/proc/net/snmp)",
        "Baseline Packet Loss % (pre-fault)",
        "Node Topology Note (test vs non-prod)",
        "CoreDNS CPU Limits Set (Advisory)",
        "Cluster-Wide Canary Baseline",
        "IOChaos Sidecar Injected on Pod (Advisory)",
        "IOChaos Namespace Inject Label",
        # Post-validation observations that document recovery risk but do not
        # prove that the fault or its cleanup remains active.
        "Pod Events (last 5m)",
        "Probe Failures Stopped (post)",
        "Circuit Breaker / DestinationRule (Advisory)",
        "No OOMKilled (post)",
        "Throughput Restored (KB/s)",
    }
)


def run_validation_checks(
    checks: dict[str, Callable[[], tuple[bool, str]]],
    *,
    session=None,
    phase="validation",
) -> dict[str, Any]:
    if session is not None:
        raw_results = session.run_checks(
            checks,
            phase=phase,
            advisory_labels=ADVISORY_CHECKS,
        )
        results = {
            label: {
                "id": label.lower().replace(" ", "_").replace("/", "_"),
                "label": label,
                "passed": bool(result["passed"]),
                "severity": "ADVISORY" if label in ADVISORY_CHECKS else "BLOCKING",
                "detail": str(result["detail"]),
                "elapsed_seconds": result["elapsed"],
                "error": result.get("error"),
            }
            for label, result in raw_results.items()
        }
    else:
        results = {}
        for label, check in checks.items():
            started = time.monotonic()
            try:
                passed, detail = check()
                error = None
            except Exception as exc:  # Provider checks must be represented in evidence.
                passed, detail, error = False, f"Unexpected: {exc}", str(exc)
            severity = "ADVISORY" if label in ADVISORY_CHECKS else "BLOCKING"
            results[label] = {
                "id": label.lower().replace(" ", "_").replace("/", "_"),
                "label": label,
                "passed": bool(passed),
                "severity": severity,
                "detail": str(detail),
                "elapsed_seconds": time.monotonic() - started,
                "error": error,
            }
    warnings = [
        result
        for result in results.values()
        if not result["passed"] and result["severity"] == "ADVISORY"
    ]
    blocking_failures = [
        result
        for result in results.values()
        if not result["passed"] and result["severity"] == "BLOCKING"
    ]
    return {
        # Provider safety checks explicitly classify diagnostic observations as
        # advisory. Preserve their failed evidence without blocking lifecycle
        # execution before a fault can be applied.
        "passed": not blocking_failures,
        "checks": results,
        "warnings": warnings,
        "blocking_failures": blocking_failures,
    }


@dataclass
class KubernetesValidationContext:
    kube_context: str
    cluster: str
    namespace: str
    workload: str = ""
    pod: str = ""
    container: str = ""
    label_key: str = ""
    label_value: str = ""
    fault_kind: str = ""
    mode: str = "one"
    duration: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


class SharedChaosMeshValidationCheck(ExperimentCheck):
    """Run the existing Kubernetes checks for equivalent AKS and EKS faults."""

    name = "shared-kubernetes-chaos-validation"
    recovery_supported = False

    def __init__(self, discovery, experiment):
        self.discovery = discovery
        self.experiment = experiment
        self.validation_id = equivalent_aks_experiment(
            experiment.id, getattr(experiment, "variables", {})
        )
        self.runtime_validation = {
            "available": self.validation_id is not None,
            "passed": False,
            "fault_observed": False,
            "samples": [],
        }
        self.validation_session = None

    def _context(self, target) -> KubernetesValidationContext:
        cluster = str(target.get("eks_cluster") or target.get("aks_context") or "")
        configure = getattr(self.discovery, "_configure_eks_kubernetes_client", None)
        if target.get("eks_cluster") and configure:
            configure(cluster)
        kube_context = str(
            target.get("aks_context")
            or getattr(self.discovery, "eks_kube_context", None)
            or cluster
        )
        labels = target.get("labels") or {}
        label_key, label_value = next(iter(labels.items()), ("", ""))
        pod_mode = str(target.get("target_mode") or "") == "pod"
        pod = str(target.get("pod") or (target.get("deployment") if pod_mode else "") or "")
        owning_deployment = str(target.get("owning_deployment") or "")
        namespace = (
            "kube-system"
            if self.validation_id in KUBE_SYSTEM_EXPERIMENTS
            else str(target.get("namespace") or "default")
        )
        return KubernetesValidationContext(
            kube_context=kube_context,
            cluster=cluster,
            namespace=namespace,
            workload=owning_deployment or ("" if pod_mode else str(target.get("deployment") or "")),
            pod=pod,
            container=str(target.get("container_name") or ""),
            label_key=str(target.get("label_key") or label_key),
            label_value=str(target.get("label_val") or label_value),
            fault_kind=str(self.validation_id or ""),
            mode=str(target.get("mode") or "one"),
            duration=str(target.get("duration") or ""),
            parameters=dict(target),
        )

    @staticmethod
    def _builder_arguments(context):
        parameters = context.parameters
        return {
            "aks_context": context.kube_context,
            "namespace": context.namespace,
            "deployment": context.workload,
            "label_key": context.label_key,
            "label_val": context.label_value,
            "experiment_id": context.fault_kind,
            "container_name": context.container,
            "dns_pattern": parameters.get("patterns") or parameters.get("dns_pattern", ""),
            "time_offset": parameters.get("time_offset", "+5m"),
            "http_port": str(parameters.get("port", parameters.get("http_port", "80"))),
            "injected_delay": parameters.get("delay", parameters.get("latency", "5s")),
            "target_mode": "pod" if context.pod else context.mode,
            "exact_pod_name": context.pod,
            "volume_path": parameters.get("volume_path", parameters.get("path", "/data")),
        }

    def capture(self, target):
        if self.validation_id is None:
            return {"validation_available": False}
        context = self._context(target)
        if target.get("eks_cluster"):
            from chaosforge.providers.azure.components.aks.experiments.chaos_studio.validation_logger import (
                ValidationSession,
            )

            self.validation_session = ValidationSession(self.experiment.id)
            self.validation_session.start()
        result = run_validation_checks(
            build_pre_validation_checks(**self._builder_arguments(context)),
            session=self.validation_session,
            phase="pre-check",
        )
        result["validation_available"] = True
        result["validation_experiment_id"] = self.validation_id
        if not result["passed"]:
            failed = [name for name, item in result["checks"].items() if not item["passed"]]
            if self.validation_session is not None:
                self.validation_session.stop()
                self.validation_session = None
            raise RuntimeError("Kubernetes pre-checks failed: " + ", ".join(failed))
        return result

    def observe_during(self, target, manifest, resource):
        context = self._context(target)
        observation = observe_fault(
            self.validation_id,
            context.kube_context,
            context.namespace,
            context.workload,
            label_key=context.label_key,
            label_val=context.label_value,
            exact_pod_name=context.pod,
        )
        if not isinstance(observation, dict):
            observation = {"severity": "WARNING", "message": str(observation or "No observation")}
        pod_deleted = (
            self.validation_id == "aks-pod-kill"
            and bool(target.get("eks_cluster"))
            and not self.discovery.eks_pod_exists(
                context.cluster, context.namespace, context.pod
            )
        )
        observed = pod_deleted or observation.get("severity") == "CHAOS" or any(
            condition.get("type") == "AllInjected" and condition.get("status") == "True"
            for condition in resource.get("status", {}).get("conditions", [])
        )
        sample = {"resource_phase": resource.get("status", {}).get("phase"), **observation}
        if pod_deleted:
            sample["pod_deleted"] = True
        self.runtime_validation["samples"].append(sample)
        self.runtime_validation["fault_observed"] |= observed
        self.runtime_validation["passed"] = self.runtime_validation["fault_observed"]
        return sample

    def validate(self, target, baseline):
        context = self._context(target)
        try:
            if self.validation_id in KUBE_SYSTEM_EXPERIMENTS:
                checks = build_cluster_plane_post_validation_checks(
                    context.kube_context,
                    self.validation_id,
                )
            else:
                arguments = self._builder_arguments(context)
                checks = build_post_validation_checks(
                    arguments.pop("experiment_id"),
                    arguments["aks_context"],
                    arguments["namespace"],
                    arguments["deployment"],
                    label_key=arguments["label_key"],
                    label_val=arguments["label_val"],
                    dns_pattern=arguments["dns_pattern"],
                    target_mode=arguments["target_mode"],
                    exact_pod_name=arguments["exact_pod_name"],
                    volume_path=arguments["volume_path"],
                    recovery_wait_seconds=(
                        _duration_seconds(target.get("duration"))
                        if target.get("eks_cluster")
                        else 0
                    ),
                    recovery_retry_count=5,
                    recovery_retry_interval_seconds=50,
                )
            result = run_validation_checks(
                checks,
                session=self.validation_session,
                phase="post-check",
            )
        finally:
            if self.validation_session is not None:
                self.validation_session.stop()
                self.validation_session = None
        failed = [name for name, item in result["checks"].items() if not item["passed"]]
        result["display"] = {
            "Expected": "All post-experiment checks pass",
            "Observed": (
                "All post-experiment checks passed"
                if not failed
                else "Failed: " + ", ".join(failed)
            ),
        }
        result["validation_experiment_id"] = self.validation_id
        return result

    def build_execution_display(self, target):
        expected_fault = (
            self.experiment.name
            if target.get("eks_cluster") and getattr(self.experiment, "name", "")
            else self.validation_id
        )
        return {
            "Expected": f"{expected_fault} fault observed",
            "Observed": (
                "Fault observed"
                if self.runtime_validation["fault_observed"]
                else "Fault not observed"
            ),
        }
