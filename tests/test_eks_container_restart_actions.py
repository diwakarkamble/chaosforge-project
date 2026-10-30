from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_container_restart_actions import (
    restart_eks_container,
)

# ----------------------------------------------------------
# Successful restart
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_container_restart_actions.terminate_pods"
)
def test_restart_eks_container(
    mock_terminate_pods,
):

    mock_terminate_pods.return_value = "restart-result"

    result = restart_eks_container(
        pod_name="my-pod",
        namespace="production",
        grace_period=30,
    )

    assert result == "restart-result"

    mock_terminate_pods.assert_called_once_with(
        name_pattern="my-pod",
        ns="production",
        qty=1,
        mode="fixed",
        rand=False,
        grace_period=30,
    )


# ----------------------------------------------------------
# Default namespace
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_container_restart_actions.terminate_pods"
)
def test_restart_eks_container_default_namespace(
    mock_terminate_pods,
):

    restart_eks_container(
        pod_name="my-pod",
    )

    mock_terminate_pods.assert_called_once_with(
        name_pattern="my-pod",
        ns="default",
        qty=1,
        mode="fixed",
        rand=False,
        grace_period=-1,
    )


# ----------------------------------------------------------
# Empty namespace falls back to default
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_container_restart_actions.terminate_pods"
)
def test_restart_eks_container_empty_namespace(
    mock_terminate_pods,
):

    restart_eks_container(
        pod_name="my-pod",
        namespace="",
        grace_period=10,
    )

    mock_terminate_pods.assert_called_once_with(
        name_pattern="my-pod",
        ns="default",
        qty=1,
        mode="fixed",
        rand=False,
        grace_period=10,
    )


# ----------------------------------------------------------
# Grace period conversion
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_container_restart_actions.terminate_pods"
)
def test_restart_eks_container_converts_grace_period(
    mock_terminate_pods,
):

    restart_eks_container(
        pod_name="my-pod",
        grace_period="15",
    )

    mock_terminate_pods.assert_called_once_with(
        name_pattern="my-pod",
        ns="default",
        qty=1,
        mode="fixed",
        rand=False,
        grace_period=15,
    )


# ----------------------------------------------------------
# Pod name validation
# ----------------------------------------------------------


@pytest.mark.parametrize(
    "pod_name",
    [
        "",
        None,
    ],
)
def test_restart_eks_container_requires_pod_name(
    pod_name,
):

    with pytest.raises(
        ValueError,
        match="EKS pod name is required",
    ):
        restart_eks_container(
            pod_name=pod_name,
        )


# ----------------------------------------------------------
# terminate_pods result is propagated
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_container_restart_actions.terminate_pods"
)
def test_restart_eks_container_returns_terminate_result(
    mock_terminate_pods,
):

    expected = {"terminated": 1}

    mock_terminate_pods.return_value = expected

    result = restart_eks_container(
        pod_name="api-pod",
        namespace="default",
    )

    assert result is expected
