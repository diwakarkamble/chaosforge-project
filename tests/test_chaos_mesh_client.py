from unittest.mock import MagicMock

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_client import ChaosMeshClient


def test_create_uses_chaos_mesh_custom_object_api():
    api = MagicMock()
    api.create_namespaced_custom_object.return_value = {
        "metadata": {
            "name": "pod-kill-test",
        }
    }

    client = ChaosMeshClient(custom_objects_api=api)

    manifest = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": "PodChaos",
        "metadata": {
            "name": "pod-kill-test",
            "namespace": "default",
        },
        "spec": {
            "action": "pod-kill",
            "mode": "one",
        },
    }

    result = client.create(manifest)

    assert result["metadata"]["name"] == "pod-kill-test"

    api.create_namespaced_custom_object.assert_called_once_with(
        group="chaos-mesh.org",
        version="v1alpha1",
        namespace="default",
        plural="podchaos",
        body=manifest,
    )


def test_get_resource():
    api = MagicMock()

    expected = {
        "kind": "NetworkChaos",
        "metadata": {
            "name": "network-delay",
        },
    }

    api.get_namespaced_custom_object.return_value = expected

    client = ChaosMeshClient(custom_objects_api=api)

    result = client.get(
        kind="NetworkChaos",
        name="network-delay",
        namespace="chaos-testing",
    )

    assert result == expected

    api.get_namespaced_custom_object.assert_called_once_with(
        group="chaos-mesh.org",
        version="v1alpha1",
        namespace="chaos-testing",
        plural="networkchaos",
        name="network-delay",
    )


def test_delete_resource():
    api = MagicMock()
    api.delete_namespaced_custom_object.return_value = {
        "status": "Success"
    }

    client = ChaosMeshClient(custom_objects_api=api)

    result = client.delete(
        kind="PodChaos",
        name="pod-kill",
        namespace="default",
    )

    assert result["status"] == "Success"

    api.delete_namespaced_custom_object.assert_called_once()


def test_list_resources():
    api = MagicMock()
    api.list_namespaced_custom_object.return_value = {
        "items": []
    }

    client = ChaosMeshClient(custom_objects_api=api)

    result = client.list(
        kind="StressChaos",
        namespace="chaos-testing",
    )

    assert result["items"] == []

    api.list_namespaced_custom_object.assert_called_once_with(
        group="chaos-mesh.org",
        version="v1alpha1",
        namespace="chaos-testing",
        plural="stresschaos",
    )


def test_wait_for_predicate():
    api = MagicMock()

    api.get_namespaced_custom_object.side_effect = [
        {
            "status": {
                "phase": "Running",
            }
        },
        {
            "status": {
                "phase": "Finished",
            }
        },
    ]

    client = ChaosMeshClient(custom_objects_api=api)

    result = client.wait_for(
        kind="PodChaos",
        name="pod-kill",
        predicate=lambda resource: (
            resource.get("status", {}).get("phase") == "Finished"
        ),
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert result["status"]["phase"] == "Finished"
    assert api.get_namespaced_custom_object.call_count == 2


def test_kind_to_plural():
    assert ChaosMeshClient._kind_to_plural("PodChaos") == "podchaos"
    assert ChaosMeshClient._kind_to_plural("NetworkChaos") == "networkchaos"
    assert ChaosMeshClient._kind_to_plural("StressChaos") == "stresschaos"
    assert ChaosMeshClient._kind_to_plural("Workflow") == "workflows"
    assert ChaosMeshClient._kind_to_plural("Schedule") == "schedules"


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unsupported Chaos Mesh kind"):
        ChaosMeshClient._kind_to_plural("UnknownChaos")
