from unittest.mock import MagicMock

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_target_resolver import (
    ChaosMeshTargetResolver,
)


def make_discovery():
    discovery = MagicMock()

    discovery.list_eks_namespaces.return_value = [
        {
            "name": "production",
            "cluster": "demo",
        },
        {
            "name": "default",
            "cluster": "demo",
        },
    ]

    discovery.list_eks_deployments.return_value = [
        {
            "name": "orders",
            "namespace": "production",
            "cluster": "demo",
        }
    ]

    discovery.list_eks_pods.return_value = [
        {
            "name": "orders-abc123",
            "namespace": "production",
            "cluster": "demo",
        }
    ]

    discovery.list_eks_nodes.return_value = [
        {
            "name": "ip-10-0-1-10",
            "cluster": "demo",
        }
    ]

    return discovery


def test_resolve_namespace():
    resolver = ChaosMeshTargetResolver(
        make_discovery()
    )

    result = resolver.resolve_namespace(
        "demo",
        "production",
    )

    assert result == {
        "cluster": "demo",
        "namespace": "production",
    }


def test_resolve_deployment():
    resolver = ChaosMeshTargetResolver(
        make_discovery()
    )

    result = resolver.resolve_deployment(
        "demo",
        "production",
        "orders",
    )

    assert result["deployment"] == "orders"


def test_resolve_pod():
    resolver = ChaosMeshTargetResolver(
        make_discovery()
    )

    result = resolver.resolve_pod(
        "demo",
        "production",
        "orders-abc123",
    )

    assert result["pod"] == "orders-abc123"


def test_resolve_node():
    resolver = ChaosMeshTargetResolver(
        make_discovery()
    )

    result = resolver.resolve_node(
        "demo",
        "ip-10-0-1-10",
    )

    assert result["node"] == "ip-10-0-1-10"


def test_missing_namespace_fails():
    resolver = ChaosMeshTargetResolver(
        make_discovery()
    )

    with pytest.raises(LookupError):
        resolver.resolve_namespace(
            "demo",
            "missing",
        )


def test_missing_pod_fails():
    resolver = ChaosMeshTargetResolver(
        make_discovery()
    )

    with pytest.raises(LookupError):
        resolver.resolve_pod(
            "demo",
            "production",
            "missing",
        )


def test_pod_selector():
    selector = ChaosMeshTargetResolver.pod_selector(
        namespace="production",
        labels={"app": "orders"},
    )

    assert selector == {
        "namespaces": ["production"],
        "labelSelectors": {
            "app": "orders",
        },
    }


def test_node_selector():
    selector = ChaosMeshTargetResolver.node_selector(
        labels={"role": "worker"},
    )

    assert selector == {
        "labelSelectors": {
            "role": "worker",
        },
    }
