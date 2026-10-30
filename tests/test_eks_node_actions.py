from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions import (
    drain_eks_node,
    wait_for_duration,
)


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.drain_nodes"
)
def test_drain_eks_node(mock_drain_nodes):
    mock_drain_nodes.return_value = ["node-1"]

    assert drain_eks_node("node-1", delete_pods_with_local_storage=True, timeout="60") == ["node-1"]
    mock_drain_nodes.assert_called_once_with(
        name="node-1",
        delete_pods_with_local_storage=True,
        timeout=60,
    )


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.drain_nodes",
    side_effect=TypeError("'NoneType' object is not iterable"),
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions._unmanaged_pods",
    return_value=[],
)
def test_drain_eks_node_reports_unmanaged_pod(mock_unmanaged_pods, mock_drain_nodes):
    with pytest.raises(RuntimeError, match="unmanaged pod"):
        drain_eks_node("node-1")

    mock_drain_nodes.assert_called_once()
    mock_unmanaged_pods.assert_called_once_with("node-1")


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.drain_nodes",
    side_effect=TypeError("'NoneType' object is not iterable"),
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions._unmanaged_pods",
    return_value=["sample-app/unmanaged-job"],
)
def test_drain_eks_node_names_the_blocking_unmanaged_pod(mock_unmanaged_pods, mock_drain_nodes):
    with pytest.raises(RuntimeError, match=r"Blocking pod\(s\): sample-app/unmanaged-job"):
        drain_eks_node("node-1")

    mock_drain_nodes.assert_called_once()
    mock_unmanaged_pods.assert_called_once_with("node-1")


def test_unmanaged_pods_excludes_mirror_terminal_and_controller_owned_pods(monkeypatch):
    api = MagicMock()
    api.list_pod_for_all_namespaces.return_value.items = [
        SimpleNamespace(
            metadata=SimpleNamespace(name="mirror", namespace="kube-system", annotations={"kubernetes.io/config.mirror": "hash"}, owner_references=[]),
            status=SimpleNamespace(phase="Running"),
        ),
        SimpleNamespace(
            metadata=SimpleNamespace(name="completed", namespace="apps", annotations={}, owner_references=[]),
            status=SimpleNamespace(phase="Succeeded"),
        ),
        SimpleNamespace(
            metadata=SimpleNamespace(name="deployment", namespace="apps", annotations={}, owner_references=[SimpleNamespace(controller=True)]),
            status=SimpleNamespace(phase="Running"),
        ),
        SimpleNamespace(
            metadata=SimpleNamespace(name="standalone", namespace="apps", annotations={}, owner_references=None),
            status=SimpleNamespace(phase="Running"),
        ),
    ]
    kubernetes = SimpleNamespace(client=SimpleNamespace(CoreV1Api=MagicMock(return_value=api)))
    monkeypatch.setitem(__import__("sys").modules, "kubernetes", kubernetes)

    from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions import (
        _unmanaged_pods,
    )

    assert _unmanaged_pods("node-1") == ["apps/standalone"]
    api.list_pod_for_all_namespaces.assert_called_once_with(field_selector="spec.nodeName=node-1")


def test_unmanaged_pods_returns_no_diagnostics_when_kubernetes_is_unavailable(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "kubernetes", None)

    from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions import (
        _unmanaged_pods,
    )

    assert _unmanaged_pods("node-1") == []


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.drain_nodes",
    side_effect=TypeError("unexpected type"),
)
def test_drain_eks_node_preserves_unrelated_type_error(mock_drain_nodes):
    with pytest.raises(TypeError, match="unexpected type"):
        drain_eks_node("node-1")

    mock_drain_nodes.assert_called_once()


@pytest.mark.parametrize("node_name", ["", None])
def test_drain_eks_node_requires_node_name(node_name):
    with pytest.raises(ValueError, match="EKS node name is required"):
        drain_eks_node(node_name)

# ----------------------------------------------------------
# Positive duration
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.time.sleep"
)
def test_wait_for_duration(
    mock_sleep,
):

    wait_for_duration(30)

    mock_sleep.assert_called_once_with(30)


# ----------------------------------------------------------
# String duration is converted to integer
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.time.sleep"
)
def test_wait_for_duration_converts_string(
    mock_sleep,
):

    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15)


# ----------------------------------------------------------
# Zero duration
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.time.sleep"
)
def test_wait_for_duration_zero(
    mock_sleep,
):

    wait_for_duration(0)

    mock_sleep.assert_not_called()


# ----------------------------------------------------------
# Negative duration
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_actions.time.sleep"
)
def test_wait_for_duration_negative(
    mock_sleep,
):

    wait_for_duration(-10)

    mock_sleep.assert_not_called()


# ----------------------------------------------------------
# Invalid duration
# ----------------------------------------------------------


def test_wait_for_duration_invalid():

    with pytest.raises(ValueError):
        wait_for_duration("invalid")
