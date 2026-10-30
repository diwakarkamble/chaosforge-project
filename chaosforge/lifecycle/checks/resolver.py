from importlib import import_module

from chaosforge.lifecycle.checks.aws_adapters import (
    APIGatewayStageAdapter,
    DynamoDBTableAdapter,
    EC2AutoScalingGroupAdapter,
    EC2ResourceAdapter,
    ECSServiceAdapter,
    ElastiCacheClusterAdapter,
    ElastiCacheReplicationGroupAdapter,
    ElastiCacheServerlessAdapter,
    ELBListenerAdapter,
    ELBLoadBalancerAdapter,
    ELBTargetGroupAdapter,
    RDSInstanceAdapter,
    S3BucketAdapter,
    SNSSubscriptionAdapter,
    SNSTopicAdapter,
    VPCResourceAdapter,
)
from chaosforge.lifecycle.checks.azure_arm_adapter import AzureARMResourceAdapter
from chaosforge.lifecycle.checks.azure_redis_adapter import AzureRedisAdapter
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.kubernetes_chaos import (
    SharedChaosMeshValidationCheck,
    equivalent_aks_experiment,
)
from chaosforge.lifecycle.checks.lambda_adapter import LambdaResourceAdapter
from chaosforge.lifecycle.checks.validations import (
    EKSContainerRestartCheck,
    EKSDeploymentCheck,
    EKSNodeCheck,
)


class CheckResolver:
    """
    Resolves the lifecycle validation check for an experiment.

    This resolver is separate from the existing experiment registry.
    It only determines whether an experiment has lifecycle validation
    support.
    """

    def resolve(self, experiment, discovery=None):
        """
        Return the lifecycle check for the experiment.

        Experiments without lifecycle support return None so that
        the existing execution path remains unchanged.
        """

        variables = getattr(experiment, "variables", {}) or {}

        azure_arm_experiments = {
            "azure_postgres_flexible": {
                "azure-postgres-flexible-toolkit-stop": False,
                "azure-postgres-flexible-restart": False,
                "azure-postgres-flexible-firewall-disruption": True,
            },
            "azure_app_service": {
                "azure-app-service-toolkit-stop": False,
                "azure-app-service-slot-swap": True,
            },
            "azure_functions": {
                "azure-functions-stop-app-service": True,
                "azure-functions-slot-swap": True,
            },
            "azure_key_vault": {
                "azure-key-vault-deny-access": True,
                "azure-key-vault-disable-certificate": False,
                "azure-key-vault-increment-certificate-version": False,
                "azure-key-vault-update-certificate-policy": False,
                "azure-key-vault-secret-disable": True,
            },
            "azure_cosmos_db": {
                "azure-cosmos-db-failover": False,
                "azure-cosmos-db-public-access-disruption": True,
            },
            "azure_event_hub": {
                "azure-event-hub-state": False,
                "azure-event-hub-public-access-disruption": True,
            },
            "azure_vm": {
                "azure-vm-redeploy": True,
                "azure-vm-shutdown": True,
                "azure-vm-toolkit-reboot": False,
                "azure-vm-boot-diagnostics-toggle": True,
            },
            "azure_vmss": {
                "azure-vmss-shutdown": True,
                "azure-vmss-shutdown-2-0": True,
                "azure-vmss-toolkit-reboot": False,
                "azure-vmss-overprovision-toggle": True,
            },
            "azure_container_apps": {
                "azure-container-app-revision-restart": False,
                "azure-container-app-traffic-shift": True,
                "azure-container-app-scale-zero": True,
            },
        }
        recovery_supported = azure_arm_experiments.get(
            getattr(experiment, "service", ""), {}
        ).get(experiment.id)
        if recovery_supported is not None:
            predicates = {
                "resource_exists": lambda current, baseline: current.get("exists") is True,
            }
            if experiment.id == "azure-event-hub-public-access-disruption":
                predicates["public_access_restored"] = lambda current, baseline: (
                    current.get("configuration", {}).get("public_network_access")
                    == baseline.get("configuration", {}).get("public_network_access")
                )
            elif recovery_supported:
                predicates["provisioning_state_restored"] = (
                    lambda current, baseline: current.get("state", {}).get(
                        "provisioning_state"
                    )
                    == baseline.get("state", {}).get("provisioning_state")
                )
            return CommonResourceCheck(
                AzureARMResourceAdapter(),
                predicates=predicates,
                name=f"{experiment.id}-lifecycle",
                recovery_supported=recovery_supported,
                preconditions={
                    "Azure resource must exist": lambda snapshot: (
                        snapshot.get("exists") is True
                    ),
                    "Azure resource provisioning must be complete": lambda snapshot: (
                        snapshot.get("state", {}).get("provisioning_state")
                        in {None, "Succeeded"}
                    ),
                },
            )

        if getattr(experiment, "service", "") == "azure_redis":
            predicates = {
                "azure-redis-reboot": {
                    "resource_exists": lambda current, baseline: current.get("exists") is True,
                    "cache_available": lambda current, baseline: (
                        current.get("state", {}).get("provisioning_state") == "Succeeded"
                    ),
                },
                "azure-redis-flush": {
                    "resource_exists": lambda current, baseline: current.get("exists") is True,
                    "cache_available": lambda current, baseline: (
                        current.get("state", {}).get("provisioning_state") == "Succeeded"
                    ),
                },
                "azure-redis-access-disruption": {
                    "resource_exists": lambda current, baseline: current.get("exists") is True,
                    "public_access_restored": lambda current, baseline: (
                        current.get("configuration", {}).get("public_network_access")
                        == baseline.get("configuration", {}).get("public_network_access")
                    ),
                },
            }.get(experiment.id)
            if predicates is not None:
                return CommonResourceCheck(
                    AzureRedisAdapter(),
                    predicates=predicates,
                    name=f"{experiment.id}-lifecycle",
                    report_field=(
                        "reboot_type" if experiment.id == "azure-redis-reboot" else "redis_name",
                        "state.provisioning_state",
                        "",
                    ),
                    recovery_supported=experiment.id != "azure-redis-flush",
                )

        fis_ec2_experiment = (
            experiment.id == "fis-create-experiment"
            and variables.get("service_id") == "ec2"
        )
        fis_experiment_id = variables.get("experiment_id")

        if (
            experiment.id == "fis-create-experiment"
            and variables.get("service_id") == "eks"
            and fis_experiment_id == "pod-delete"
        ):
            if discovery is None:
                raise ValueError("AWS discovery is required for EKS FIS pod lifecycle checks.")
            proxy = type(
                "EKSFISPodDelete",
                (),
                {"id": "fis-eks-pod-delete", "variables": variables},
            )()
            return SharedChaosMeshValidationCheck(discovery, proxy)

        if (
            experiment.id == "fis-create-experiment"
            and variables.get("service_id") == "lambda"
            and fis_experiment_id in {"invocation-delay", "invocation-error", "http-response"}
        ):
            return import_module(
                "chaosforge.providers.aws.components.lambda.experiments.fis.checks"
            ).LambdaFISCheck()

        if fis_ec2_experiment and fis_experiment_id in {
            "stop-instances",
            "reboot-instances",
        }:
            return CommonResourceCheck(
                EC2ResourceAdapter(),
                predicates={
                    "resource_exists": lambda current, baseline: (
                        current.get("exists") is True
                    ),
                    "instance_state_restored": lambda current, baseline: (
                        current.get("state", {}).get("instance_states")
                        == baseline.get("state", {}).get("instance_states")
                    ),
                },
                name=f"fis-{fis_experiment_id}-lifecycle",
                preconditions={
                    "all target instances must be running": lambda snapshot: (
                        bool(
                            snapshot.get("state", {}).get(
                                "instance_states", {}
                            )
                        )
                        and all(
                            state == "running"
                            for state in snapshot.get("state", {}).get(
                                "instance_states", {}
                            ).values()
                        )
                    ),
                },
            )

        if fis_ec2_experiment and fis_experiment_id == "terminate-instances":
            return CommonResourceCheck(
                EC2ResourceAdapter(),
                predicates={
                    "resource_exists": lambda current, baseline: (
                        current.get("exists") is True
                    ),
                    "instances_terminated": lambda current, baseline: all(
                        state == "terminated"
                        for state in current.get("state", {}).get(
                            "instance_states", {}
                        ).values()
                    ),
                },
                name="fis-terminate-instances-lifecycle",
                recovery_supported=False,
                validation_timeout_seconds=300,
            )

        if experiment.id == "eks-replica-reduction":
            if discovery is None:
                raise ValueError(
                    "AWS discovery is required for "
                    "EKS replica reduction lifecycle checks."
                )

            return EKSDeploymentCheck(discovery)

        if experiment.id == "eks-container-restart":
            if discovery is None:
                raise ValueError(
                    "AWS discovery is required for "
                    "EKS container restart lifecycle checks."
                )

            return EKSContainerRestartCheck(discovery)

        if experiment.id in {
            "eks-node-cordon",
            "eks-node-drain",
        }:
            if discovery is None:
                raise ValueError(
                    "AWS discovery is required for "
                    "EKS node lifecycle checks."
                )

            return EKSNodeCheck(discovery)

        # AKS node experiments perform their own target-specific prechecks,
        # cleanup, and recovery checks in the provider lifecycle. They do not
        # have a workload selector for the shared pod validation profile.
        if experiment.id in {
            "aks-node-drain",
            "aks-node-taint",
            "aks-node-cpu-stress",
            "aks-node-memory-pressure",
            "aks-node-notready",
            "aks-node-zone-failure",
        }:
            return None

        validation_experiment_id = equivalent_aks_experiment(experiment.id, variables)
        if validation_experiment_id:
            is_native_aks = experiment.id.startswith("aks-")
            if not is_native_aks and discovery is None:
                raise ValueError(
                    "AWS discovery is required for Chaos Mesh lifecycle checks."
                )

            return SharedChaosMeshValidationCheck(discovery, experiment)

        ec2_predicates = {
            "ec2-ebs-volume-detach": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "attachments_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "block_device_mappings"
                    )
                    == baseline.get("configuration", {}).get(
                        "block_device_mappings"
                    )
                ),
            },
            "ec2-ebs-volume-attach": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "attachments_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "block_device_mappings"
                    )
                    == baseline.get("configuration", {}).get(
                        "block_device_mappings"
                    )
                ),
            },
        }

        if experiment.id == "ec2-incremental-instance-stop":
            return CommonResourceCheck(
                EC2ResourceAdapter(),
                predicates={
                    "resource_exists": lambda current, baseline: (
                        current.get("exists") is True
                    ),
                    "instances_stopped": lambda current, baseline: all(
                        state == "stopped"
                        for state in current.get(
                            "state", {}
                        ).get(
                            "instance_states", {}
                        ).values()
                    ),
                },
                name=f"{experiment.id}-lifecycle",
                recovery_supported=False,
            )

        if experiment.id in {
            "ec2-ebs-volume-detach-asg",
            "ec2-ebs-volume-attach-asg",
        }:
            return CommonResourceCheck(
                EC2AutoScalingGroupAdapter(),
                predicates={
                    "resource_exists": lambda current, baseline: (
                        current.get("exists") is True
                    ),
                    "block_device_mappings_restored": lambda current, baseline: (
                        current.get("configuration", {}).get(
                            "block_device_mappings"
                        )
                        == baseline.get("configuration", {}).get(
                            "block_device_mappings"
                        )
                    ),
                },
                name=f"{experiment.id}-lifecycle",
            )

        predicates = ec2_predicates.get(experiment.id)

        if predicates is not None:
            return CommonResourceCheck(
                EC2ResourceAdapter(),
                predicates=predicates,
                name=f"{experiment.id}-lifecycle",
            )

        dynamodb_predicates = {
            "dynamodb-capacity": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "read_capacity_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "read_capacity"
                    )
                    == baseline.get("configuration", {}).get(
                        "read_capacity"
                    )
                ),
                "write_capacity_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "write_capacity"
                    )
                    == baseline.get("configuration", {}).get(
                        "write_capacity"
                    )
                ),
            },
            "dynamodb-pitr": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "pitr_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "pitr_status"
                    )
                    == baseline.get("configuration", {}).get(
                        "pitr_status"
                    )
                ),
            },
            "dynamodb-stream": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "stream_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "stream_enabled"
                    )
                    == baseline.get("configuration", {}).get(
                        "stream_enabled"
                    )
                ),
            },
            "dynamodb-ttl": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "ttl_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "ttl_status"
                    )
                    == baseline.get("configuration", {}).get(
                        "ttl_status"
                    )
                ),
            },
        }

        predicates = dynamodb_predicates.get(
            experiment.id
        )

        if predicates is not None:
            return CommonResourceCheck(
                DynamoDBTableAdapter(),
                predicates=predicates,
                name=f"{experiment.id}-lifecycle",
            )


        rds_predicates = {
            "rds-parameter-group": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "parameter_groups_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "parameter_groups"
                    )
                    == baseline.get("configuration", {}).get(
                        "parameter_groups"
                    )
                ),
            },
            "rds-instance-class": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "instance_class_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "instance_class"
                    )
                    == baseline.get("configuration", {}).get(
                        "instance_class"
                    )
                ),
            },
            "rds-backup-retention": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "backup_retention_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "backup_retention_period"
                    )
                    == baseline.get("configuration", {}).get(
                        "backup_retention_period"
                    )
                ),
            },
            "rds-auto-minor-version-upgrade": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "auto_minor_upgrade_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "auto_minor_version_upgrade"
                    )
                    == baseline.get("configuration", {}).get(
                        "auto_minor_version_upgrade"
                    )
                ),
            },
            "rds-deletion-protection": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "deletion_protection_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "deletion_protection"
                    )
                    == baseline.get("configuration", {}).get(
                        "deletion_protection"
                    )
                ),
            },
            "rds-storage-autoscaling": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "max_storage_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "max_allocated_storage"
                    )
                    == baseline.get("configuration", {}).get(
                        "max_allocated_storage"
                    )
                ),
            },
            "rds-iops": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "iops_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "iops"
                    )
                    == baseline.get("configuration", {}).get(
                        "iops"
                    )
                ),
            },
        }

        predicates = rds_predicates.get(
            experiment.id
        )

        if predicates is not None:
            return CommonResourceCheck(
                RDSInstanceAdapter(),
                predicates=predicates,
                name=f"{experiment.id}-lifecycle",
            )

        elasticache_predicates = {
            "elasticache-reboot": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "cluster_available": lambda current, baseline: (
                    current.get("state", {}).get("status")
                    == baseline.get("state", {}).get("status")
                    == "available"
                ),
            },
            "elasticache-security-group": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "security_groups_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "security_group_ids"
                    )
                    == baseline.get("configuration", {}).get(
                        "security_group_ids"
                    )
                ),
            },
            "elasticache-snapshot-retention": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "snapshot_retention_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "snapshot_retention_limit"
                    )
                    == baseline.get("configuration", {}).get(
                        "snapshot_retention_limit"
                    )
                ),
            },
            "elasticache-usage-limit": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "usage_limits_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "cache_usage_limits"
                    )
                    == baseline.get("configuration", {}).get(
                        "cache_usage_limits"
                    )
                ),
            },
            "elasticache-daily-snapshot": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "snapshot_window_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "snapshot_window"
                    )
                    == baseline.get("configuration", {}).get(
                        "snapshot_window"
                    )
                ),
            },
        }

        predicates = elasticache_predicates.get(
            experiment.id
        )

        if predicates is not None:
            adapter = (
                ElastiCacheClusterAdapter()
                if experiment.id == "elasticache-reboot"
                else (
                    ElastiCacheServerlessAdapter()
                    if experiment.id == "elasticache-usage-limit"
                    else ElastiCacheReplicationGroupAdapter()
                )
            )

            return CommonResourceCheck(
                adapter,
                predicates=predicates,
                name=f"{experiment.id}-lifecycle",
            )

        ecs_predicates = {
            "ecs-cpu-modification": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "cpu_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "task_definition_cpu"
                    )
                    == baseline.get("configuration", {}).get(
                        "task_definition_cpu"
                    )
                ),
            },
            "ecs-desired-task-count": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "desired_count_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "desired_count"
                    )
                    == baseline.get("configuration", {}).get(
                        "desired_count"
                    )
                ),
            },
            "ecs-force-deployment": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "service_available": lambda current, baseline: (
                    current.get("state", {}).get("status")
                    == "ACTIVE"
                ),
            },
            "ecs-memory-modification": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "memory_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "task_definition_memory"
                    )
                    == baseline.get("configuration", {}).get(
                        "task_definition_memory"
                    )
                ),
            },
            "ecs-task-definition-rollback": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "task_definition_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "task_definition"
                    )
                    == baseline.get("configuration", {}).get(
                        "task_definition"
                    )
                ),
            },
        }

        predicates = ecs_predicates.get(experiment.id)

        if predicates is not None:
            return CommonResourceCheck(
                ECSServiceAdapter(),
                predicates=predicates,
                name=f"{experiment.id}-lifecycle",
            )


        elb_predicates = {
            "elb-target-deregistration": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "targets_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "registered_targets"
                    )
                    == baseline.get("configuration", {}).get(
                        "registered_targets"
                    )
                ),
            },
            "elb-cross-zone": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "cross_zone_restored": lambda current, baseline: (
                    current.get("configuration", {}).get(
                        "cross_zone"
                    )
                    == baseline.get("configuration", {}).get(
                        "cross_zone"
                    )
                ),
            },
            "elb-deregistration-delay": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "deregistration_delay_restored": (
                    lambda current, baseline: (
                        current.get("configuration", {}).get(
                            "deregistration_delay"
                        )
                        == baseline.get("configuration", {}).get(
                            "deregistration_delay"
                        )
                    )
                ),
            },
            "elb-health-check": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
            },
            "elb-listener": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "listener_configuration_restored": (
                    lambda current, baseline: (
                        current.get("configuration")
                        == baseline.get("configuration")
                    )
                ),
            },
            "elb-load-balancer": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "load_balancer_attributes_restored": (
                    lambda current, baseline: (
                        current.get("configuration", {}).get(
                            "attributes"
                        )
                        == baseline.get("configuration", {}).get(
                            "attributes"
                        )
                    )
                ),
            },
            "elb-target-group": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "target_group_configuration_restored": (
                    lambda current, baseline: (
                        current.get("configuration")
                        == baseline.get("configuration")
                    )
                ),
            },
        }

        if experiment.id in {
            "elb-cross-zone",
            "elb-deregistration-delay",
            "elb-health-check",
        }:
            adapter = ELBTargetGroupAdapter()
        elif experiment.id == "elb-listener":
            adapter = ELBListenerAdapter()
        elif experiment.id == "elb-load-balancer":
            adapter = ELBLoadBalancerAdapter()
        elif experiment.id == "elb-target-group":
            adapter = ELBTargetGroupAdapter()
        else:
            adapter = None

        if adapter is not None:
            return CommonResourceCheck(
                adapter,
                predicates=elb_predicates[experiment.id],
                name=f"{experiment.id}-lifecycle",
            )

        api_gateway_predicates = {
            "api-gateway-access-logging": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "access_logging_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "access_log_settings"
                    )
                    == baseline.get("configuration", {}).get(
                        "access_log_settings"
                    ),
            },

            "api-gateway-stage-cache": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "cache_restored": lambda current, baseline:
                    (
                        current.get("configuration", {}).get(
                            "cache_cluster_enabled"
                        )
                        == baseline.get("configuration", {}).get(
                            "cache_cluster_enabled"
                        )
                        and
                        current.get("configuration", {}).get(
                            "cache_cluster_size"
                        )
                        == baseline.get("configuration", {}).get(
                            "cache_cluster_size"
                        )
                    ),
            },

            "api-gateway-cache-ttl": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "cache_ttl_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "method_settings"
                    )
                    == baseline.get("configuration", {}).get(
                        "method_settings"
                    ),
            },

            "api-gateway-stage-throttling": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "throttling_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "method_settings"
                    )
                    == baseline.get("configuration", {}).get(
                        "method_settings"
                    ),
            },

            "api-gateway-stage-variables": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "variables_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "variables"
                    )
                    == baseline.get("configuration", {}).get(
                        "variables"
                    ),
            },

            "api-gateway-xray-tracing": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "tracing_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "tracing_enabled"
                    )
                    == baseline.get("configuration", {}).get(
                        "tracing_enabled"
                    ),
            },
        }

        api_gateway_experiment_ids = {
            "api-gateway-access-logging",
            "api-gateway-stage-cache",
            "api-gateway-cache-ttl",
            "api-gateway-stage-throttling",
            "api-gateway-stage-variables",
            "api-gateway-xray-tracing",
        }

        if experiment.id in api_gateway_experiment_ids:
            return CommonResourceCheck(
                APIGatewayStageAdapter(),
                predicates=api_gateway_predicates[experiment.id],
                name=f"{experiment.id}-lifecycle",
            )

        s3_predicates = {
            "s3-bucket-policy": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "policy_restored": lambda current, baseline:
                    current.get("configuration", {}).get("policy")
                    == baseline.get("configuration", {}).get("policy"),
            },

            "s3-encryption": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "encryption_restored": lambda current, baseline:
                    current.get("configuration", {}).get("encryption")
                    == baseline.get("configuration", {}).get("encryption"),
            },

            "s3-lifecycle": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "lifecycle_restored": lambda current, baseline:
                    current.get("configuration", {}).get("lifecycle")
                    == baseline.get("configuration", {}).get("lifecycle"),
            },

            "s3-public-access": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "public_access_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "public_access_block"
                    )
                    == baseline.get("configuration", {}).get(
                        "public_access_block"
                    ),
            },

            "s3-versioning": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "versioning_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "versioning"
                    )
                    == baseline.get("configuration", {}).get(
                        "versioning"
                    ),
            },
        }

        if experiment.id in s3_predicates:
            preconditions = {}
            if experiment.id == "s3-public-access":
                preconditions["at least one Public Access Block control must be enabled"] = (
                    lambda snapshot: any(
                        (snapshot.get("configuration", {}).get("public_access_block") or {}).values()
                    )
                )
            return CommonResourceCheck(
                S3BucketAdapter(),
                predicates=s3_predicates[experiment.id],
                name=f"{experiment.id}-lifecycle",
                preconditions=preconditions,
            )


        apigateway_predicates = {
            "apigateway-stage-throttling": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "throttling_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "method_settings"
                    )
                    == baseline.get("configuration", {}).get(
                        "method_settings"
                    ),
            },

            "apigateway-stage-cache": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "cache_restored": lambda current, baseline:
                    (
                        current.get("configuration", {}).get(
                            "cache_cluster_enabled"
                        )
                        == baseline.get("configuration", {}).get(
                            "cache_cluster_enabled"
                        )
                        and
                        current.get("configuration", {}).get(
                            "cache_cluster_size"
                        )
                        == baseline.get("configuration", {}).get(
                            "cache_cluster_size"
                        )
                    ),
            },

            "apigateway-stage-cache-ttl": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "cache_ttl_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "method_settings"
                    )
                    == baseline.get("configuration", {}).get(
                        "method_settings"
                    ),
            },

            "apigateway-access-logging": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "access_logging_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "access_log_settings"
                    )
                    == baseline.get("configuration", {}).get(
                        "access_log_settings"
                    ),
            },

            "apigateway-xray": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "xray_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "tracing_enabled"
                    )
                    == baseline.get("configuration", {}).get(
                        "tracing_enabled"
                    ),
            },

            "apigateway-stage-variables": {
                "resource_exists": lambda current, baseline:
                    current.get("exists") is True,
                "variables_restored": lambda current, baseline:
                    current.get("configuration", {}).get(
                        "variables"
                    )
                    == baseline.get("configuration", {}).get(
                        "variables"
                    ),
            },
        }

        if experiment.id in apigateway_predicates:
            return CommonResourceCheck(
                APIGatewayStageAdapter(),
                predicates=apigateway_predicates[experiment.id],
                name=f"{experiment.id}-lifecycle",
            )

        lambda_predicates = {
            "lambda-memory": {
                "exists": lambda current, baseline: (
                    current.get("exists") == baseline.get("exists")
                ),
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "memory_size": lambda current, baseline: (
                    current.get("configuration", {}).get("memory_size")
                    == baseline.get("configuration", {}).get("memory_size")
                ),
            },
            "lambda-timeout": {
                "exists": lambda current, baseline: (
                    current.get("exists") == baseline.get("exists")
                ),
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "timeout": lambda current, baseline: (
                    current.get("configuration", {}).get("timeout")
                    == baseline.get("configuration", {}).get("timeout")
                ),
            },
            "lambda-concurrency": {
                "exists": lambda current, baseline: (
                    current.get("exists") == baseline.get("exists")
                ),
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "reserved_concurrency": lambda current, baseline: (
                    current.get("concurrency", {}).get(
                        "reserved_concurrency"
                    )
                    == baseline.get("concurrency", {}).get(
                        "reserved_concurrency"
                    )
                ),
            },
            "lambda-provisioned-concurrency": {
                "exists": lambda current, baseline: (
                    current.get("exists") == baseline.get("exists")
                ),
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "provisioned_concurrency": lambda current, baseline: (
                    current.get("provisioned_concurrency", {}).get(
                        "requested"
                    )
                    == baseline.get("provisioned_concurrency", {}).get(
                        "requested"
                    )
                ),
            },
            "lambda-retry": {
                "exists": lambda current, baseline: (
                    current.get("exists") == baseline.get("exists")
                ),
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "maximum_retry_attempts": lambda current, baseline: (
                    current.get("async_invoke", {}).get(
                        "maximum_retry_attempts"
                    )
                    == baseline.get("async_invoke", {}).get(
                        "maximum_retry_attempts"
                    )
                ),
            },
            "lambda-storm-injector": {
                "exists": lambda current, baseline: (
                    current.get("exists") == baseline.get("exists")
                ),
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "lambda_state": lambda current, baseline: (
                    current.get("state", {}).get("state")
                    == baseline.get("state", {}).get("state")
                ),
            },
        }

        predicates = lambda_predicates.get(experiment.id)

        if predicates is not None:
            report_fields = {
                "lambda-memory": (
                    "target_memory_size",
                    "configuration.memory_size",
                    "MB",
                ),
                "lambda-timeout": (
                    "target_timeout",
                    "configuration.timeout",
                    "seconds",
                ),
                "lambda-concurrency": (
                    "target_concurrency",
                    "concurrency.reserved_concurrency",
                    "",
                ),
                "lambda-provisioned-concurrency": (
                    "target_provisioned_concurrency",
                    "provisioned_concurrency.requested",
                    "",
                ),
                "lambda-retry": (
                    "target_retry_attempts",
                    "async_invoke.maximum_retry_attempts",
                    "",
                ),
            }

            return CommonResourceCheck(
                LambdaResourceAdapter(),
                predicates=predicates,
                name=f"{experiment.id}-lifecycle",
                report_field=report_fields.get(
                    experiment.id
                ),
            )

        # ------------------------------------------------------------------
        # SNS lifecycle checks
        # ------------------------------------------------------------------

        sns_predicates = {
            "sns-publish-message": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
            },

            "sns-topic-policy": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "policy_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("policy")
                    == baseline.get("configuration", {}).get("policy")
                ),
            },

            "sns-subscription-filter": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "filter_policy_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("filter_policy")
                    == baseline.get("configuration", {}).get("filter_policy")
                ),
            },

            "sns-delivery-policy": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "delivery_policy_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("delivery_policy")
                    == baseline.get("configuration", {}).get("delivery_policy")
                ),
            },
        }

        if experiment.id in sns_predicates:
            if experiment.id == "sns-subscription-filter":
                adapter = SNSSubscriptionAdapter()
            else:
                adapter = SNSTopicAdapter()

            return CommonResourceCheck(
                adapter,
                predicates=sns_predicates[experiment.id],
                name=f"{experiment.id}-lifecycle",
            )

        if experiment.id == "sns-delete-subscription":
            return CommonResourceCheck(
                SNSSubscriptionAdapter(),
                predicates={
                    "subscription_deleted": lambda current, baseline: (
                        baseline.get("exists") is True
                        and current.get("exists") is False
                    ),
                },
                name="sns-delete-subscription-lifecycle",
                recovery_supported=False,
            )

        # ------------------------------------------------------------------
        # VPC lifecycle checks
        # ------------------------------------------------------------------

        vpc_predicates = {
            "vpc-security-group": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "ingress_rules_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("ingress")
                    == baseline.get("configuration", {}).get("ingress")
                ),
                "egress_rules_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("egress")
                    == baseline.get("configuration", {}).get("egress")
                ),
            },

            "vpc-route-table": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "routes_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("routes")
                    == baseline.get("configuration", {}).get("routes")
                ),
                "associations_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("associations")
                    == baseline.get("configuration", {}).get("associations")
                ),
            },

            "vpc-network-acl": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "entries_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("entries")
                    == baseline.get("configuration", {}).get("entries")
                ),
                "associations_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("associations")
                    == baseline.get("configuration", {}).get("associations")
                ),
            },

            "vpc-internet-gateway": {
                "resource_exists": lambda current, baseline: (
                    current.get("exists") is True
                ),
                "attachments_restored": lambda current, baseline: (
                    current.get("configuration", {}).get("attachments")
                    == baseline.get("configuration", {}).get("attachments")
                ),
            },
        }

        vpc_resource_types = {
            "vpc-security-group": "security-group",
            "vpc-route-table": "route-table",
            "vpc-network-acl": "network-acl",
            "vpc-internet-gateway": "internet-gateway",
        }

        if experiment.id in vpc_predicates:
            adapter = VPCResourceAdapter()

            # VPCResourceAdapter requires the resource type in the
            # lifecycle target. The experiment id determines it.
            original_capture = adapter.capture

            def capture_with_resource_type(
                target,
                _capture=original_capture,
                _resource_type=vpc_resource_types[experiment.id],
            ):
                lifecycle_target = dict(target)
                lifecycle_target["resource_type"] = _resource_type
                return _capture(lifecycle_target)

            adapter.capture = capture_with_resource_type

            return CommonResourceCheck(
                adapter,
                predicates=vpc_predicates[experiment.id],
                name=f"{experiment.id}-lifecycle",
            )

        return None
