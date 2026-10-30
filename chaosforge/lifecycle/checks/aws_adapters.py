from typing import Any

import boto3
from botocore.exceptions import ClientError

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class EC2ResourceAdapter(ResourceAdapter):
    name = "ec2-resource-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]

        instance_ids = target.get("instance_ids")

        if instance_ids is None:
            instance_id = target.get("instance_id")
            instance_ids = [instance_id] if instance_id else []

        if isinstance(instance_ids, str):
            instance_ids = [instance_ids]

        instance_ids = [
            str(instance_id).strip()
            for instance_id in instance_ids
            if str(instance_id).strip()
        ]

        if not instance_ids:
            raise ValueError("At least one EC2 instance ID is required.")

        client = boto3.client(
            "ec2",
            region_name=region,
        )

        response = client.describe_instances(
            InstanceIds=instance_ids,
        )

        states = {}
        block_devices = {}

        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instance_id = instance["InstanceId"]

                states[instance_id] = instance.get("State", {}).get("Name")

                attachments = []

                for mapping in instance.get(
                    "BlockDeviceMappings",
                    [],
                ):
                    ebs = mapping.get("Ebs")

                    if not ebs:
                        continue

                    attachments.append(
                        {
                            "volume_id": ebs.get("VolumeId"),
                            "device_name": mapping.get("DeviceName"),
                            "attachment_state": ebs.get("Status"),
                        }
                    )

                block_devices[instance_id] = attachments

        return {
            "exists": bool(states),
            "identity": {
                "instance_ids": instance_ids,
            },
            "state": {
                "instance_states": states,
            },
            "configuration": {
                "block_device_mappings": block_devices,
            },
        }


class EC2AutoScalingGroupAdapter(ResourceAdapter):
    name = "ec2-autoscaling-group-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        autoscaling_group = target["autoscaling_group"]

        asg_client = boto3.client(
            "autoscaling",
            region_name=region,
        )
        ec2_client = boto3.client(
            "ec2",
            region_name=region,
        )

        response = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[autoscaling_group],
        )

        groups = response.get("AutoScalingGroups", [])

        if not groups:
            return {
                "exists": False,
                "identity": {
                    "name": autoscaling_group,
                },
                "state": {},
                "configuration": {},
            }

        instances = [
            instance.get("InstanceId")
            for instance in groups[0].get("Instances", [])
            if (
                instance.get("LifecycleState") == "InService"
                and instance.get("InstanceId")
            )
        ]

        block_device_mappings = {}

        if instances:
            response = ec2_client.describe_instances(
                InstanceIds=instances,
            )

            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    instance_id = instance.get("InstanceId")

                    mappings = sorted(
                        [
                            {
                                "device_name": mapping.get("DeviceName"),
                                "volume_id": (mapping.get("Ebs", {}).get("VolumeId")),
                                "delete_on_termination": (
                                    mapping.get("Ebs", {}).get("DeleteOnTermination")
                                ),
                            }
                            for mapping in instance.get(
                                "BlockDeviceMappings",
                                [],
                            )
                            if mapping.get("Ebs")
                        ],
                        key=lambda item: (
                            item.get("device_name") or "",
                            item.get("volume_id") or "",
                        ),
                    )

                    block_device_mappings[instance_id] = mappings

        return {
            "exists": True,
            "identity": {
                "name": autoscaling_group,
            },
            "state": {
                "instance_ids": sorted(instances),
            },
            "configuration": {
                "block_device_mappings": block_device_mappings,
            },
        }


class DynamoDBTableAdapter(ResourceAdapter):
    name = "dynamodb-table-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        table_name = target["table_name"]

        client = boto3.client(
            "dynamodb",
            region_name=region,
        )

        table = client.describe_table(
            TableName=table_name,
        )["Table"]

        configuration = {
            "billing_mode": table.get(
                "BillingModeSummary",
                {},
            ).get("BillingMode"),
            "read_capacity": table.get(
                "ProvisionedThroughput",
                {},
            ).get("ReadCapacityUnits"),
            "write_capacity": table.get(
                "ProvisionedThroughput",
                {},
            ).get("WriteCapacityUnits"),
            "stream_enabled": table.get(
                "StreamSpecification",
                {},
            ).get("StreamEnabled", False),
        }

        pitr = client.describe_continuous_backups(
            TableName=table_name,
        )

        configuration["pitr_status"] = (
            pitr.get(
                "ContinuousBackupsDescription",
                {},
            )
            .get(
                "PointInTimeRecoveryDescription",
                {},
            )
            .get("PointInTimeRecoveryStatus")
        )

        ttl = client.describe_time_to_live(
            TableName=table_name,
        )

        configuration["ttl_status"] = ttl.get(
            "TimeToLiveDescription",
            {},
        ).get("TimeToLiveStatus")

        return {
            "exists": True,
            "identity": {
                "name": table.get("TableName"),
                "arn": table.get("TableArn"),
            },
            "state": {
                "status": table.get("TableStatus"),
            },
            "configuration": configuration,
        }


class RDSInstanceAdapter(ResourceAdapter):
    name = "rds-instance-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        identifier = target["db_instance_identifier"]

        client = boto3.client(
            "rds",
            region_name=region,
        )

        instance = client.describe_db_instances(
            DBInstanceIdentifier=identifier,
        )["DBInstances"][0]

        parameter_groups = [
            item.get("DBParameterGroupName")
            for item in instance.get(
                "DBParameterGroups",
                [],
            )
        ]

        return {
            "exists": True,
            "identity": {
                "name": instance.get("DBInstanceIdentifier"),
                "arn": instance.get("DBInstanceArn"),
            },
            "state": {
                "status": instance.get("DBInstanceStatus"),
            },
            "configuration": {
                "instance_class": instance.get("DBInstanceClass"),
                "backup_retention_period": instance.get("BackupRetentionPeriod"),
                "auto_minor_version_upgrade": instance.get("AutoMinorVersionUpgrade"),
                "deletion_protection": instance.get("DeletionProtection"),
                "allocated_storage": instance.get("AllocatedStorage"),
                "max_allocated_storage": instance.get("MaxAllocatedStorage"),
                "iops": instance.get("Iops"),
                "parameter_groups": parameter_groups,
            },
        }


class ElastiCacheClusterAdapter(ResourceAdapter):
    name = "elasticache-cluster-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        cache_cluster_id = target["cache_cluster_id"]

        client = boto3.client(
            "elasticache",
            region_name=region,
        )

        response = client.describe_cache_clusters(
            CacheClusterId=cache_cluster_id,
        )

        clusters = response.get("CacheClusters", [])

        if not clusters:
            return {
                "exists": False,
                "identity": {
                    "name": cache_cluster_id,
                },
                "state": {},
                "configuration": {},
            }

        cluster = clusters[0]

        return {
            "exists": True,
            "identity": {
                "name": cluster.get("CacheClusterId"),
                "arn": cluster.get("ARN"),
            },
            "state": {
                "status": cluster.get("CacheClusterStatus"),
            },
            "configuration": {
                "engine": cluster.get("Engine"),
                "engine_version": cluster.get("EngineVersion"),
                "num_cache_nodes": cluster.get("NumCacheNodes"),
                "preferred_availability_zone": cluster.get("PreferredAvailabilityZone"),
            },
        }


class ElastiCacheServerlessAdapter(ResourceAdapter):
    name = "elasticache-serverless-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        cache_name = target["serverless_cache_name"]

        client = boto3.client(
            "elasticache",
            region_name=region,
        )

        cache = client.describe_serverless_caches(
            ServerlessCacheName=cache_name,
        )["ServerlessCaches"][0]

        return {
            "exists": True,
            "identity": {
                "name": cache.get("ServerlessCacheName"),
                "arn": cache.get("ARN"),
            },
            "state": {
                "status": cache.get("Status"),
            },
            "configuration": {
                "snapshot_retention_limit": cache.get("SnapshotRetentionLimit"),
                "daily_snapshot_time": cache.get("DailySnapshotTime"),
                "security_group_ids": sorted(
                    cache.get(
                        "SecurityGroupIds",
                        [],
                    )
                ),
                "cache_usage_limits": cache.get(
                    "CacheUsageLimits",
                    {},
                ),
            },
        }


class ElastiCacheReplicationGroupAdapter(ResourceAdapter):
    name = "elasticache-replication-group-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        client = boto3.client("elasticache", region_name=target["aws_region"])
        groups = client.describe_replication_groups(
            ReplicationGroupId=target["replication_group_id"]
        ).get("ReplicationGroups", [])
        if not groups:
            return {"exists": False, "identity": {}, "state": {}, "configuration": {}}
        group = groups[0]
        return {
            "exists": True,
            "identity": {"name": group.get("ReplicationGroupId"), "arn": group.get("ARN")},
            "state": {"status": group.get("Status")},
            "configuration": {
                "security_group_ids": sorted(
                    security_group.get("SecurityGroupId", security_group)
                    for security_group in group.get("SecurityGroups", [])
                ),
                "snapshot_retention_limit": group.get("SnapshotRetentionLimit"),
                "snapshot_window": group.get("SnapshotWindow"),
            },
        }


class ECSServiceAdapter(ResourceAdapter):
    name = "ecs-service-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        cluster = target["ecs_cluster"]
        service = target["ecs_service"]

        client = boto3.client(
            "ecs",
            region_name=region,
        )

        response = client.describe_services(
            cluster=cluster,
            services=[service],
        )

        services = response.get("services", [])

        if not services:
            return {
                "exists": False,
                "identity": {
                    "cluster": cluster,
                    "name": service,
                },
                "state": {},
                "configuration": {},
            }

        ecs_service = services[0]

        task_definition_arn = ecs_service.get("taskDefinition")

        task_definition = {}

        if task_definition_arn:
            task_definition_response = client.describe_task_definition(
                taskDefinition=task_definition_arn,
            )

            task_definition = task_definition_response.get("taskDefinition", {})

        container_definitions = task_definition.get(
            "containerDefinitions",
            [],
        )

        containers = []

        for container in container_definitions:
            containers.append(
                {
                    "name": container.get("name"),
                    "cpu": container.get("cpu"),
                    "memory": container.get("memory"),
                    "memory_reservation": container.get("memoryReservation"),
                }
            )

        return {
            "exists": True,
            "identity": {
                "cluster": cluster,
                "name": service,
                "arn": ecs_service.get("serviceArn"),
            },
            "state": {
                "status": ecs_service.get("status"),
                "running_count": ecs_service.get("runningCount"),
                "pending_count": ecs_service.get("pendingCount"),
                "desired_count": ecs_service.get("desiredCount"),
            },
            "configuration": {
                "desired_count": ecs_service.get("desiredCount"),
                "task_definition": task_definition_arn,
                "task_definition_revision": (task_definition.get("revision")),
                "task_definition_cpu": (task_definition.get("cpu")),
                "task_definition_memory": (task_definition.get("memory")),
                "containers": containers,
            },
        }


class ELBTargetGroupAdapter(ResourceAdapter):
    name = "elb-target-group-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        target_group_arn = target["target_group"]

        client = boto3.client(
            "elbv2",
            region_name=region,
        )

        response = client.describe_target_groups(
            TargetGroupArns=[target_group_arn],
        )

        groups = response.get(
            "TargetGroups",
            [],
        )

        if not groups:
            return {
                "exists": False,
                "identity": {
                    "arn": target_group_arn,
                },
                "state": {},
                "configuration": {},
            }

        group = groups[0]

        attributes_response = client.describe_target_group_attributes(
            TargetGroupArn=target_group_arn,
        )

        attributes = {
            item["Key"]: item.get("Value")
            for item in attributes_response.get(
                "Attributes",
                [],
            )
        }

        health_response = client.describe_target_health(
            TargetGroupArn=target_group_arn,
        )

        registered_targets = sorted(
            [
                {
                    "id": description.get("Target", {}).get("Id"),
                    "port": description.get("Target", {}).get("Port"),
                    "availability_zone": description.get("Target", {}).get(
                        "AvailabilityZone"
                    ),
                }
                for description in health_response.get(
                    "TargetHealthDescriptions",
                    [],
                )
            ],
            key=lambda item: (
                item.get("id") or "",
                item.get("port") or 0,
            ),
        )

        return {
            "exists": True,
            "identity": {
                "arn": target_group_arn,
                "name": group.get("TargetGroupName"),
            },
            "state": {
                "target_type": group.get("TargetType"),
            },
            "configuration": {
                "deregistration_delay": attributes.get(
                    "deregistration_delay.timeout_seconds"
                ),
                "cross_zone": attributes.get("load_balancing.cross_zone.enabled"),
                "stickiness_enabled": attributes.get("stickiness.enabled"),
                "registered_targets": registered_targets,
            },
        }


class ELBLoadBalancerAdapter(ResourceAdapter):
    name = "elb-load-balancer-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        load_balancer_arn = target["load_balancer"]

        client = boto3.client(
            "elbv2",
            region_name=region,
        )

        response = client.describe_load_balancers(
            LoadBalancerArns=[load_balancer_arn],
        )

        load_balancers = response.get(
            "LoadBalancers",
            [],
        )

        if not load_balancers:
            return {
                "exists": False,
                "identity": {
                    "arn": load_balancer_arn,
                },
                "state": {},
                "configuration": {},
            }

        load_balancer = load_balancers[0]

        attributes_response = client.describe_load_balancer_attributes(
            LoadBalancerArn=load_balancer_arn,
        )

        attributes = {
            item["Key"]: item.get("Value")
            for item in attributes_response.get(
                "Attributes",
                [],
            )
        }

        return {
            "exists": True,
            "identity": {
                "arn": load_balancer_arn,
                "name": load_balancer.get("LoadBalancerName"),
            },
            "state": {
                "state": load_balancer.get(
                    "State",
                    {},
                ).get("Code"),
            },
            "configuration": {
                "attributes": attributes,
            },
        }


class ELBListenerAdapter(ResourceAdapter):
    name = "elb-listener-adapter"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        listener_arn = target["listener"]

        client = boto3.client(
            "elbv2",
            region_name=region,
        )

        response = client.describe_listeners(
            ListenerArns=[listener_arn],
        )

        listeners = response.get(
            "Listeners",
            [],
        )

        if not listeners:
            return {
                "exists": False,
                "identity": {
                    "arn": listener_arn,
                },
                "state": {},
                "configuration": {},
            }

        listener = listeners[0]

        return {
            "exists": True,
            "identity": {
                "arn": listener_arn,
            },
            "state": {},
            "configuration": {
                "port": listener.get("Port"),
                "protocol": listener.get("Protocol"),
                "ssl_policy": listener.get("SslPolicy"),
                "default_actions": listener.get(
                    "DefaultActions",
                    [],
                ),
            },
        }


class APIGatewayStageAdapter(ResourceAdapter):
    name = "api-gateway-stage"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        rest_api_id = target.get("rest_api_id", target.get("api_gateway"))
        stage_name = target.get("stage_name", target.get("stage"))
        if not rest_api_id or not stage_name:
            raise ValueError("API Gateway and Stage are required for lifecycle checks.")

        client = boto3.client(
            "apigateway",
            region_name=region,
        )

        response = client.get_stage(
            restApiId=rest_api_id,
            stageName=stage_name,
        )

        return {
            "exists": True,
            "identity": {
                "rest_api_id": rest_api_id,
                "stage": stage_name,
            },
            "state": {
                "deployment_id": response.get("deploymentId"),
                "cache_cluster_enabled": response.get("cacheClusterEnabled"),
            },
            "configuration": {
                "access_log_settings": response.get("accessLogSettings"),
                "cache_cluster_enabled": response.get("cacheClusterEnabled"),
                "cache_cluster_size": response.get("cacheClusterSize"),
                "tracing_enabled": response.get("tracingEnabled"),
                "variables": response.get(
                    "variables",
                    {},
                ),
                "method_settings": response.get(
                    "methodSettings",
                    {},
                ),
            },
        }


class S3BucketAdapter(ResourceAdapter):
    name = "s3-bucket"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        # Current S3 catalog metadata uses bucket_name. Keep the previous
        # adapter key for persisted campaigns created before that contract.
        bucket = target.get("bucket_name") or target["bucket"]

        client = boto3.client(
            "s3",
            region_name=region,
        )

        try:
            client.head_bucket(
                Bucket=bucket,
            )
        except ClientError as exc:
            return {
                "exists": False,
                "identity": {
                    "bucket": bucket,
                },
                "state": {},
                "configuration": {},
                "error": str(exc),
            }

        configuration = {}

        try:
            encryption = client.get_bucket_encryption(
                Bucket=bucket,
            )
            configuration["encryption"] = encryption.get(
                "ServerSideEncryptionConfiguration"
            )
        except ClientError:
            configuration["encryption"] = None

        try:
            versioning = client.get_bucket_versioning(
                Bucket=bucket,
            )
            configuration["versioning"] = versioning.get("Status")
        except ClientError:
            configuration["versioning"] = None

        try:
            public_access = client.get_public_access_block(
                Bucket=bucket,
            )
            configuration["public_access_block"] = public_access.get(
                "PublicAccessBlockConfiguration"
            )
        except ClientError:
            configuration["public_access_block"] = None

        try:
            lifecycle = client.get_bucket_lifecycle_configuration(
                Bucket=bucket,
            )
            configuration["lifecycle"] = lifecycle.get(
                "Rules",
                [],
            )
        except ClientError:
            configuration["lifecycle"] = []

        try:
            policy = client.get_bucket_policy(
                Bucket=bucket,
            )
            configuration["policy"] = policy.get("Policy")
        except ClientError:
            configuration["policy"] = None

        return {
            "exists": True,
            "identity": {
                "bucket": bucket,
            },
            "state": {},
            "configuration": configuration,
        }


class SNSTopicAdapter(ResourceAdapter):
    name = "sns-topic"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        topic_arn = target["topic_arn"]

        client = boto3.client(
            "sns",
            region_name=region,
        )

        attributes = client.get_topic_attributes(
            TopicArn=topic_arn,
        ).get("Attributes", {})

        return {
            "exists": True,
            "identity": {
                "topic_arn": topic_arn,
            },
            "state": {
                "owner": attributes.get("Owner"),
            },
            "configuration": {
                "policy": attributes.get("Policy"),
                "delivery_policy": attributes.get("DeliveryPolicy"),
                "display_name": attributes.get("DisplayName"),
                "kms_master_key_id": attributes.get("KmsMasterKeyId"),
            },
        }


class SNSSubscriptionAdapter(ResourceAdapter):
    name = "sns-subscription"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        subscription_arn = target["subscription_arn"]

        client = boto3.client(
            "sns",
            region_name=region,
        )

        try:
            response = client.get_subscription_attributes(
                SubscriptionArn=subscription_arn,
            )
        except ClientError as exc:
            error_code = exc.response.get(
                "Error",
                {},
            ).get("Code")

            if error_code in {
                "NotFound",
                "NotFoundException",
            }:
                return {
                    "exists": False,
                    "identity": {
                        "subscription_arn": subscription_arn,
                    },
                    "state": {},
                    "configuration": {},
                }

            raise

        attributes = response.get("Attributes", {})

        return {
            "exists": True,
            "identity": {
                "subscription_arn": subscription_arn,
            },
            "state": {},
            "configuration": {
                "filter_policy": attributes.get("FilterPolicy"),
                "filter_policy_scope": attributes.get("FilterPolicyScope"),
                "delivery_policy": attributes.get("DeliveryPolicy"),
                "raw_message_delivery": attributes.get("RawMessageDelivery"),
                "redrive_policy": attributes.get("RedrivePolicy"),
            },
        }


class VPCResourceAdapter(ResourceAdapter):
    name = "vpc-resource"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        region = target["aws_region"]
        resource_type = target["resource_type"]

        client = boto3.client(
            "ec2",
            region_name=region,
        )

        if resource_type == "security-group":
            return self._security_group(
                client,
                target["security_group_id"],
            )

        if resource_type == "route-table":
            return self._route_table(
                client,
                target["route_table_id"],
            )

        if resource_type == "network-acl":
            return self._network_acl(
                client,
                target["network_acl_id"],
            )

        if resource_type == "internet-gateway":
            return self._internet_gateway(
                client,
                target["internet_gateway_id"],
            )

        raise ValueError(f"Unsupported VPC resource type: {resource_type}")

    def _security_group(
        self,
        client,
        security_group_id,
    ):
        response = client.describe_security_groups(
            GroupIds=[security_group_id],
        )

        groups = response.get("SecurityGroups", [])

        if not groups:
            return {
                "exists": False,
                "identity": {
                    "id": security_group_id,
                },
                "state": {},
                "configuration": {},
            }

        group = groups[0]

        return {
            "exists": True,
            "identity": {
                "id": group.get("GroupId"),
                "name": group.get("GroupName"),
                "vpc_id": group.get("VpcId"),
            },
            "state": {},
            "configuration": {
                "description": group.get("Description"),
                "ingress": group.get(
                    "IpPermissions",
                    [],
                ),
                "egress": group.get(
                    "IpPermissionsEgress",
                    [],
                ),
            },
        }

    def _route_table(
        self,
        client,
        route_table_id,
    ):
        response = client.describe_route_tables(
            RouteTableIds=[route_table_id],
        )

        tables = response.get("RouteTables", [])

        if not tables:
            return {
                "exists": False,
                "identity": {
                    "id": route_table_id,
                },
                "state": {},
                "configuration": {},
            }

        table = tables[0]

        return {
            "exists": True,
            "identity": {
                "id": table.get("RouteTableId"),
                "vpc_id": table.get("VpcId"),
            },
            "state": {},
            "configuration": {
                "routes": table.get(
                    "Routes",
                    [],
                ),
                "associations": table.get(
                    "Associations",
                    [],
                ),
                "propagating_vgws": table.get(
                    "PropagatingVgws",
                    [],
                ),
            },
        }

    def _network_acl(
        self,
        client,
        network_acl_id,
    ):
        response = client.describe_network_acls(
            NetworkAclIds=[network_acl_id],
        )

        acls = response.get("NetworkAcls", [])

        if not acls:
            return {
                "exists": False,
                "identity": {
                    "id": network_acl_id,
                },
                "state": {},
                "configuration": {},
            }

        acl = acls[0]

        return {
            "exists": True,
            "identity": {
                "id": acl.get("NetworkAclId"),
                "vpc_id": acl.get("VpcId"),
            },
            "state": {},
            "configuration": {
                "entries": acl.get(
                    "Entries",
                    [],
                ),
                "associations": acl.get(
                    "Associations",
                    [],
                ),
            },
        }

    def _internet_gateway(
        self,
        client,
        internet_gateway_id,
    ):
        response = client.describe_internet_gateways(
            InternetGatewayIds=[internet_gateway_id],
        )

        gateways = response.get(
            "InternetGateways",
            [],
        )

        if not gateways:
            return {
                "exists": False,
                "identity": {
                    "id": internet_gateway_id,
                },
                "state": {},
                "configuration": {},
            }

        gateway = gateways[0]

        return {
            "exists": True,
            "identity": {
                "id": gateway.get("InternetGatewayId"),
            },
            "state": {},
            "configuration": {
                "attachments": gateway.get(
                    "Attachments",
                    [],
                ),
                "tags": gateway.get(
                    "Tags",
                    [],
                ),
            },
        }
