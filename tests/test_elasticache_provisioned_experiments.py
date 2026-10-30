import json
from unittest.mock import MagicMock, mock_open

from chaosforge.application.metadata import get_experiment
from chaosforge.interfaces.web import app as web_app
from chaosforge.lifecycle.checks.aws_adapters import ElastiCacheReplicationGroupAdapter
from chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions import (
    elasticache_replication_group_actions as actions,
)
from chaosforge.providers.aws.discovery import AWSDiscovery


def test_elasticache_catalog_uses_the_matching_aws_resource_type_and_api():
    expected = {
        "elasticache-security-group": (
            "replication_group_id",
            "elasticache-replication-group",
            "elasticache:ModifyReplicationGroup",
        ),
        "elasticache-snapshot-retention": (
            "replication_group_id",
            "elasticache-replication-group",
            "elasticache:ModifyReplicationGroup",
        ),
        "elasticache-reboot": (
            "cache_cluster_id",
            "elasticache-cache-cluster",
            "elasticache:RebootCacheCluster",
        ),
        "elasticache-usage-limit": (
            "serverless_cache_name",
            "elasticache",
            "elasticache:ModifyServerlessCache",
        ),
        "elasticache-daily-snapshot": (
            "replication_group_id",
            "elasticache-replication-group",
            "elasticache:ModifyReplicationGroup",
        ),
    }

    for experiment_id, (name, resource_type, permission) in expected.items():
        experiment = get_experiment("elasticache", experiment_id)
        target = next(field for field in experiment["inputs"] if field["type"] == "aws_resource")

        assert (target["name"], target["resource_type"]) == (name, resource_type)
        assert permission in experiment["iam"]["modify"]

    security_group = next(
        field
        for field in get_experiment("elasticache", "elasticache-security-group")["inputs"]
        if field["name"] == "target_security_group_id"
    )
    assert (security_group["type"], security_group["resource_type"], security_group["return"]) == (
        "aws_resource",
        "security-group",
        "id",
    )


def test_elasticache_cache_cluster_discovery_returns_rebootable_clusters(monkeypatch):
    client = MagicMock()
    client.describe_cache_clusters.return_value = {
        "CacheClusters": [{"CacheClusterId": "redis-001", "ARN": "arn:cache"}]
    }
    monkeypatch.setattr("chaosforge.providers.aws.discovery.boto3.client", lambda *_args, **_kwargs: client)

    assert AWSDiscovery("eu-west-1").list_elasticache_cache_clusters() == [
        {"name": "redis-001", "arn": "arn:cache"}
    ]


def test_replication_group_actions_capture_modify_and_restore(monkeypatch):
    client = MagicMock()
    client.describe_replication_groups.return_value = {
        "ReplicationGroups": [
            {
                "SecurityGroups": [{"SecurityGroupId": "sg-original"}],
                "SnapshotRetentionLimit": 7,
                "SnapshotWindow": "03:00-04:00",
                "SnapshottingClusterId": "redis-001-001",
            }
        ]
    }
    monkeypatch.setattr(actions, "_client", lambda _region: client)
    state = {}
    monkeypatch.setattr(actions, "_save_state", lambda *_args, **values: state.update(values))

    actions.capture_security_groups("redis-001", "eu-west-1")
    assert state == {"security_group_ids": ["sg-original"]}
    actions.modify_security_groups("redis-001", "eu-west-1", "sg-temporary")
    actions.capture_snapshot_retention("redis-001", "eu-west-1")
    actions.modify_snapshot_retention("redis-001", "eu-west-1", 1)
    actions.capture_snapshot_window("redis-001", "eu-west-1")
    actions.modify_snapshot_window("redis-001", "eu-west-1", "05:00-06:00")

    assert client.modify_replication_group.call_args_list[0].kwargs == {
        "ReplicationGroupId": "redis-001",
        "SecurityGroupIds": ["sg-temporary"],
        "ApplyImmediately": True,
    }
    assert client.modify_replication_group.call_args_list[1].kwargs == {
        "ReplicationGroupId": "redis-001",
        "SnapshotRetentionLimit": 1,
        "SnapshottingClusterId": "redis-001-001",
        "ApplyImmediately": True,
    }
    assert client.modify_replication_group.call_args_list[2].kwargs["SnapshotWindow"] == "05:00-06:00"


def test_replication_group_actions_reject_missing_security_group_and_restore_state(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(actions, "_client", lambda _region: client)
    monkeypatch.setattr(actions.os, "remove", MagicMock())
    monkeypatch.setattr(
        "builtins.open",
        mock_open(
            read_data=json.dumps(
                {
                    "replication_group_id": "redis-001",
                    "region": "eu-west-1",
                    "security_group_ids": ["sg-original"],
                }
            )
        ),
    )

    try:
        actions.modify_security_groups("redis-001", "eu-west-1", "")
    except ValueError as error:
        assert str(error) == "Temporary security group ID is required."
    else:
        raise AssertionError("Expected a missing security group to be rejected")

    actions.restore_replication_group()

    client.modify_replication_group.assert_called_once_with(
        ReplicationGroupId="redis-001",
        SecurityGroupIds=["sg-original"],
        ApplyImmediately=True,
    )


def test_snapshot_retention_requires_a_member_cluster_when_enabling_snapshots(monkeypatch):
    client = MagicMock()
    client.describe_replication_groups.return_value = {"ReplicationGroups": [{}]}
    monkeypatch.setattr(actions, "_client", lambda _region: client)

    try:
        actions.modify_snapshot_retention("redis-001", "eu-west-1", 1)
    except ValueError as error:
        assert "no cache cluster" in str(error)
    else:
        raise AssertionError("Expected a missing snapshotting cluster to be rejected")

    actions.modify_snapshot_retention("redis-001", "eu-west-1", 0)
    client.modify_replication_group.assert_called_once_with(
        ReplicationGroupId="redis-001",
        SnapshotRetentionLimit=0,
        ApplyImmediately=True,
    )


def test_replication_group_action_client_and_state_helpers(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(actions.boto3, "client", MagicMock(return_value=client))
    writer = mock_open()
    monkeypatch.setattr("builtins.open", writer)

    assert actions._client("eu-west-1") is client
    actions._save_state("redis-001", "eu-west-1", snapshot_window="03:00-04:00")

    actions.boto3.client.assert_called_once_with("elasticache", region_name="eu-west-1")
    writer.assert_called_once_with(actions.STATE_FILE, "w", encoding="utf-8")


def test_replication_group_adapter_captures_recovery_configuration(monkeypatch):
    client = MagicMock()
    client.describe_replication_groups.return_value = {
        "ReplicationGroups": [
            {
                "ReplicationGroupId": "redis-001",
                "ARN": "arn:redis",
                "Status": "available",
                "SecurityGroups": [{"SecurityGroupId": "sg-1"}],
                "SnapshotRetentionLimit": 7,
                "SnapshotWindow": "03:00-04:00",
            }
        ]
    }
    monkeypatch.setattr("chaosforge.lifecycle.checks.aws_adapters.boto3.client", lambda *_args, **_kwargs: client)

    captured = ElastiCacheReplicationGroupAdapter().capture(
        {"aws_region": "eu-west-1", "replication_group_id": "redis-001"}
    )

    assert captured["configuration"] == {
        "security_group_ids": ["sg-1"],
        "snapshot_retention_limit": 7,
        "snapshot_window": "03:00-04:00",
    }


def test_replication_group_adapter_reports_missing_group(monkeypatch):
    client = MagicMock()
    client.describe_replication_groups.return_value = {"ReplicationGroups": []}
    monkeypatch.setattr("chaosforge.lifecycle.checks.aws_adapters.boto3.client", lambda *_args, **_kwargs: client)

    assert ElastiCacheReplicationGroupAdapter().capture(
        {"aws_region": "eu-west-1", "replication_group_id": "missing"}
    ) == {"exists": False, "identity": {}, "state": {}, "configuration": {}}


def test_web_resource_api_loads_provisioned_elasticache_targets(monkeypatch):
    selector = MagicMock()
    selector.get_resources.side_effect = [[{"name": "redis-001"}], [{"name": "redis-001-001"}]]
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))
    web_app.app.config.update(TESTING=True)
    client = web_app.app.test_client()

    assert client.get(
        "/api/resources/elasticache-replication-group/eu-west-1"
    ).get_json() == [{"name": "redis-001"}]
    assert client.get(
        "/api/resources/elasticache-cache-cluster/eu-west-1"
    ).get_json() == [{"name": "redis-001-001"}]
