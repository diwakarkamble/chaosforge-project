from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshReleaseInfo,
    HelmReleaseStatus,
)
from chaosforge.engines.chaos_mesh.version_policy import (
    ChaosMeshVersionAssessment,
    apply_execution_actions,
    assess_campaign,
    assess_installer,
    compare_versions,
    decision_is_current,
    saved_decision,
)
from chaosforge.models import Campaign, Experiment


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ("2.8.4", "older"),
        ("2.8.7", "current"),
        ("2.8.8", "newer"),
        ("2.7.9", "incompatible"),
        ("3.0.0", "incompatible"),
    ],
)
def test_compare_versions(installed, expected):
    assert compare_versions(installed) == expected


def test_compare_versions_rejects_invalid_value():
    with pytest.raises(ValueError, match="Invalid Chaos Mesh version"):
        compare_versions("latest")


@pytest.mark.parametrize(
    ("status", "version", "state"),
    [
        (HelmReleaseStatus.ABSENT, None, "absent"),
        (HelmReleaseStatus.ERROR, None, "error"),
        (HelmReleaseStatus.INSTALLED, None, "error"),
        (HelmReleaseStatus.INSTALLED, "2.8.4", "older"),
        (HelmReleaseStatus.INSTALLED, "2.8.7", "current"),
        (HelmReleaseStatus.INSTALLED, "2.8.9", "newer"),
        (HelmReleaseStatus.INSTALLED, "2.9.0", "incompatible"),
    ],
)
def test_assess_installer_classifies_release(status, version, state):
    installer = MagicMock()
    installer.release_info.return_value = ChaosMeshReleaseInfo(status, "status", version)

    assessment = assess_installer(installer, "eu-central-1", "cluster")

    assert assessment.state == state
    assert assessment.key == "eu-central-1:cluster"


def test_campaign_assessment_is_unique_per_region_and_cluster():
    campaign = Campaign(experiments=[
        Experiment("one", "chaos_mesh", "One", "file", {
            "aws_region": "eu-central-1", "eks_cluster": "cluster",
        }, engine="Chaos Mesh"),
        Experiment("two", "chaos_mesh", "Two", "file", {
            "aws_region": "eu-central-1", "eks_cluster": "cluster",
        }, engine="Chaos Mesh"),
    ])
    discovery = MagicMock()
    discovery.eks_kubeconfig_path = "config"
    discovery.eks_kube_context = "context"
    installer = MagicMock()
    installer.release_info.return_value = ChaosMeshReleaseInfo(
        HelmReleaseStatus.INSTALLED, "installed", "2.8.7"
    )
    installer_factory = MagicMock(return_value=installer)

    assessments = assess_campaign(
        campaign,
        discovery_factory=MagicMock(return_value=discovery),
        installer_factory=installer_factory,
    )

    assert len(assessments) == 1
    discovery._configure_eks_kubernetes_client.assert_called_once_with("cluster")
    installer_factory.assert_called_once_with(
        kubeconfig_path="config", kube_context="context",
        release_name="chaos-mesh", namespace="chaos-mesh",
    )


def test_campaign_assessment_includes_only_aks_experiments_using_chaos_mesh():
    campaign = Campaign(experiments=[
        Experiment("aks-pod-kill", "aks", "Pod", "file", {"aks_context": "aks-ctx"}),
        Experiment("aks-crashloop", "aks", "Crashloop", "file", {"aks_context": "aks-ctx"}),
        Experiment("aks-node-drain", "aks", "Drain", "file", {"aks_context": "aks-ctx"}),
    ])
    installer = MagicMock()
    installer.release_info.return_value = ChaosMeshReleaseInfo(
        HelmReleaseStatus.INSTALLED, "installed", "2.8.7"
    )
    installer_factory = MagicMock(return_value=installer)

    assessments = assess_campaign(campaign, installer_factory=installer_factory)

    assert [item.key for item in assessments] == ["azure:aks-ctx"]
    installer_factory.assert_called_once_with(
        kubeconfig_path=None,
        kube_context="aks-ctx",
        release_name="chaos-mesh-studio",
        namespace="chaos-testing",
    )


def test_saved_decision_is_reused_only_for_same_detected_version():
    assessment = ChaosMeshVersionAssessment(
        "region:cluster", "cluster", "region", "older", "2.8.4"
    )
    decision = saved_decision("continue", assessment)

    assert decision_is_current(decision, assessment)
    assert not decision_is_current(
        decision,
        ChaosMeshVersionAssessment(
            "region:cluster", "cluster", "region", "older", "2.8.5"
        ),
    )


def test_apply_execution_actions_sets_transient_directive_without_variables():
    experiment = Experiment(
        "one", "chaos_mesh", "One", "file",
        {"aws_region": "region", "eks_cluster": "cluster"},
        engine="Chaos Mesh",
    )
    campaign = Campaign(experiments=[experiment])
    assessment = ChaosMeshVersionAssessment(
        "region:cluster", "cluster", "region", "older", "2.8.4"
    )

    apply_execution_actions(
        campaign, [assessment], {assessment.key: saved_decision("upgrade", assessment)}
    )

    assert experiment.chaos_mesh_version_action == "upgrade"
    assert "chaos_mesh_version_action" not in experiment.variables


def test_apply_execution_actions_sets_aks_transient_directive():
    experiment = Experiment(
        "aks-pod-kill", "aks", "Pod Kill", "file",
        {"aks_context": "aks-ctx"}, engine="Azure Chaos Studio",
    )
    campaign = Campaign(experiments=[experiment])
    assessment = ChaosMeshVersionAssessment(
        "azure:aks-ctx", "aks-ctx", "azure", "older", "2.8.4"
    )

    apply_execution_actions(
        campaign, [assessment], {
            assessment.key: saved_decision("continue", assessment)
        }
    )

    assert experiment.chaos_mesh_version_action == "continue"
    assert experiment.chaos_mesh_installed_version == "2.8.4"


def test_apply_execution_actions_rejects_missing_decision():
    campaign = SimpleNamespace(experiments=[SimpleNamespace(
        engine="Chaos Mesh", variables={"aws_region": "region", "eks_cluster": "cluster"}
    )])
    assessment = ChaosMeshVersionAssessment(
        "region:cluster", "cluster", "region", "older", "2.8.4"
    )
    with pytest.raises(ValueError, match="decision is required"):
        apply_execution_actions(campaign, [assessment], {})
