import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions import (
    capture_current_security_group,
    get_client,
    restore_security_group,
    update_security_group,
    wait_for_available,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.boto3.client")
def test_get_client(mock_client):

    get_client("eu-central-1")

    mock_client.assert_called_once_with(
        "elasticache",
        region_name="eu-central-1",
    )


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.json.dump")
@patch("builtins.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.get_client")
def test_capture_current_security_group(
    mock_get_client,
    mock_file,
    mock_dump,
):

    client = MagicMock()

    mock_get_client.return_value = client

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [
            {
                "SecurityGroupIds": [
                    "sg-111",
                    "sg-222",
                ]
            }
        ]
    }

    capture_current_security_group(
        "cache1",
        "eu-central-1",
    )

    client.describe_serverless_caches.assert_called_once_with(
        ServerlessCacheName="cache1"
    )

    mock_dump.assert_called_once_with(
        {
            "original_sgs": [
                "sg-111",
                "sg-222",
            ]
        },
        mock_file(),
    )


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.wait_for_available")
@patch("builtins.input")
@patch(
    "builtins.open",
    new_callable=mock_open,
    read_data=json.dumps(
        {
            "original_sgs": [
                "sg-111",
                "sg-222",
            ]
        }
    ),
)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.get_client")
def test_update_security_group(
    mock_get_client,
    mock_file,
    mock_input,
    mock_wait,
):

    mock_input.return_value = "sg-999"

    client = MagicMock()

    mock_get_client.return_value = client

    update_security_group(
        "cache1",
        "eu-central-1",
    )

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        SecurityGroupIds=["sg-999"],
    )

    mock_wait.assert_called_once_with(
        client,
        "cache1",
    )


@patch("builtins.input")
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.wait_for_available")
@patch("builtins.open", new_callable=mock_open, read_data=json.dumps({"original_sgs": ["sg-111"]}))
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.get_client")
def test_update_security_group_uses_supplied_target_without_prompt(
    mock_get_client, _mock_file, mock_wait, mock_input
):
    client = MagicMock()
    mock_get_client.return_value = client

    update_security_group("cache1", "eu-central-1", target_security_group_id="sg-999")

    mock_input.assert_not_called()
    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1", SecurityGroupIds=["sg-999"]
    )
    mock_wait.assert_called_once_with(client, "cache1")


@patch("builtins.input", return_value="")
@patch("builtins.open", new_callable=mock_open, read_data=json.dumps({"original_sgs": ["sg-111"]}))
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.get_client")
def test_update_security_group_rejects_missing_target(mock_get_client, _mock_file, _mock_input):
    mock_get_client.return_value = MagicMock()

    with pytest.raises(ValueError, match="required"):
        update_security_group("cache1", "eu-central-1", target_security_group_id="")


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.wait_for_available")
@patch(
    "builtins.open",
    new_callable=mock_open,
    read_data=json.dumps(
        {
            "original_sgs": [
                "sg-111",
                "sg-222",
            ]
        }
    ),
)
@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.get_client")
def test_restore_security_group(
    mock_get_client,
    mock_file,
    mock_wait,
):

    client = MagicMock()

    mock_get_client.return_value = client

    restore_security_group(
        "cache1",
        "eu-central-1",
    )

    client.modify_serverless_cache.assert_called_once_with(
        ServerlessCacheName="cache1",
        SecurityGroupIds=[
            "sg-111",
            "sg-222",
        ],
    )

    mock_wait.assert_called_once_with(
        client,
        "cache1",
    )


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.time.sleep")
def test_wait_for_duration(mock_sleep):

    wait_for_duration("30")

    mock_sleep.assert_called_once_with(30.0)


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.time.sleep")
def test_wait_for_available(mock_sleep):

    client = MagicMock()

    client.describe_serverless_caches.side_effect = [
        {"ServerlessCaches": [{"Status": "modifying"}]},
        {"ServerlessCaches": [{"Status": "AVAILABLE"}]},
    ]

    wait_for_available(
        client,
        "cache1",
    )

    assert client.describe_serverless_caches.call_count == 2

    mock_sleep.assert_called_once_with(15)


@patch("chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions.elasticache_security_group_actions.time.sleep")
def test_wait_for_available_immediately_available(mock_sleep):

    client = MagicMock()

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [{"Status": "available"}]
    }

    wait_for_available(
        client,
        "cache1",
    )

    mock_sleep.assert_not_called()
