"""Live environment and target checks for executable campaign YAML."""

from dataclasses import dataclass, field

import boto3

from chaosforge.application.campaigns.duplicates import duplicate_experiment_indexes
from chaosforge.catalog import ExperimentCatalog
from chaosforge.providers.aws.discovery import AWSDiscovery
from chaosforge.providers.azure.components.registry import (
    COMPONENT_RESOURCE_TYPES,
    COMPONENT_RESOURCES,
    list_component_resources,
)


@dataclass(frozen=True)
class CampaignPreflightResult:
    ready: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    targets: tuple[dict, ...] = field(default_factory=tuple)


class CampaignPreflightService:
    def __init__(self, catalog=None):
        self.catalog = catalog or ExperimentCatalog()

    def preflight(self, campaign, document, identity):
        if document.get("template"):
            return CampaignPreflightResult(
                ready=False,
                errors=(
                    "Campaign YAML is a template. Supply environment identity and concrete targets "
                    "before importing it.",
                ),
            )

        provider = campaign.cloud_provider
        environment = document.get("environment", {})
        errors = self._identity_errors(provider, environment, identity)
        targets = []
        if not errors:
            if provider == "azure":
                errors.extend(self._normalize_azure_resource_names(campaign, environment))
            if not errors:
                for experiment in campaign.experiments:
                    target, error = self._resolve_target(experiment)
                    if error:
                        errors.append(f"{experiment.id}: {error}")
                    elif target:
                        targets.append(target)
        return CampaignPreflightResult(
            ready=not errors,
            errors=tuple(errors),
            targets=tuple(targets),
        )

    @staticmethod
    def _identity_errors(provider, environment, identity):
        identity_key = "account_id" if provider == "aws" else "subscription_id"
        expected = str(environment.get(identity_key) or "").strip()
        actual = str(identity.get(identity_key) or "").strip()
        if not expected or not actual or expected != actual:
            return [
                f"Campaign expects {provider} {identity_key.replace('_', ' ')} "
                f"'{expected or 'missing'}', but the active identity is "
                f"'{actual or 'unavailable'}'."
            ]
        return []

    def _resolve_target(self, experiment):
        if experiment.service == "lambda":
            return CampaignPreflightService._resolve_lambda(experiment)
        if experiment.service == "azure_redis":
            return CampaignPreflightService._resolve_azure_redis(experiment)
        from chaosforge.providers.azure.chaos_studio.classic_faults import CLASSIC_FAULTS

        if (experiment.service, experiment.id) in CLASSIC_FAULTS:
            return CampaignPreflightService._resolve_azure_classic(experiment)
        if experiment.service in COMPONENT_RESOURCES:
            return CampaignPreflightService._resolve_azure_component(experiment)
        if experiment.service == "aks":
            return self._resolve_aks_context(experiment)
        if experiment.service == "fis":
            return self._resolve_fis(experiment)
        return self._resolve_aws_resources(experiment)

    def _normalize_azure_resource_names(self, campaign, environment):
        """Resolve YAML ``resource_name`` aliases to canonical ARM resource IDs."""
        from chaosforge.providers.azure.discovery import AzureResourceDiscovery

        errors = []
        subscription_id = str(environment.get("subscription_id") or "").strip()
        for experiment in campaign.experiments:
            variables = experiment.variables
            resource_name = str(variables.get("resource_name") or "").strip()
            if not resource_name:
                continue
            resource_id = str(variables.get("resource_id") or "").strip()
            if resource_id:
                errors.append(
                    f"{experiment.id}: provide either resource_id or resource_name, not both."
                )
                continue
            if experiment.service not in COMPONENT_RESOURCES:
                errors.append(
                    f"{experiment.id}: resource_name is not supported for {experiment.service}."
                )
                continue
            metadata = self.catalog.get_experiment(experiment.service, experiment.id) or {}
            if not any(
                field.get("name") == "resource_id"
                and field.get("type") == "azure_component_resource"
                for field in metadata.get("inputs", [])
            ):
                errors.append(
                    f"{experiment.id}: resource_name is not supported; this experiment uses a different target field."
                )
                continue
            resource_group = str(variables.get("resource_group") or "").strip()
            resolved_subscription = str(variables.get("subscription_id") or subscription_id).strip()
            if not resource_group or not resolved_subscription:
                errors.append(
                    f"{experiment.id}: resource_name requires subscription_id and resource_group."
                )
                continue
            try:
                resources = list_component_resources(
                    AzureResourceDiscovery(resolved_subscription), experiment.service, resource_group
                )
            except Exception as exc:  # noqa: BLE001 - report name-resolution failures before execution.
                errors.append(f"{experiment.id}: could not resolve resource_name '{resource_name}': {exc}")
                continue
            matches = [item for item in resources if str(item.get("name") or "").casefold() == resource_name.casefold()]
            if not matches:
                errors.append(
                    f"{experiment.id}: {COMPONENT_RESOURCES[experiment.service][0].rstrip('s')} "
                    f"'{resource_name}' was not found in resource group '{resource_group}'."
                )
                continue
            if len(matches) > 1:
                errors.append(
                    f"{experiment.id}: resource_name '{resource_name}' matched multiple "
                    f"{COMPONENT_RESOURCES[experiment.service][0]} in resource group '{resource_group}'."
                )
                continue
            resolved_id = str(matches[0].get("id") or "")
            if not resolved_id.startswith("/"):
                resource_type = COMPONENT_RESOURCE_TYPES[experiment.service]
                resolved_id = (
                    f"/subscriptions/{resolved_subscription}/resourceGroups/{resource_group}"
                    f"/providers/{resource_type}/{matches[0]['name']}"
                )
            variables["subscription_id"] = resolved_subscription
            variables["resource_id"] = resolved_id
            variables.pop("resource_name", None)
        duplicates = duplicate_experiment_indexes(campaign.experiments)
        for duplicate_index, original_index in duplicates:
            experiment = campaign.experiments[duplicate_index]
            errors.append(
                f"{experiment.id}: duplicates experiment {original_index + 1} after Azure target resolution."
            )
        return errors

    @staticmethod
    def _resolve_azure_component(experiment):
        variables = experiment.variables
        resource_id = str(variables.get("resource_id") or "").strip()
        if not resource_id:
            return None, "resource_id is required for Azure target preflight."
        return {
            "experiment_id": experiment.id,
            "service": experiment.service,
            "name": resource_id,
            "resource_group": variables.get("resource_group", ""),
        }, None

    def _resolve_aws_resources(self, experiment, definition=None):
        region = self._aws_region(experiment.variables)
        definition = definition or self.catalog.get_experiment(experiment.service, experiment.id)
        if definition is None:
            return None, f"Experiment '{experiment.id}' is not registered for target preflight."
        discovery = AWSDiscovery(region)
        resolved = []
        for input_definition in definition.get("inputs", []):
            if input_definition.get("type") != "aws_resource":
                continue
            value = experiment.variables.get(input_definition["name"])
            if value in (None, ""):
                if input_definition.get("required"):
                    return None, f"{input_definition['name']} is required for target preflight."
                continue
            try:
                resources = self._aws_resources_for_field(
                    discovery, input_definition, experiment.variables
                )
            except Exception as exc:  # noqa: BLE001
                return None, f"Could not resolve {input_definition['name']} '{value}': {exc}"
            returned_key = input_definition.get("return", "id")
            if not any(resource.get(returned_key) == value for resource in resources):
                return None, f"{input_definition['name']} '{value}' was not found."
            resolved.append(input_definition["name"])
        return {
            "experiment_id": experiment.id,
            "service": experiment.service,
            "name": experiment.id,
            "region": region,
            "resolved_inputs": resolved,
        }, None

    @staticmethod
    def _resolve_azure_classic(experiment):
        from azure.identity import DefaultAzureCredential

        from chaosforge.providers.azure.chaos_studio.classic import AzureChaosIdentityService
        from chaosforge.providers.azure.chaos_studio.classic_faults import fault_details

        variables = experiment.variables
        required = ("subscription_id", "resource_group", "resource_id", "chaos_identity_id")
        missing = [name for name in required if not variables.get(name)]
        if missing:
            return None, f"{', '.join(missing)} is required for Azure Chaos Studio preflight."
        try:
            role_name = fault_details(experiment.service, experiment.id)[2]
            readiness = AzureChaosIdentityService(
                variables["subscription_id"], DefaultAzureCredential()
            ).readiness(variables["chaos_identity_id"], variables["resource_id"], role_name)
        except Exception as exc:  # noqa: BLE001 - identity readiness is an execution blocker.
            return None, f"Could not verify Azure Chaos identity: {exc}"
        if readiness["status"] != "ready":
            return None, readiness.get("message", "Azure Chaos identity is not ready.")
        return {
            "experiment_id": experiment.id,
            "service": experiment.service,
            "name": variables["resource_id"],
            "resource_group": variables["resource_group"],
            "chaos_identity_id": variables["chaos_identity_id"],
        }, None

    @staticmethod
    def _aws_region(variables):
        region = variables.get("aws_region") or variables.get("region")
        if region:
            return region
        for value in variables.values():
            if isinstance(value, str) and value.startswith("arn:aws:"):
                parts = value.split(":", 5)
                if len(parts) > 3 and parts[3]:
                    return parts[3]
        return boto3.Session().region_name or "us-east-1"

    @staticmethod
    def _aws_resources_for_field(discovery, field, variables):
        resource_type = field["resource_type"]
        parent = variables.get(field.get("parent", ""))
        mapping = {
            "apigateway": lambda: discovery.list_apigateway_apis(),
            "apigateway-stage": lambda: discovery.list_apigateway_stages(parent),
            "autoscaling-group": lambda: discovery.list_auto_scaling_groups(),
            "chaos-physical-machine": lambda: discovery.list_chaos_physical_machines(parent),
            "dynamodb": lambda: discovery.list_dynamodb_tables(),
            "ebs-volume": lambda: discovery.list_ec2_ebs_volumes(parent),
            "ebs-volume-available": lambda: discovery.list_available_ec2_ebs_volumes(parent),
            "ec2": lambda: discovery.list_ec2_instances(),
            "ecs": lambda: discovery.list_ecs_clusters(),
            "ecs-service": lambda: discovery.list_ecs_services(parent),
            "eks": lambda: discovery.list_eks_clusters(),
            "eks-container": lambda: discovery.list_eks_containers(
                variables["eks_cluster"],
                parent,
                pod_name=variables.get("pod", ""),
                deployment=variables.get("deployment", ""),
            ),
            "eks-deployment": lambda: discovery.list_eks_deployments(variables["eks_cluster"], parent),
            "eks-namespace": lambda: discovery.list_eks_namespaces(parent),
            "eks-node": lambda: discovery.list_eks_nodes(parent),
            "eks-pod": lambda: discovery.list_eks_pods(variables["eks_cluster"], parent),
            "eks-volume": lambda: discovery.list_eks_volumes(variables["eks_cluster"], variables["namespace"], parent),
            "elb": lambda: discovery.list_elb_load_balancers(),
            "elb-target": lambda: discovery.list_elb_targets(parent),
            "internet-gateway": lambda: discovery.list_internet_gateways(),
            "lambda": lambda: discovery.list_lambda_functions(),
            "network-acl": lambda: discovery.list_network_acls(),
            "network-acl-rule": lambda: discovery.list_network_acl_rules(parent),
            "rds": lambda: discovery.list_rds_instances(),
            "rds-instance-class": lambda: discovery.list_rds_instance_classes(parent),
            "route": lambda: discovery.list_routes(parent),
            "route-table": lambda: discovery.list_route_tables(),
            "s3": lambda: discovery.list_s3_buckets(),
            "security-group": lambda: discovery.list_security_groups(),
            "security-group-rule": lambda: discovery.list_security_group_rules(parent),
            "elasticache-replication-group": lambda: discovery.list_elasticache_replication_groups(),
            "elasticache-cache-cluster": lambda: discovery.list_elasticache_cache_clusters(),
            "sns": lambda: discovery.list_sns_topics(),
            "sns_subscription": lambda: discovery.list_sns_subscriptions(),
        }
        if resource_type == "elasticache":
            client = boto3.client("elasticache", region_name=discovery.region)
            resources = discovery.list_elasticache_serverless()
            resources.extend(
                {"name": cache["CacheClusterId"], "id": cache["CacheClusterId"]}
                for cache in client.describe_cache_clusters().get("CacheClusters", [])
            )
            return resources
        if resource_type == "ebs-volume-asg-available":
            client = boto3.client("autoscaling", region_name=discovery.region)
            groups = client.describe_auto_scaling_groups(
                AutoScalingGroupNames=[parent]
            ).get("AutoScalingGroups", [])
            instance_id = next(
                (
                    instance.get("InstanceId")
                    for group in groups
                    for instance in group.get("Instances", [])
                    if instance.get("LifecycleState") == "InService"
                    and instance.get("HealthStatus") == "Healthy"
                ),
                None,
            )
            if not instance_id:
                return []
            return discovery.list_available_ec2_ebs_volumes(instance_id)
        if resource_type in {"elb-target-group", "elb-listener"}:
            client = boto3.client("elbv2", region_name=discovery.region)
            if resource_type == "elb-target-group":
                return [
                    {"name": group["TargetGroupName"], "id": group["TargetGroupArn"], "arn": group["TargetGroupArn"]}
                    for group in client.describe_target_groups().get("TargetGroups", [])
                ]
            return [
                {"name": listener["ListenerArn"], "id": listener["ListenerArn"], "arn": listener["ListenerArn"]}
                for load_balancer in client.describe_load_balancers().get("LoadBalancers", [])
                for listener in client.describe_listeners(LoadBalancerArn=load_balancer["LoadBalancerArn"]).get("Listeners", [])
            ]
        try:
            return mapping[resource_type]()
        except KeyError as exc:
            raise LookupError(f"No target resolver is registered for '{resource_type}'.") from exc

    @staticmethod
    def _resolve_fis(experiment):
        variables = experiment.variables
        region = CampaignPreflightService._aws_region(variables)
        client = boto3.client("fis", region_name=region)
        if experiment.id in {"fis-start-template", "fis-delete-template"}:
            template_id = variables.get("experiment_template_id") or variables.get("template_id")
            try:
                client.get_experiment_template(id=template_id)
            except Exception as exc:  # noqa: BLE001
                return None, f"FIS template '{template_id}' was not found: {exc}"
        elif experiment.id == "fis-stop-experiment":
            experiment_id = variables.get("experiment_id")
            try:
                client.get_experiment(id=experiment_id)
            except Exception as exc:  # noqa: BLE001
                return None, f"FIS experiment '{experiment_id}' was not found: {exc}"
        elif experiment.id == "fis-create-experiment":
            role_arn = variables.get("role_arn")
            target_arn = variables.get("target_arn")
            if not role_arn or not target_arn:
                return None, "role_arn and target_arn are required for target preflight."
            try:
                boto3.client("iam").get_role(RoleName=role_arn.rsplit("/", 1)[-1])
            except Exception as exc:  # noqa: BLE001
                return None, f"FIS role '{role_arn}' was not found: {exc}"
            target_service = variables.get("service_id")
            if target_service and target_service != "s3":
                target = type(
                    "FISTarget",
                    (),
                    {
                        "id": "fis-create-target",
                        "service": target_service,
                        "variables": {"aws_region": region, "target_arn": target_arn},
                    },
                )()
                target_definition = {
                    "inputs": [
                        {
                            "name": "target_arn",
                            "type": "aws_resource",
                            "resource_type": target_service,
                            "return": "arn",
                            "required": True,
                        }
                    ]
                }
                _, target_error = CampaignPreflightService()._resolve_aws_resources(
                    target, definition=target_definition
                )
                if target_error:
                    return None, target_error
        return {"experiment_id": experiment.id, "service": "fis", "name": experiment.id, "region": region}, None

    @staticmethod
    def _resolve_lambda(experiment):
        function_name = experiment.variables.get("lambda_name")
        region = experiment.variables.get("aws_region")
        if not function_name or not region:
            return None, "lambda_name and aws_region are required for target preflight."
        try:
            response = boto3.client("lambda", region_name=region).get_function(
                FunctionName=function_name
            )
        except Exception as exc:  # noqa: BLE001
            return None, f"Lambda '{function_name}' was not found in {region}: {exc}"
        configuration = response.get("Configuration", {})
        return {
            "experiment_id": experiment.id,
            "service": "lambda",
            "name": configuration.get("FunctionName", function_name),
            "arn": configuration.get("FunctionArn", ""),
            "region": region,
        }, None

    @staticmethod
    def _resolve_azure_redis(experiment):
        from azure.identity import DefaultAzureCredential

        from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
            AzureRedisChaosIdentityService,
            redis_target_id,
        )
        from chaosforge.providers.azure.discovery import AzureResourceDiscovery

        variables = experiment.variables
        subscription_id = variables.get("subscription_id")
        resource_group = variables.get("resource_group")
        redis_name = variables.get("redis_name")
        if not subscription_id or not resource_group or not redis_name:
            return None, "subscription_id, resource_group, and redis_name are required for target preflight."
        try:
            caches = AzureResourceDiscovery(subscription_id).list_redis_caches(resource_group)
        except Exception as exc:  # noqa: BLE001
            return None, f"Could not resolve Redis cache '{redis_name}': {exc}"
        if redis_name not in {cache["id"] for cache in caches}:
            return None, f"Redis cache '{redis_name}' was not found in resource group '{resource_group}'."
        if experiment.id == "azure-redis-reboot" and not variables.get("chaos_identity_id"):
            return None, "chaos_identity_id is required for Azure Redis Reboot."
        if experiment.id == "azure-redis-reboot":
            target_id = redis_target_id(subscription_id, resource_group, redis_name)
            try:
                readiness = AzureRedisChaosIdentityService(
                    subscription_id, DefaultAzureCredential()
                ).readiness(variables["chaos_identity_id"], target_id)
            except Exception as exc:  # noqa: BLE001 - identity readiness is an execution blocker.
                return None, f"Could not verify Azure Redis chaos identity: {exc}"
            if readiness["status"] != "ready":
                return None, readiness.get("message", "Azure Redis chaos identity is not ready.")
        return {
            "experiment_id": experiment.id,
            "service": "azure_redis",
            "name": redis_name,
            "resource_group": resource_group,
            "chaos_identity_id": variables.get("chaos_identity_id", ""),
        }, None

    @staticmethod
    def _resolve_aks_context(experiment):
        from chaosforge.providers.azure.components.aks.discovery import AzureAKSDiscovery

        context = experiment.variables.get("aks_context")
        if not context:
            return None, "aks_context is required for target preflight."
        try:
            contexts = AzureAKSDiscovery().list_contexts()
        except Exception as exc:  # noqa: BLE001
            return None, f"Could not resolve AKS context '{context}': {exc}"
        if context not in contexts:
            return None, f"AKS context '{context}' was not found in the active kubeconfig."
        return {
            "experiment_id": experiment.id,
            "service": "aks",
            "name": context,
        }, None
