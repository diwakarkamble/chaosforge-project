import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions import (
    capture_and_modify_daily_snapshot,
    rollback_daily_snapshot,
)

# ----------------------------------------------------------
# Capture + Modify
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.wait_for_serverless_cache_available")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.json.dump")
@patch("builtins.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.get_client")
def test_capture_and_modify_daily_snapshot(
    mock_get_client,
    mock_file,
    mock_dump,
    mock_wait,
):

    client = MagicMock()

    mock_get_client.return_value = client

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"DailySnapshotTime": "02:00"}]
    }

    capture_and_modify_daily_snapshot(
        "cache1",
        "05:00",
        "eu-central-1",
    )

    mock_dump.assert_called_once()

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        DailySnapshotTime="05:00",
    )

    mock_wait.assert_called_once_with(
        client,
        "cache1",
    )


# ----------------------------------------------------------
# Rollback
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.os.remove")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.wait_for_serverless_cache_available")
@patch(
    "builtins.open",
    new_callable=mock_open,
    read_data=json.dumps(
        {
            "serverless_cache_name": "cache1",
            "region": "eu-central-1",
            "original": "02:00",
        }
    ),
)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.get_client")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.os.path.exists")
def test_rollback_daily_snapshot(
    mock_exists,
    mock_get_client,
    mock_file,
    mock_wait,
    mock_remove,
):

    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    rollback_daily_snapshot()

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        DailySnapshotTime="02:00",
    )

    mock_wait.assert_called_once_with(
        client,
        "cache1",
    )

    mock_remove.assert_called_once()


# ----------------------------------------------------------
# Missing State File
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.os.path.exists")
def test_rollback_daily_snapshot_no_state(
    mock_exists,
):

    mock_exists.return_value = False

    with pytest.raises(FileNotFoundError):
        rollback_daily_snapshot()


# ----------------------------------------------------------
# Capture when Snapshot Time is None
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.wait_for_serverless_cache_available")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.json.dump")
@patch("builtins.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_daily_snapshot_actions.get_client")
def test_capture_daily_snapshot_none(
    mock_get_client,
    mock_file,
    mock_dump,
    mock_wait,
):

    client = MagicMock()

    mock_get_client.return_value = client

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"DailySnapshotTime": None}]
    }

    capture_and_modify_daily_snapshot(
        "cache1",
        "06:00",
        "eu-central-1",
    )

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        DailySnapshotTime="06:00",
    )
