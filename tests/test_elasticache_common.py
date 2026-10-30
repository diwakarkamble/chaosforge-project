from unittest.mock import MagicMock, patch

from chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_common import (
    get_client,
    wait_for_serverless_cache_available,
)

# ----------------------------------------------------------
# Get Client
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_common.boto3.client")
def test_get_client(mock_client):

    get_client("eu-central-1")

    mock_client.assert_called_once_with(
        "elasticache",
        region_name="eu-central-1",
    )


# ----------------------------------------------------------
# Already Available
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_common.time.sleep")
def test_wait_for_serverless_cache_available_immediately(
    mock_sleep,
):

    client = MagicMock()

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [
            {
                "Status": "available",
            }
        ]
    }

    wait_for_serverless_cache_available(
        client,
        "cache-1",
    )

    client.describe_serverless_caches.assert_called_once_with(
        ServerlessCacheName="cache-1"
    )

    mock_sleep.assert_not_called()


# ----------------------------------------------------------
# Wait Until Available
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_common.time.sleep")
def test_wait_for_serverless_cache_available_waits(
    mock_sleep,
):

    client = MagicMock()

    client.describe_serverless_caches.side_effect = [
        {
            "ServerlessCaches": [
                {
                    "Status": "modifying",
                }
            ]
        },
        {
            "ServerlessCaches": [
                {
                    "Status": "creating",
                }
            ]
        },
        {
            "ServerlessCaches": [
                {
                    "Status": "available",
                }
            ]
        },
    ]

    wait_for_serverless_cache_available(
        client,
        "cache-1",
    )

    assert client.describe_serverless_caches.call_count == 3

    mock_sleep.assert_called_with(15)

    assert mock_sleep.call_count == 2


# ----------------------------------------------------------
# Mixed Case Status
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_common.time.sleep")
def test_wait_for_serverless_cache_available_case_insensitive(
    mock_sleep,
):

    client = MagicMock()

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [
            {
                "Status": "AvAiLaBlE",
            }
        ]
    }

    wait_for_serverless_cache_available(
        client,
        "cache-1",
    )

    mock_sleep.assert_not_called()
