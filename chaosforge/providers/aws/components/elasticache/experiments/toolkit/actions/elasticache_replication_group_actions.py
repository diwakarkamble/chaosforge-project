"""Reversible configuration changes for provisioned Redis replication groups."""

import json
import os
import tempfile

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "elasticache_replication_group_state.json")


def _client(region):
    return boto3.client("elasticache", region_name=region)


def _group(client, replication_group_id):
    return client.describe_replication_groups(
        ReplicationGroupId=replication_group_id
    )["ReplicationGroups"][0]


def _snapshotting_cluster_id(group):
    return group.get("SnapshottingClusterId") or next(
        iter(group.get("MemberClusters", [])), None
    )


def _save_state(replication_group_id, region, **values):
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(
            {"replication_group_id": replication_group_id, "region": region, **values},
            handle,
        )


def _load_state():
    with open(STATE_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def capture_security_groups(replication_group_id, region):
    group = _group(_client(region), replication_group_id)
    _save_state(
        replication_group_id,
        region,
        security_group_ids=[
            security_group["SecurityGroupId"]
            for security_group in group.get("SecurityGroups", [])
        ],
    )


def modify_security_groups(replication_group_id, region, target_security_group_id):
    if not target_security_group_id:
        raise ValueError("Temporary security group ID is required.")
    _client(region).modify_replication_group(
        ReplicationGroupId=replication_group_id,
        SecurityGroupIds=[target_security_group_id],
        ApplyImmediately=True,
    )


def capture_snapshot_retention(replication_group_id, region):
    group = _group(_client(region), replication_group_id)
    _save_state(
        replication_group_id,
        region,
        snapshot_retention_limit=group.get("SnapshotRetentionLimit"),
        snapshotting_cluster_id=_snapshotting_cluster_id(group),
    )


def modify_snapshot_retention(replication_group_id, region, snapshot_retention_limit):
    client = _client(region)
    retention_limit = int(snapshot_retention_limit)
    parameters = {
        "ReplicationGroupId": replication_group_id,
        "SnapshotRetentionLimit": retention_limit,
        "ApplyImmediately": True,
    }
    if retention_limit > 0:
        snapshotting_cluster_id = _snapshotting_cluster_id(
            _group(client, replication_group_id)
        )
        if not snapshotting_cluster_id:
            raise ValueError(
                "The replication group has no cache cluster available for snapshots."
            )
        parameters["SnapshottingClusterId"] = snapshotting_cluster_id
    client.modify_replication_group(**parameters)


def capture_snapshot_window(replication_group_id, region):
    group = _group(_client(region), replication_group_id)
    _save_state(replication_group_id, region, snapshot_window=group.get("SnapshotWindow"))


def modify_snapshot_window(replication_group_id, region, snapshot_window):
    _client(region).modify_replication_group(
        ReplicationGroupId=replication_group_id,
        SnapshotWindow=snapshot_window,
        ApplyImmediately=True,
    )


def restore_replication_group():
    state = _load_state()
    values = {
        key: value
        for key, value in state.items()
        if key in {
            "security_group_ids",
            "snapshot_retention_limit",
            "snapshot_window",
            "snapshotting_cluster_id",
        }
        and value is not None
    }
    if values:
        parameters = {"ReplicationGroupId": state["replication_group_id"], "ApplyImmediately": True}
        parameters.update(
            {
                "SecurityGroupIds": values["security_group_ids"]
                if "security_group_ids" in values
                else None,
                "SnapshotRetentionLimit": values.get("snapshot_retention_limit"),
                "SnapshotWindow": values.get("snapshot_window"),
                "SnapshottingClusterId": values.get("snapshotting_cluster_id")
                if values.get("snapshot_retention_limit", 0) > 0
                else None,
            }
        )
        _client(state["region"]).modify_replication_group(
            **{key: value for key, value in parameters.items() if value is not None}
        )
    os.remove(STATE_FILE)
