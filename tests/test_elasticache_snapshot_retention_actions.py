from unittest.mock import MagicMock, patch

import chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_snapshot_retention_actions as actions

# ----------------------------------------------------------
# get_cache
# ----------------------------------------------------------


def test_get_cache():

    client = MagicMock()

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"SnapshotRetentionLimit": 7}]
    }

    result = actions.get_cache(
        client,
        "cache1",
    )

    assert result["SnapshotRetentionLimit"] == 7

    client.describe_serverless_caches.assert_called_once_with(
        ServerlessCacheName="cache1"
    )


# ----------------------------------------------------------
# capture_snapshot_retention
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_snapshot_retention_actions.boto3.client")
def test_capture_snapshot_retention(mock_boto):

    client = MagicMock()

    mock_boto.return_value = client

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"SnapshotRetentionLimit": 14}]
    }

    actions.capture_snapshot_retention(
        "cache1",
        "eu-central-1",
    )

    assert actions._original_snapshot_retention == 14


# ----------------------------------------------------------
# modify_snapshot_retention
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_snapshot_retention_actions.boto3.client")
def test_modify_snapshot_retention(mock_boto):

    actions._original_snapshot_retention = 14

    client = MagicMock()

    mock_boto.return_value = client

    client.modify_serverless_cache.return_value = {
        "ServerlessCache": {"Status": "modifying"}
    }

    actions.modify_snapshot_retention(
        "cache1",
        "eu-central-1",
        "30",
    )

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        SnapshotRetentionLimit=30,
    )


# ----------------------------------------------------------
# restore_snapshot_retention
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_snapshot_retention_actions.boto3.client")
def test_restore_snapshot_retention(mock_boto):

    actions._original_snapshot_retention = 21

    client = MagicMock()

    mock_boto.return_value = client

    client.modify_serverless_cache.return_value = {
        "ServerlessCache": {"Status": "available"}
    }

    actions.restore_snapshot_retention(
        "cache1",
        "eu-central-1",
    )

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        SnapshotRetentionLimit=21,
    )
