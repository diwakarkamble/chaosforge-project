"""
ChaosForge EKS Replica Reduction Actions

Custom actions for temporarily reducing the replica count
of a Kubernetes deployment and restoring the original count.
"""

import json
import os
import time

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

STATE_FILE = os.path.join(
    os.environ.get("TEMP", "/tmp"),
    "chaosforge_eks_replica.json",
)


def _load_kubernetes():
    """
    Load the Kubernetes configuration.

    Uses the local kubeconfig/context configured for the EKS cluster.
    """

    try:
        config.load_kube_config()
    except ConfigException:
        config.load_incluster_config()


def _get_apps_api():
    """
    Return the Kubernetes AppsV1Api client.
    """

    _load_kubernetes()
    return client.AppsV1Api()


def capture_current_replicas(
    deployment_name,
    namespace="default",
):
    """
    Capture the current replica count of the deployment.

    The value is stored in a temporary state file so that
    rollback can restore the exact original replica count.
    """

    api = _get_apps_api()

    deployment = api.read_namespaced_deployment(
        name=deployment_name,
        namespace=namespace,
    )

    original_replicas = deployment.spec.replicas

    if original_replicas is None:
        original_replicas = 0

    state = {
        "deployment_name": deployment_name,
        "namespace": namespace,
        "original_replicas": int(original_replicas),
    }

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file)

    return int(original_replicas)


def reduce_replicas(
    deployment_name,
    namespace="default",
    reduced_replicas=1,
):
    """
    Reduce the deployment to the requested replica count.
    """

    replicas = int(reduced_replicas)

    if replicas < 0:
        raise ValueError("Replica count cannot be negative.")

    api = _get_apps_api()

    body = {
        "spec": {
            "replicas": replicas,
        }
    }

    api.patch_namespaced_deployment_scale(
        name=deployment_name,
        namespace=namespace,
        body=body,
    )

    return f"Deployment {deployment_name} scaled to {replicas} replica(s)."


def restore_original_replicas(
    deployment_name,
    namespace="default",
):
    """
    Restore the replica count captured before the chaos action.
    """

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError(f"State file not found: {STATE_FILE}")

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)

    original_replicas = int(state["original_replicas"])

    api = _get_apps_api()

    body = {
        "spec": {
            "replicas": original_replicas,
        }
    }

    api.patch_namespaced_deployment_scale(
        name=deployment_name,
        namespace=namespace,
        body=body,
    )

    try:
        os.remove(STATE_FILE)
    except OSError:
        pass

    return f"Deployment {deployment_name} restored to {original_replicas} replica(s)."


def wait_for_duration(wait_seconds):
    """
    Keep the chaos active for the configured duration.
    """

    seconds = int(wait_seconds)

    if seconds <= 0:
        return

    time.sleep(seconds)
