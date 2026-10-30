from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kubernetes.client.rest import ApiException

from chaosforge.lifecycle.checks.aws_adapters import (
    DynamoDBTableAdapter,
    ElastiCacheServerlessAdapter,
    RDSInstanceAdapter,
)
from chaosforge.lifecycle.checks.eks_container_restart_adapter import (
    EKSContainerRestartAdapter,
)


def test_dynamodb_table_adapter():
    client = MagicMock()

    client.describe_table.return_value = {
        "Table": {
            "TableName": "test-table",
            "TableArn": "arn:aws:dynamodb:eu-central-1:123:table/test-table",
            "TableStatus": "ACTIVE",
            "BillingModeSummary": {
                "BillingMode": "PAY_PER_REQUEST",
            },
            "ProvisionedThroughput": {
                "ReadCapacityUnits": 5,
                "WriteCapacityUnits": 5,
            },
            "StreamSpecification": {
                "StreamEnabled": True,
            },
        }
    }

    client.describe_continuous_backups.return_value = {
        "ContinuousBackupsDescription": {
            "PointInTimeRecoveryDescription": {
                "PointInTimeRecoveryStatus": "ENABLED",
            }
        }
    }

    client.describe_time_to_live.return_value = {
        "TimeToLiveDescription": {
            "TimeToLiveStatus": "ENABLED",
        }
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = DynamoDBTableAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "table_name": "test-table",
            }
        )

    assert result["exists"] is True
    assert result["identity"]["name"] == "test-table"
    assert result["state"]["status"] == "ACTIVE"

    configuration = result["configuration"]

    assert configuration["billing_mode"] == "PAY_PER_REQUEST"
    assert configuration["read_capacity"] == 5
    assert configuration["write_capacity"] == 5
    assert configuration["stream_enabled"] is True
    assert configuration["pitr_status"] == "ENABLED"
    assert configuration["ttl_status"] == "ENABLED"


def test_rds_instance_adapter():
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "test-db",
                "DBInstanceArn": (
                    "arn:aws:rds:eu-central-1:123:"
                    "db:test-db"
                ),
                "DBInstanceStatus": "available",
                "DBInstanceClass": "db.t3.medium",
                "BackupRetentionPeriod": 7,
                "AutoMinorVersionUpgrade": True,
                "DeletionProtection": True,
                "AllocatedStorage": 100,
                "MaxAllocatedStorage": 200,
                "Iops": 3000,
                "DBParameterGroups": [
                    {
                        "DBParameterGroupName": "default.pg"
                    }
                ],
            }
        ]
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = RDSInstanceAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "db_instance_identifier": "test-db",
            }
        )

    assert result["exists"] is True
    assert result["identity"]["name"] == "test-db"
    assert result["state"]["status"] == "available"

    configuration = result["configuration"]

    assert configuration["instance_class"] == "db.t3.medium"
    assert configuration["backup_retention_period"] == 7
    assert configuration["auto_minor_version_upgrade"] is True
    assert configuration["deletion_protection"] is True
    assert configuration["allocated_storage"] == 100
    assert configuration["max_allocated_storage"] == 200
    assert configuration["iops"] == 3000
    assert configuration["parameter_groups"] == ["default.pg"]


def test_elasticache_serverless_adapter():
    client = MagicMock()

    client.describe_serverless_caches.return_value = {
        "ServerlessCaches": [
            {
                "ServerlessCacheName": "test-cache",
                "ARN": (
                    "arn:aws:elasticache:eu-central-1:123:"
                    "serverlesscache:test-cache"
                ),
                "Status": "available",
                "SnapshotRetentionLimit": 7,
                "DailySnapshotTime": "03:00",
                "SecurityGroupIds": [
                    "sg-222",
                    "sg-111",
                ],
                "CacheUsageLimits": {
                    "DataStorage": {
                        "Maximum": 10,
                    }
                },
            }
        ]
    }

    with patch(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        return_value=client,
    ):
        result = ElastiCacheServerlessAdapter().capture(
            {
                "aws_region": "eu-central-1",
                "serverless_cache_name": "test-cache",
            }
        )

    assert result["exists"] is True
    assert result["identity"]["name"] == "test-cache"
    assert result["state"]["status"] == "available"

    configuration = result["configuration"]

    assert configuration["snapshot_retention_limit"] == 7
    assert configuration["daily_snapshot_time"] == "03:00"

    assert configuration["security_group_ids"] == [
        "sg-111",
        "sg-222",
    ]

    assert configuration["cache_usage_limits"] == {
        "DataStorage": {
            "Maximum": 10,
        }
    }
def test_eks_node_adapter():
    from chaosforge.lifecycle.checks.eks_node_adapter import EKSNodeAdapter

    discovery = MagicMock()

    node = MagicMock()
    node.spec.unschedulable = True

    ready_condition = MagicMock()
    ready_condition.type = "Ready"
    ready_condition.status = "True"

    node.status.conditions = [ready_condition]

    discovery.k8s_core_api.read_node.return_value = node

    adapter = EKSNodeAdapter(discovery)

    result = adapter.capture(
        {
            "eks_cluster": "test-cluster",
            "node_name": "test-node",
        }
    )

    discovery._configure_eks_kubernetes_client.assert_called_once_with(
        "test-cluster"
    )

    discovery.k8s_core_api.read_node.assert_called_once_with(
        name="test-node"
    )

    assert result["exists"] is True
    assert result["cluster"] == "test-cluster"
    assert result["node"] == "test-node"
    assert result["unschedulable"] is True
    assert result["ready"] == "True"
    assert result["conditions"]["Ready"] == "True"

def test_eks_container_restart_adapter():
    from chaosforge.lifecycle.checks.eks_container_restart_adapter import (
        EKSContainerRestartAdapter,
    )

    discovery = MagicMock()

    original_pod = MagicMock()

    owner = MagicMock()
    owner.kind = "ReplicaSet"
    owner.name = "demo-rs"

    original_pod.metadata.owner_references = [owner]

    discovery.k8s_core_api.read_namespaced_pod.return_value = (
        original_pod
    )

    discovery.find_eks_pods_by_owner.return_value = [
        {
            "name": "demo-pod-new",
            "namespace": "default",
            "cluster": "test-cluster",
            "status": "Running",
            "owner_kind": "ReplicaSet",
            "owner_name": "demo-rs",
        }
    ]

    adapter = EKSContainerRestartAdapter(discovery)

    result = adapter.capture(
        {
            "eks_cluster": "test-cluster",
            "namespace": "default",
            "pod_name": "demo-pod-old",
        }
    )

    discovery._configure_eks_kubernetes_client.assert_called_once_with(
        "test-cluster"
    )

    discovery.k8s_core_api.read_namespaced_pod.assert_called_once_with(
        name="demo-pod-old",
        namespace="default",
    )

    discovery.find_eks_pods_by_owner.assert_called_once_with(
        "test-cluster",
        "default",
        "ReplicaSet",
        "demo-rs",
    )

    assert result["exists"] is True
    assert result["original_pod"] == "demo-pod-old"
    assert result["owner_kind"] == "ReplicaSet"
    assert result["owner_name"] == "demo-rs"
    assert result["recovered"] is True
    assert len(result["running_pods"]) == 1
    assert result["running_pods"][0]["name"] == "demo-pod-new"
def test_eks_container_restart_adapter_uses_cached_owner_after_original_pod_is_deleted():
    discovery = MagicMock()

    baseline_pod = MagicMock()
    baseline_pod.metadata.owner_references = [
        SimpleNamespace(
            kind="ReplicaSet",
            name="demo-rs",
        )
    ]

    discovery.k8s_core_api.read_namespaced_pod.return_value = baseline_pod

    discovery.find_eks_pods_by_owner.return_value = [
        {
            "name": "demo-pod-new",
            "namespace": "default",
            "cluster": "Chaos-POC-v2",
            "status": "Running",
            "owner_kind": "ReplicaSet",
            "owner_name": "demo-rs",
        }
    ]

    adapter = EKSContainerRestartAdapter(discovery)

    target = {
        "eks_cluster": "Chaos-POC-v2",
        "namespace": "default",
        "pod_name": "demo-pod-old",
    }

    baseline = adapter.capture(target)

    assert baseline["owner_kind"] == "ReplicaSet"
    assert baseline["owner_name"] == "demo-rs"

    discovery.k8s_core_api.read_namespaced_pod.side_effect = ApiException(
        status=404,
        reason="Not Found",
    )
    current = adapter.capture(target)

    assert current["owner_kind"] == "ReplicaSet"
    assert current["owner_name"] == "demo-rs"
    assert current["recovered"] is True
    assert current["exists"] is True
    assert current["running_pods"][0]["name"] == "demo-pod-new"
