from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.application.component_fis import bind_component_fis
from chaosforge.lifecycle.checks.kubernetes_chaos import SharedChaosMeshValidationCheck
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.providers.aws.fis import component_actions

eks_fis_actions = import_module("chaosforge.providers.aws.components.eks.experiments.fis.actions")


def test_eks_fis_pod_delete_uses_cluster_namespace_and_pod_inputs():
    metadata = {
        "inputs": [
            {"name": "service_id"}, {"name": "experiment_id"}, {"name": "created_by"},
            {"name": "target_arn"}, {"name": "role_arn"},
        ]
    }
    bound = bind_component_fis(metadata, "eks", "pod-delete")

    assert [field["name"] for field in bound["inputs"] if field["name"] in {"eks_cluster", "namespace", "pod"}] == [
        "eks_cluster", "namespace", "pod"
    ]
    assert "target_arn" not in [field["name"] for field in bound["inputs"]]


def test_eks_fis_pod_delete_resolves_pod_arn_once(monkeypatch):
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    monkeypatch.setattr(eks_fis_actions.boto3, "client", lambda *_args, **_kwargs: sts)
    variables = {
        "service_id": "eks", "experiment_id": "pod-delete", "aws_region": "eu-central-1",
        "eks_cluster": "demo", "namespace": "apps", "pod": "api-1",
    }

    eks_fis_actions.prepare(variables)
    eks_fis_actions.prepare(variables)

    assert variables["target_arn"] == "arn:aws:eks:eu-central-1:123456789012:pod/demo/apps/api-1"
    sts.get_caller_identity.assert_called_once()


def test_eks_fis_non_pod_delete_action_does_not_prepare_target(monkeypatch):
    sts = MagicMock()
    monkeypatch.setattr(eks_fis_actions.boto3, "client", sts)
    variables = {"service_id": "eks", "experiment_id": "pod-cpu-stress", "aws_region": "eu-central-1"}

    eks_fis_actions.prepare(variables)

    assert "target_arn" not in variables
    sts.assert_not_called()


def test_eks_fis_pod_delete_reuses_aks_pod_kill_validation():
    experiment = SimpleNamespace(
        id="fis-create-experiment",
        variables={"service_id": "eks", "experiment_id": "pod-delete"},
    )

    check = CheckResolver().resolve(experiment, discovery=SimpleNamespace())

    assert isinstance(check, SharedChaosMeshValidationCheck)
    assert check.validation_id == "aks-pod-kill"


def test_eks_fis_pod_delete_requires_discovery_for_shared_validation():
    experiment = SimpleNamespace(
        id="fis-create-experiment",
        variables={"service_id": "eks", "experiment_id": "pod-delete"},
    )

    with pytest.raises(ValueError, match="AWS discovery is required"):
        CheckResolver().resolve(experiment)


def test_eks_component_dispatch_prepares_before_shared_fis_lifecycle(monkeypatch):
    prepare = MagicMock()
    module = MagicMock(prepare=prepare)
    create = MagicMock()
    monkeypatch.setattr(component_actions, "import_module", MagicMock(return_value=module))
    variables = {
        "service_id": "eks", "experiment_id": "pod-delete", "experiment_name": "Pod Delete",
        "description": "Test", "target_arn": "arn:pod", "role_arn": "arn:role",
        "aws_region": "eu-central-1",
    }

    component_actions.execute(variables, create)

    prepare.assert_called_once_with(variables)
    assert create.call_args.kwargs["service_id"] == "eks"
