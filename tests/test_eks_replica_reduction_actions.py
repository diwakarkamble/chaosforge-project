import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions import (
    STATE_FILE,
    capture_current_replicas,
    reduce_replicas,
    restore_original_replicas,
    wait_for_duration,
)

# ----------------------------------------------------------
# Kubernetes configuration
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.config.load_incluster_config"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.config.load_kube_config"
)
def test_load_kubernetes_falls_back_to_incluster(
    mock_load_kube_config,
    mock_load_incluster_config,
):

    from kubernetes.config.config_exception import ConfigException

    from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions import (
        _load_kubernetes,
    )

    mock_load_kube_config.side_effect = ConfigException("kubeconfig unavailable")

    _load_kubernetes()

    mock_load_kube_config.assert_called_once()
    mock_load_incluster_config.assert_called_once()


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.config.load_kube_config"
)
def test_load_kubernetes_uses_kubeconfig(
    mock_load_kube_config,
):

    from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions import (
        _load_kubernetes,
    )

    _load_kubernetes()

    mock_load_kube_config.assert_called_once()


# ----------------------------------------------------------
# Apps API
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.client.AppsV1Api"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions._load_kubernetes"
)
def test_get_apps_api(
    mock_load_kubernetes,
    mock_apps_api,
):

    from chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions import (
        _get_apps_api,
    )

    expected_api = MagicMock()
    mock_apps_api.return_value = expected_api

    result = _get_apps_api()

    assert result is expected_api
    mock_load_kubernetes.assert_called_once()
    mock_apps_api.assert_called_once_with()


# ----------------------------------------------------------
# Capture replicas
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.json.dump"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions._get_apps_api"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.open",
    new_callable=mock_open,
)
def test_capture_current_replicas(
    mock_file,
    mock_get_apps_api,
    mock_json_dump,
):

    api = mock_get_apps_api.return_value

    deployment = MagicMock()
    deployment.spec.replicas = 3

    api.read_namespaced_deployment.return_value = deployment

    result = capture_current_replicas(
        deployment_name="api",
        namespace="production",
    )

    assert result == 3

    api.read_namespaced_deployment.assert_called_once_with(
        name="api",
        namespace="production",
    )

    mock_file.assert_called_once_with(
        STATE_FILE,
        "w",
        encoding="utf-8",
    )

    mock_json_dump.assert_called_once_with(
        {
            "deployment_name": "api",
            "namespace": "production",
            "original_replicas": 3,
        },
        mock_file.return_value.__enter__.return_value,
    )


# ----------------------------------------------------------
# Capture replicas when Kubernetes reports None
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.json.dump"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions._get_apps_api"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.open",
    new_callable=mock_open,
)
def test_capture_current_replicas_none(
    mock_file,
    mock_get_apps_api,
    mock_json_dump,
):

    api = mock_get_apps_api.return_value

    deployment = MagicMock()
    deployment.spec.replicas = None

    api.read_namespaced_deployment.return_value = deployment

    result = capture_current_replicas(
        deployment_name="api",
        namespace="default",
    )

    assert result == 0

    mock_json_dump.assert_called_once_with(
        {
            "deployment_name": "api",
            "namespace": "default",
            "original_replicas": 0,
        },
        mock_file.return_value.__enter__.return_value,
    )


# ----------------------------------------------------------
# Reduce replicas
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions._get_apps_api"
)
def test_reduce_replicas(
    mock_get_apps_api,
):

    api = mock_get_apps_api.return_value

    result = reduce_replicas(
        deployment_name="api",
        namespace="production",
        reduced_replicas=1,
    )

    assert result == ("Deployment api scaled to 1 replica(s).")

    api.patch_namespaced_deployment_scale.assert_called_once_with(
        name="api",
        namespace="production",
        body={
            "spec": {
                "replicas": 1,
            }
        },
    )


# ----------------------------------------------------------
# Reduce replicas converts string
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions._get_apps_api"
)
def test_reduce_replicas_converts_string(
    mock_get_apps_api,
):

    api = mock_get_apps_api.return_value

    result = reduce_replicas(
        deployment_name="api",
        reduced_replicas="2",
    )

    assert result == ("Deployment api scaled to 2 replica(s).")

    api.patch_namespaced_deployment_scale.assert_called_once_with(
        name="api",
        namespace="default",
        body={
            "spec": {
                "replicas": 2,
            }
        },
    )


# ----------------------------------------------------------
# Negative replicas
# ----------------------------------------------------------


def test_reduce_replicas_rejects_negative():

    with pytest.raises(
        ValueError,
        match="Replica count cannot be negative",
    ):
        reduce_replicas(
            deployment_name="api",
            reduced_replicas=-1,
        )


# ----------------------------------------------------------
# Restore state missing
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.os.path.exists"
)
def test_restore_original_replicas_state_missing(
    mock_exists,
):

    mock_exists.return_value = False

    with pytest.raises(
        FileNotFoundError,
        match="State file not found",
    ):
        restore_original_replicas(
            deployment_name="api",
        )


# ----------------------------------------------------------
# Restore replicas
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.os.remove"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.os.path.exists"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions._get_apps_api"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.open",
    new_callable=mock_open,
    read_data=json.dumps(
        {
            "deployment_name": "api",
            "namespace": "production",
            "original_replicas": 4,
        }
    ),
)
def test_restore_original_replicas(
    mock_file,
    mock_get_apps_api,
    mock_exists,
    mock_remove,
):

    api = mock_get_apps_api.return_value
    mock_exists.return_value = True

    result = restore_original_replicas(
        deployment_name="api",
        namespace="production",
    )

    assert result == ("Deployment api restored to 4 replica(s).")

    api.patch_namespaced_deployment_scale.assert_called_once_with(
        name="api",
        namespace="production",
        body={
            "spec": {
                "replicas": 4,
            }
        },
    )

    mock_remove.assert_called_once_with(
        STATE_FILE,
    )


# ----------------------------------------------------------
# Restore state cleanup failure
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.os.remove"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.os.path.exists"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions._get_apps_api"
)
@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.open",
    new_callable=mock_open,
    read_data=json.dumps(
        {
            "deployment_name": "api",
            "namespace": "default",
            "original_replicas": 2,
        }
    ),
)
def test_restore_original_replicas_remove_failure(
    mock_file,
    mock_get_apps_api,
    mock_exists,
    mock_remove,
):

    mock_exists.return_value = True
    mock_remove.side_effect = OSError

    result = restore_original_replicas(
        deployment_name="api",
    )

    assert result == ("Deployment api restored to 2 replica(s).")


# ----------------------------------------------------------
# Wait positive duration
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.time.sleep"
)
def test_wait_for_duration(
    mock_sleep,
):

    wait_for_duration(30)

    mock_sleep.assert_called_once_with(30)


# ----------------------------------------------------------
# Wait converts string
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.time.sleep"
)
def test_wait_for_duration_converts_string(
    mock_sleep,
):

    wait_for_duration("15")

    mock_sleep.assert_called_once_with(15)


# ----------------------------------------------------------
# Wait zero
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.time.sleep"
)
def test_wait_for_duration_zero(
    mock_sleep,
):

    wait_for_duration(0)

    mock_sleep.assert_not_called()


# ----------------------------------------------------------
# Wait negative
# ----------------------------------------------------------


@patch(
    "chaosforge.providers.aws.components.eks.experiments.toolkit.actions.eks_replica_reduction_actions.time.sleep"
)
def test_wait_for_duration_negative(
    mock_sleep,
):

    wait_for_duration(-1)

    mock_sleep.assert_not_called()
