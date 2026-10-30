import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions import (
    capture_and_modify_usage_limit,
    rollback_usage_limit,
)

# ----------------------------------------------------------
# Capture + Modify
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.wait_for_serverless_cache_available")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.json.dump")
@patch("builtins.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.get_client")
def test_capture_and_modify_usage_limit(
    mock_get_client,
    mock_file,
    mock_dump,
    mock_wait,
):

    client = MagicMock()

    mock_get_client.return_value = client

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"CacheUsageLimits": {"DataStorage": {"Maximum": 100}}}]
    }

    capture_and_modify_usage_limit(
        "cache1",
        "DataStorage",
        "200",
        "eu-central-1",
    )

    mock_dump.assert_called_once()

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        CacheUsageLimits={"DataStorage": {"Maximum": 200}},
    )

    mock_wait.assert_called_once_with(
        client,
        "cache1",
    )


# ----------------------------------------------------------
# Usage Limit Missing
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.get_client")
def test_capture_and_modify_usage_limit_missing(
    mock_get_client,
):

    client = MagicMock()

    mock_get_client.return_value = client

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"CacheUsageLimits": {}}]
    }

    with pytest.raises(ValueError):
        capture_and_modify_usage_limit(
            "cache1",
            "DataStorage",
            "200",
            "eu-central-1",
        )


# ----------------------------------------------------------
# Rollback
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.os.remove")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.wait_for_serverless_cache_available")
@patch(
    "builtins.open",
    new_callable=mock_open,
    read_data=json.dumps(
        {
            "serverless_cache_name": "cache1",
            "region": "eu-central-1",
            "usage_type": "DataStorage",
            "original": {"Maximum": 100},
        }
    ),
)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.get_client")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.os.path.exists")
def test_rollback_usage_limit(
    mock_exists,
    mock_get_client,
    mock_file,
    mock_wait,
    mock_remove,
):

    mock_exists.return_value = True

    client = MagicMock()

    mock_get_client.return_value = client

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"CacheUsageLimits": {"DataStorage": {"Maximum": 200}}}]
    }

    rollback_usage_limit()

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        CacheUsageLimits={"DataStorage": {"Maximum": 100}},
    )

    mock_wait.assert_called_once_with(
        client,
        "cache1",
    )

    mock_remove.assert_called_once()


# ----------------------------------------------------------
# State File Missing
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_usage_limit_actions.os.path.exists")
def test_rollback_usage_limit_no_state(
    mock_exists,
):

    mock_exists.return_value = False

    with pytest.raises(FileNotFoundError):
        rollback_usage_limit()
