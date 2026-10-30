from unittest.mock import MagicMock, patch

from chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_reboot_actions import (
    reboot_cache_cluster,
)

# ----------------------------------------------------------
# Reboot Cache Cluster
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_reboot_actions.boto3.client")
def test_reboot_cache_cluster(mock_boto):

    client = MagicMock()

    mock_boto.return_value = client

    reboot_cache_cluster(
        "cache-1",
        "eu-central-1",
    )

    mock_boto.assert_called_once_with(
        "elasticache",
        region_name="eu-central-1",
    )

    client.reboot_cache_cluster.assert_called_once_with(
        CacheClusterId="cache-1",
        CacheNodeIdsToReboot=["0001"],
    )
    client.get_waiter.assert_called_once_with("cache_cluster_available")
    client.get_waiter.return_value.wait.assert_called_once_with(
        CacheClusterId="cache-1",
        WaiterConfig={"Delay": 15, "MaxAttempts": 40},
    )


# ----------------------------------------------------------
# Different Region
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_reboot_actions.boto3.client")
def test_reboot_cache_cluster_different_region(mock_boto):

    client = MagicMock()

    mock_boto.return_value = client

    reboot_cache_cluster(
        "production-cache",
        "us-east-1",
    )

    mock_boto.assert_called_once_with(
        "elasticache",
        region_name="us-east-1",
    )

    client.reboot_cache_cluster.assert_called_once_with(
        CacheClusterId="production-cache",
        CacheNodeIdsToReboot=["0001"],
    )
    client.get_waiter.return_value.wait.assert_called_once_with(
        CacheClusterId="production-cache",
        WaiterConfig={"Delay": 15, "MaxAttempts": 40},
    )
