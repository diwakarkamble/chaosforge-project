from unittest.mock import patch

import pytest

from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_cordon_actions import (
    cordon_eks_node,
    uncordon_eks_node,
)

# ----------------------------------------------------------
# Cordon node
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_cordon_actions.cordon_node"
)
def test_cordon_eks_node(
    mock_cordon_node,
):

    mock_cordon_node.return_value = "cordon-result"

    result = cordon_eks_node(
        node_name="ip-10-0-1-100",
    )

    assert result == "cordon-result"

    mock_cordon_node.assert_called_once_with(
        name="ip-10-0-1-100",
    )


# ----------------------------------------------------------
# Uncordon node
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_node_cordon_actions.uncordon_node"
)
def test_uncordon_eks_node(
    mock_uncordon_node,
):

    mock_uncordon_node.return_value = "uncordon-result"

    result = uncordon_eks_node(
        node_name="ip-10-0-1-100",
    )

    assert result == "uncordon-result"

    mock_uncordon_node.assert_called_once_with(
        name="ip-10-0-1-100",
    )


# ----------------------------------------------------------
# Cordon validation
# ----------------------------------------------------------


@pytest.mark.parametrize(
    "node_name",
    [
        "",
        None,
    ],
)
def test_cordon_eks_node_requires_node_name(
    node_name,
):

    with pytest.raises(
        ValueError,
        match="EKS node name is required",
    ):
        cordon_eks_node(node_name)


# ----------------------------------------------------------
# Uncordon validation
# ----------------------------------------------------------


@pytest.mark.parametrize(
    "node_name",
    [
        "",
        None,
    ],
)
def test_uncordon_eks_node_requires_node_name(
    node_name,
):

    with pytest.raises(
        ValueError,
        match="EKS node name is required",
    ):
        uncordon_eks_node(node_name)
