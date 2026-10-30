"""
ChaosForge EKS Node Actions
"""

import time

from chaosk8s.node.actions import drain_nodes


def _unmanaged_pods(node_name):
    """Return evictable pod identities that lack a Kubernetes controller."""
    try:
        from kubernetes import client

        pods = client.CoreV1Api().list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name}"
        ).items
    except Exception:  # noqa: BLE001 - retain the drain failure when diagnostics are unavailable.
        return []

    unmanaged = []
    for pod in pods:
        metadata = getattr(pod, "metadata", None)
        annotations = getattr(metadata, "annotations", None) or {}
        if "kubernetes.io/config.mirror" in annotations:
            continue
        status = getattr(getattr(pod, "status", None), "phase", None)
        if status in {"Succeeded", "Failed"}:
            continue
        owners = getattr(metadata, "owner_references", None) or []
        if not any(getattr(owner, "controller", False) for owner in owners):
            unmanaged.append(f"{getattr(metadata, 'namespace', 'default')}/{metadata.name}")
    return unmanaged


def drain_eks_node(
    node_name,
    delete_pods_with_local_storage=False,
    timeout=120,
):
    """Drain one EKS node and report unmanaged pods safely."""

    if not node_name:
        raise ValueError("EKS node name is required.")

    try:
        return drain_nodes(
            name=node_name,
            delete_pods_with_local_storage=delete_pods_with_local_storage,
            timeout=int(timeout),
        )
    except TypeError as exc:
        if "NoneType" not in str(exc) or "iterable" not in str(exc):
            raise
        unmanaged = _unmanaged_pods(node_name)
        pod_detail = f" Blocking pod(s): {', '.join(unmanaged)}." if unmanaged else ""
        raise RuntimeError(
            f"Cannot drain EKS node '{node_name}' because it hosts an unmanaged pod. "
            "Remove or assign an owning controller to that pod before retrying."
            + pod_detail
        ) from exc


def wait_for_duration(wait_seconds):
    """
    Keep the EKS chaos state active for the configured duration.
    """

    seconds = int(wait_seconds)

    if seconds <= 0:
        return

    time.sleep(seconds)
