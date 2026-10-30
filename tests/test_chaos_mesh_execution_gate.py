from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_execution_gate import (
    ChaosMeshExecutionGate,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshInstaller,
    ChaosMeshReleaseInfo,
    HelmReleaseStatus,
)


def create_experiment():
    return SimpleNamespace(
        id="chaos-mesh-network-delay",
        variables={
            "eks_cluster": "Chaos-POC-v2",
            "namespace": "default",
        },
        json_file="chaosforge/engines/chaos_mesh/experiments/definitions/network-delay.json",
    )


def create_manifest_mapper(kind="NetworkChaos"):
    mapper = Mock()
    mapper.build_manifest.return_value = {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": kind,
        "metadata": {
            "name": "test-chaos",
            "namespace": "default",
        },
        "spec": {},
    }
    return mapper


def create_preflight(executable=True, blockers=None):
    preflight = Mock()
    preflight.check.return_value = SimpleNamespace(
        executable=executable,
        blockers=blockers or [],
    )
    return preflight


def create_installer(
    release_status=HelmReleaseStatus.INSTALLED,
):
    installer = Mock()
    installer.release_status.return_value = (
        release_status,
        "test release status",
    )
    installer.release_info.return_value = ChaosMeshReleaseInfo(
        release_status,
        "test release status",
        "2.8.7" if release_status == HelmReleaseStatus.INSTALLED else None,
    )
    installer.ensure_installed.return_value = SimpleNamespace(
        status="INSTALLED",
        message="installed",
        installed=True,
    )
    return installer


def test_ready_environment_does_not_install():
    installer = create_installer()
    preflight = create_preflight(executable=True)
    mapper = create_manifest_mapper()

    gate = ChaosMeshExecutionGate(
        discovery=Mock(),
        installer=installer,
        preflight=preflight,
        mapper=mapper,
    )

    gate.ensure_ready(create_experiment())

    installer.release_status.assert_not_called()
    installer.ensure_installed.assert_not_called()
    preflight.check.assert_called_once()


def test_absent_release_triggers_installation():
    installer = create_installer(
        release_status=HelmReleaseStatus.ABSENT,
    )
    preflight = create_preflight(
        executable=False,
        blockers=["Chaos Mesh CRD is unavailable."],
    )
    mapper = create_manifest_mapper()

    gate = ChaosMeshExecutionGate(
        discovery=Mock(),
        installer=installer,
        preflight=preflight,
        mapper=mapper,
    )

    preflight.check.side_effect = [
        SimpleNamespace(
            executable=False,
            blockers=["Chaos Mesh CRD is unavailable."],
        ),
        SimpleNamespace(
            executable=True,
            blockers=[],
        ),
    ]

    experiment = create_experiment()
    experiment.chaos_mesh_version_action = "install"
    gate.ensure_ready(experiment)

    installer.ensure_installed.assert_called_once()
    assert preflight.check.call_count == 2


def test_absent_release_installs_even_when_crds_are_already_ready():
    installer = create_installer(release_status=HelmReleaseStatus.ABSENT)
    preflight = create_preflight(executable=True)
    mapper = create_manifest_mapper()
    experiment = create_experiment()
    experiment.chaos_mesh_version_action = "install"
    gate = ChaosMeshExecutionGate(
        discovery=Mock(), installer=installer, preflight=preflight, mapper=mapper
    )

    gate.ensure_ready(experiment)

    installer.ensure_installed.assert_called_once()
    assert preflight.check.call_count == 2


def test_older_release_upgrades_and_rechecks_preflight():
    installer = create_installer(release_status=HelmReleaseStatus.INSTALLED)
    installer.release_info.return_value = ChaosMeshReleaseInfo(
        HelmReleaseStatus.INSTALLED, "installed", "2.8.4"
    )
    installer.upgrade.return_value = SimpleNamespace(status="UPGRADED", message="ok")
    preflight = create_preflight(executable=True)
    experiment = create_experiment()
    experiment.chaos_mesh_version_action = "upgrade"
    gate = ChaosMeshExecutionGate(
        discovery=Mock(), installer=installer, preflight=preflight,
        mapper=create_manifest_mapper(),
    )

    gate.ensure_ready(experiment)

    installer.upgrade.assert_called_once()
    assert preflight.check.call_count == 2


def test_installed_release_does_not_reinstall():
    installer = create_installer(
        release_status=HelmReleaseStatus.INSTALLED,
    )
    preflight = create_preflight(
        executable=False,
        blockers=["Chaos Mesh Daemon is unavailable."],
    )
    mapper = create_manifest_mapper()

    gate = ChaosMeshExecutionGate(
        discovery=Mock(),
        installer=installer,
        preflight=preflight,
        mapper=mapper,
    )

    with pytest.raises(RuntimeError, match="Helm release is installed"):
        gate.ensure_ready(create_experiment())

    installer.ensure_installed.assert_not_called()


def test_helm_status_error_blocks_execution():
    installer = create_installer(
        release_status=HelmReleaseStatus.ERROR,
    )
    preflight = create_preflight(
        executable=False,
        blockers=["Kubernetes API is not available."],
    )
    mapper = create_manifest_mapper()

    gate = ChaosMeshExecutionGate(
        discovery=Mock(),
        installer=installer,
        preflight=preflight,
        mapper=mapper,
    )

    with pytest.raises(RuntimeError, match="test release status"):
        gate.ensure_ready(create_experiment())

    installer.ensure_installed.assert_not_called()


def test_missing_cluster_blocks_execution():
    experiment = create_experiment()
    experiment.variables.pop("eks_cluster")

    gate = ChaosMeshExecutionGate(
        discovery=Mock(),
        installer=Mock(),
        preflight=Mock(),
        mapper=Mock(),
    )

    with pytest.raises(
        RuntimeError,
        match="eks_cluster",
    ):
        gate.ensure_ready(experiment)


def test_mapper_kind_is_used_for_preflight():
    installer = create_installer()
    preflight = create_preflight(executable=True)
    mapper = create_manifest_mapper(kind="HTTPChaos")

    gate = ChaosMeshExecutionGate(
        discovery=Mock(),
        installer=installer,
        preflight=preflight,
        mapper=mapper,
    )
    gate.installer.release_info = Mock(
        return_value=ChaosMeshReleaseInfo(
            HelmReleaseStatus.INSTALLED,
            "installed",
            "2.8.7",
        )
    )

    gate.ensure_ready(create_experiment())

    preflight.check.assert_called_once_with(
        cluster="Chaos-POC-v2",
        kind="HTTPChaos",
        namespace="default",
    )


def test_discovery_kubeconfig_is_passed_to_default_installer(monkeypatch):
    discovery = Mock()
    discovery.eks_kubeconfig_path = (
        r"C:\temp\chaosforge-eks.config"
    )
    discovery.eks_kube_context = (
        "arn:aws:eks:eu-central-1:123456789012:"
        "cluster/Chaos-POC-v2"
    )

    preflight = create_preflight(executable=True)
    mapper = create_manifest_mapper()
    monkeypatch.setattr(
        ChaosMeshInstaller,
        "release_info",
        lambda _self: ChaosMeshReleaseInfo(
            HelmReleaseStatus.INSTALLED, "installed", "2.8.7"
        ),
    )

    gate = ChaosMeshExecutionGate(
        discovery=discovery,
        preflight=preflight,
        mapper=mapper,
    )

    gate.ensure_ready(create_experiment())

    assert isinstance(gate.installer, ChaosMeshInstaller)
    assert (
        gate.installer.kubeconfig_path
        == r"C:\temp\chaosforge-eks.config"
    )
    assert (
        gate.installer.kube_context
        == (
            "arn:aws:eks:eu-central-1:123456789012:"
            "cluster/Chaos-POC-v2"
        )
    )
