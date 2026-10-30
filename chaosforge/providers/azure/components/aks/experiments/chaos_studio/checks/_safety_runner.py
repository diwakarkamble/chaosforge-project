"""Steady-state check runner, kept independent from safety.py globals."""

import warnings


def run_parallel_steady_state(
    aks_context: str,
    namespace: str = "",
    deployment: str = "",
    label_key: str = "",
    label_val: str = "",
    *,
    phase: str = "validation",
    session=None,
    experiment_id: str = "",
    container_name: str = "",
    dns_pattern: str = "",
    time_offset: str = "+5m",
    http_port: str = "80",
    injected_delay: str = "5s",
    target_mode: str = "",
    exact_pod_name: str = "",
    volume_path: str = "/data",
    build_checks,
    validation_session,
) -> bool:
    """Run steady-state checks with dependencies supplied by the public wrapper."""
    checks = build_checks(
        aks_context, namespace, deployment, label_key, label_val,
        experiment_id=experiment_id, container_name=container_name,
        dns_pattern=dns_pattern, time_offset=time_offset,
        http_port=http_port, injected_delay=injected_delay,
        target_mode=target_mode, exact_pod_name=exact_pod_name,
        volume_path=volume_path,
    )
    warn_only = {
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
    }

    if session is not None:
        results = session.run_checks(checks, phase=phase, print_live=True,
                                     advisory_labels=warn_only)
    else:
        temporary_session = validation_session(f"inline-{phase}")
        temporary_session.start()
        try:
            results = temporary_session.run_checks(
                checks, phase=phase, print_live=True, advisory_labels=warn_only
            )
        finally:
            temporary_session.stop()

    hard_failures = [
        f"  • {label}: {result['detail']}"
        for label, result in results.items()
        if not result.get("passed") and label not in warn_only
    ]
    warn_failures = [
        label for label, result in results.items()
        if not result.get("passed") and label in warn_only
    ]
    if warn_failures:
        warnings.warn(f"Pre-check advisory (non-blocking): {', '.join(warn_failures)}")
    if hard_failures:
        raise RuntimeError(
            f"Steady-state checks failed ({phase}):\n" + "\n".join(hard_failures)
        )
    return True
