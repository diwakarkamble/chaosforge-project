from unittest.mock import MagicMock, patch

from chaosforge.engines.chaos_mesh.chaos_mesh_preflight import ChaosMeshPreflight


def make_discovery():
    discovery = MagicMock()
    discovery.k8s_core_api = MagicMock()
    discovery.k8s_apps_api = MagicMock()
    return discovery


@patch("chaosforge.engines.chaos_mesh.chaos_mesh_preflight.ChaosMeshPreflight._custom_objects_api")
def test_preflight_ready(mock_custom_objects):
    discovery = make_discovery()

    deployment = MagicMock()
    deployment.spec.replicas = 1
    deployment.status.ready_replicas = 1

    daemonset = MagicMock()
    daemonset.status.desired_number_scheduled = 1
    daemonset.status.number_ready = 1

    discovery.k8s_apps_api.read_namespaced_deployment.return_value = (
        deployment
    )
    discovery.k8s_apps_api.read_namespaced_daemon_set.return_value = (
        daemonset
    )

    custom_api = MagicMock()
    custom_api.get_cluster_custom_object.return_value = {
        "metadata": {
            "name": "podchaos.chaos-mesh.org",
        }
    }

    mock_custom_objects.return_value = custom_api

    preflight = ChaosMeshPreflight(discovery)

    result = preflight.check(
        cluster="test-cluster",
        kind="PodChaos",
        namespace="default",
    )

    assert result.status == "READY"
    assert result.executable is True
    assert result.blockers == []

    discovery._configure_eks_kubernetes_client.assert_called_once_with(
        "test-cluster"
    )

    discovery.k8s_core_api.read_namespace.assert_called_once_with(
        name="default"
    )


@patch("chaosforge.engines.chaos_mesh.chaos_mesh_preflight.ChaosMeshPreflight._custom_objects_api")
def test_preflight_blocks_when_crd_missing(mock_custom_objects):
    discovery = make_discovery()

    custom_api = MagicMock()
    custom_api.get_cluster_custom_object.side_effect = RuntimeError(
        "CRD not found"
    )

    mock_custom_objects.return_value = custom_api

    preflight = ChaosMeshPreflight(discovery)

    result = preflight.check(
        cluster="test-cluster",
        kind="PodChaos",
        namespace="default",
    )

    assert result.status == "BLOCKED"
    assert result.executable is False
    assert any(
        "podchaos.chaos-mesh.org" in blocker
        for blocker in result.blockers
    )


def test_preflight_blocks_without_cluster():
    discovery = make_discovery()
    preflight = ChaosMeshPreflight(discovery)

    result = preflight.check(
        cluster="",
        kind="PodChaos",
    )

    assert result.status == "BLOCKED"
    assert result.executable is False
    assert "EKS cluster is required." in result.blockers


def test_preflight_blocks_unknown_kind():
    discovery = make_discovery()
    preflight = ChaosMeshPreflight(discovery)

    result = preflight.check(
        cluster="test-cluster",
        kind="UnknownChaos",
    )

    assert result.status == "BLOCKED"
    assert result.executable is False
    assert any(
        "Unsupported Chaos Mesh preflight kind" in blocker
        for blocker in result.blockers
    )


@patch("chaosforge.engines.chaos_mesh.chaos_mesh_preflight.ChaosMeshPreflight._custom_objects_api")
def test_preflight_blocks_when_kubernetes_connection_fails(
    mock_custom_objects,
):
    discovery = make_discovery()

    discovery._configure_eks_kubernetes_client.side_effect = LookupError(
        "Kubernetes configuration was not found"
    )

    preflight = ChaosMeshPreflight(discovery)

    result = preflight.check(
        cluster="test-cluster",
        kind="NetworkChaos",
    )

    assert result.status == "BLOCKED"
    assert result.executable is False
    assert any(
        "Kubernetes API is not available" in blocker
        for blocker in result.blockers
    )

    mock_custom_objects.assert_not_called()

def test_preflight_blocks_when_controller_manager_not_ready():
    discovery = make_discovery()

    deployment = MagicMock()
    deployment.spec.replicas = 1
    deployment.status.ready_replicas = 0

    daemonset = MagicMock()
    daemonset.status.desired_number_scheduled = 1
    daemonset.status.number_ready = 1

    discovery.k8s_apps_api.read_namespaced_deployment.return_value = (
        deployment
    )
    discovery.k8s_apps_api.read_namespaced_daemon_set.return_value = (
        daemonset
    )

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_preflight.ChaosMeshPreflight._custom_objects_api"
    ) as mock_custom_objects:
        custom_api = MagicMock()
        custom_api.get_cluster_custom_object.return_value = {
            "metadata": {
                "name": "podchaos.chaos-mesh.org",
            }
        }
        mock_custom_objects.return_value = custom_api

        preflight = ChaosMeshPreflight(discovery)

        result = preflight.check(
            cluster="test-cluster",
            kind="PodChaos",
            namespace="default",
        )

    assert result.status == "BLOCKED"
    assert result.executable is False
    assert any(
        "Controller Manager is not ready" in blocker
        for blocker in result.blockers
    )


def test_preflight_blocks_when_chaos_daemon_not_ready():
    discovery = make_discovery()

    deployment = MagicMock()
    deployment.spec.replicas = 1
    deployment.status.ready_replicas = 1

    daemonset = MagicMock()
    daemonset.status.desired_number_scheduled = 3
    daemonset.status.number_ready = 2

    discovery.k8s_apps_api.read_namespaced_deployment.return_value = (
        deployment
    )
    discovery.k8s_apps_api.read_namespaced_daemon_set.return_value = (
        daemonset
    )

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_preflight.ChaosMeshPreflight._custom_objects_api"
    ) as mock_custom_objects:
        custom_api = MagicMock()
        custom_api.get_cluster_custom_object.return_value = {
            "metadata": {
                "name": "podchaos.chaos-mesh.org",
            }
        }
        mock_custom_objects.return_value = custom_api

        preflight = ChaosMeshPreflight(discovery)

        result = preflight.check(
            cluster="test-cluster",
            kind="PodChaos",
            namespace="default",
        )

    assert result.status == "BLOCKED"
    assert result.executable is False
    assert any(
        "Chaos Mesh Daemon is not ready" in blocker
        for blocker in result.blockers
    )




def test_schedule_does_not_require_chaos_daemon():
    discovery = MagicMock()

    discovery.k8s_core_api = MagicMock()
    discovery.k8s_apps_api = MagicMock()

    deployment = MagicMock()
    deployment.spec.replicas = 1
    deployment.status.ready_replicas = 1

    discovery.k8s_apps_api.read_namespaced_deployment.return_value = (
        deployment
    )

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_preflight.ChaosMeshPreflight._custom_objects_api"
    ) as mock_custom_objects:
        custom_api = MagicMock()
        custom_api.get_cluster_custom_object.return_value = {
            "metadata": {
                "name": "schedules.chaos-mesh.org",
            }
        }
        mock_custom_objects.return_value = custom_api

        preflight = ChaosMeshPreflight(discovery)

        result = preflight.check(
            cluster="test-cluster",
            kind="Schedule",
            namespace="default",
        )

    assert result.status == "READY"
    assert result.executable is True

    check_names = [
        check["name"]
        for check in result.checks
    ]

    assert "Chaos Controller Manager" in check_names
    assert "Chaos Daemon" not in check_names

    discovery.k8s_apps_api.read_namespaced_daemon_set.assert_not_called()
