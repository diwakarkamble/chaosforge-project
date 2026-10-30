import time
from typing import Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException


class ChaosMeshClient:
    """
    Kubernetes API client for Chaos Mesh CRDs.

    This class is responsible only for Kubernetes/CRD operations.
    ChaosForge experiment semantics remain outside this client.
    """

    API_GROUP = "chaos-mesh.org"
    API_VERSION = "v1alpha1"

    def __init__(
        self,
        custom_objects_api=None,
        api_client=None,
    ):
        self._api_client = api_client
        self.custom_objects_api = custom_objects_api

    def _load_client(self):
        """
        Load Kubernetes configuration and create the CustomObjects API.
        """

        if self.custom_objects_api is not None:
            return self.custom_objects_api

        if self._api_client is None:
            try:
                config.load_kube_config()
            except ConfigException:
                config.load_incluster_config()

            self._api_client = client.ApiClient()

        self.custom_objects_api = client.CustomObjectsApi(
            self._api_client
        )

        return self.custom_objects_api

    def create(
        self,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create a Chaos Mesh custom resource.
        """

        api = self._load_client()

        metadata = manifest.get("metadata", {})
        namespace = metadata.get("namespace", "default")
        plural = self._kind_to_plural(manifest["kind"])

        return api.create_namespaced_custom_object(
            group=self.API_GROUP,
            version=self.API_VERSION,
            namespace=namespace,
            plural=plural,
            body=manifest,
        )

    def get(
        self,
        kind: str,
        name: str,
        namespace: str = "default",
    ) -> dict[str, Any]:
        """
        Get a Chaos Mesh custom resource.
        """

        api = self._load_client()

        return api.get_namespaced_custom_object(
            group=self.API_GROUP,
            version=self.API_VERSION,
            namespace=namespace,
            plural=self._kind_to_plural(kind),
            name=name,
        )

    def delete(
        self,
        kind: str,
        name: str,
        namespace: str = "default",
    ) -> dict[str, Any]:
        """
        Delete a Chaos Mesh custom resource.
        """

        api = self._load_client()

        return api.delete_namespaced_custom_object(
            group=self.API_GROUP,
            version=self.API_VERSION,
            namespace=namespace,
            plural=self._kind_to_plural(kind),
            name=name,
            body=client.V1DeleteOptions(),
        )

    def list(
        self,
        kind: str,
        namespace: str = "default",
    ) -> dict[str, Any]:
        """
        List Chaos Mesh custom resources in a namespace.
        """

        api = self._load_client()

        return api.list_namespaced_custom_object(
            group=self.API_GROUP,
            version=self.API_VERSION,
            namespace=namespace,
            plural=self._kind_to_plural(kind),
        )

    def wait_for(
        self,
        kind: str,
        name: str,
        namespace: str = "default",
        predicate=None,
        on_poll=None,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any]:
        """
        Wait for a Chaos Mesh resource to satisfy a predicate.

        If no predicate is supplied, the current resource is returned
        as soon as it can be read.

        Raises:
            TimeoutError: If the resource does not satisfy the predicate
                before the timeout expires.
        """

        deadline = time.monotonic() + timeout_seconds

        last_error = None

        while time.monotonic() < deadline:
            try:
                resource = self.get(
                    kind=kind,
                    name=name,
                    namespace=namespace,
                )

                if on_poll is not None:
                    on_poll(resource)

                if predicate is None or predicate(resource):
                    return resource

            except ApiException as exc:
                last_error = exc

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                break

            time.sleep(
                min(
                    poll_interval_seconds,
                    remaining,
                )
            )

        message = (
            f"Timed out waiting for Chaos Mesh resource "
            f"{kind}/{namespace}/{name}."
        )

        if last_error is not None:
            message += f" Last API error: {last_error}"

        raise TimeoutError(message)

    def wait_for_deleted(
        self,
        kind: str,
        name: str,
        namespace: str = "default",
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        """
        Wait until a Chaos Mesh custom resource is confirmed deleted.

        Kubernetes DELETE can return successfully while the object is still
        terminating because of finalizers. A 404 confirms that the resource
        is actually gone.
        """

        deadline = time.monotonic() + timeout_seconds
        last_error = None

        while time.monotonic() < deadline:
            try:
                self.get(
                    kind=kind,
                    name=name,
                    namespace=namespace,
                )

            except ApiException as exc:
                if exc.status == 404:
                    return

                last_error = exc

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                break

            time.sleep(
                min(
                    poll_interval_seconds,
                    remaining,
                )
            )

        message = (
            f"Timed out waiting for Chaos Mesh resource "
            f"{kind}/{namespace}/{name} to be deleted."
        )

        if last_error is not None:
            message += f" Last API error: {last_error}"

        raise TimeoutError(message)


    @staticmethod
    def _kind_to_plural(kind: str) -> str:
        mapping = {
            "PodChaos": "podchaos",
            "NetworkChaos": "networkchaos",
            "DNSChaos": "dnschaos",
            "HTTPChaos": "httpchaos",
            "StressChaos": "stresschaos",
            "IOChaos": "iochaos",
            "TimeChaos": "timechaos",
            "KernelChaos": "kernelchaos",
            "AWSChaos": "awschaos",
            "JVMChaos": "jvmchaos",
            "BlockChaos": "blockchaos",
            "PhysicalMachineChaos": "physicalmachinechaos",
            "Workflow": "workflows",
            "Schedule": "schedules",
            "StatusCheck": "statuschecks",
        }

        try:
            return mapping[kind]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported Chaos Mesh kind: {kind}"
            ) from exc
