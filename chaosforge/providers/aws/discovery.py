import os
import subprocess
import tempfile

import boto3
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException

from chaosforge.interfaces.cli.interactive.ui.spinner import spinner
from chaosforge.interfaces.cli.interactive.ui.status import info


class AWSDiscovery:
    def __init__(self, region):

        self.region = region

        #
        # Kubernetes API clients
        #
        self.k8s_core_api = None
        self.k8s_apps_api = None
        self.k8s_custom_api = None
        self.k8s_api_client = None

        # EKS kubeconfig/context used by Kubernetes clients and Helm.
        self.eks_kubeconfig_path = None
        self.eks_kube_context = None
        self.eks_kubeconfig_temporary = False


    # ----------------------------------------------------------
    # AWS Authentication
    # ----------------------------------------------------------

    def verify_aws_credentials(self):
        """
        Verify that the current AWS credentials are valid.

        Returns:
            dict: AWS identity information when authentication succeeds.

        Raises:
            RuntimeError: When AWS credentials are missing or invalid.
        """
        try:
            sts_client = boto3.client("sts", region_name=self.region)
            identity = sts_client.get_caller_identity()

            return {
                "authenticated": True,
                "account_id": identity.get("Account"),
                "arn": identity.get("Arn"),
                "user_id": identity.get("UserId"),
                "region": self.region,
            }

        except Exception as exc:
            raise RuntimeError(
                f"AWS authentication failed for region "
                f"'{self.region}': {exc}"
            ) from exc

    # ----------------------------------------------------------
    # EKS Kubernetes Client
    # ----------------------------------------------------------

    def _configure_eks_kubernetes_client(self, cluster_name):
        """
        Configure Kubernetes clients for the requested EKS cluster.

        Reuse an existing kubeconfig context when available. If the
        requested cluster is not present in the current kubeconfig,
        generate a temporary kubeconfig using AWS CLI.
        """
        selected_context = None
        kubeconfig_path = None

        try:
            contexts, _ = config.list_kube_config_contexts()

            for context in contexts or []:
                name = context.get("name")
                cluster = context.get("context", {}).get("cluster", "")

                if (
                    name == cluster_name or cluster == cluster_name or cluster.endswith((f"/{cluster_name}", f":cluster/{cluster_name}"))
                ):
                    selected_context = name
                    break

        except Exception:
            contexts = []

        if selected_context is None:
            fd, kubeconfig_path = tempfile.mkstemp(
                prefix="chaosforge-eks-",
                suffix=".config",
            )
            os.close(fd)

            try:
                subprocess.run(
                    [
                        "aws",
                        "eks",
                        "update-kubeconfig",
                        "--name",
                        cluster_name,
                        "--region",
                        self.region,
                        "--kubeconfig",
                        kubeconfig_path,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )

                temp_contexts, _ = config.list_kube_config_contexts(
                    config_file=kubeconfig_path
                )

                for context in temp_contexts or []:
                    name = context.get("name")
                    cluster = context.get("context", {}).get("cluster", "")

                    if (
                        name == cluster_name or cluster == cluster_name or cluster.endswith((f"/{cluster_name}", f":cluster/{cluster_name}"))
                    ):
                        selected_context = name
                        break

                if selected_context is None:
                    raise RuntimeError(
                        f"Unable to find kubeconfig context for EKS cluster "
                        f"'{cluster_name}'."
                    )

                self.eks_kubeconfig_path = kubeconfig_path
                self.eks_kube_context = selected_context
                self.eks_kubeconfig_temporary = True

            except Exception:
                try:
                    os.remove(kubeconfig_path)
                except OSError:
                    pass
                raise

        else:
            self.eks_kubeconfig_path = None
            self.eks_kube_context = selected_context
            self.eks_kubeconfig_temporary = False

        if kubeconfig_path:
            config.load_kube_config(
                config_file=kubeconfig_path,
                context=selected_context,
            )
        else:
            config.load_kube_config(
                context=selected_context,
            )

        self.k8s_core_api = client.CoreV1Api()
        self.k8s_apps_api = client.AppsV1Api()
        self.k8s_custom_api = client.CustomObjectsApi()
        self.k8s_api_client = getattr(self.k8s_custom_api, "api_client", None)
        from chaosforge.providers.azure.components.aks.kubernetes import register_api_client

        register_api_client(self.eks_kube_context, self.k8s_api_client)

    def list_lambda_functions(self):

        with spinner("Discovering Lambda Functions..."):
            client = boto3.client("lambda", region_name=self.region)

            response = client.list_functions()

            functions = []

            for function in response.get("Functions", []):
                functions.append(
                    {"name": function["FunctionName"], "arn": function["FunctionArn"]}
                )

        info(f"Discovered {len(functions)} Lambda Function(s)")

        return functions

    # ----------------------------------------------------------
    # ECS Clusters
    # ----------------------------------------------------------

    def list_ecs_clusters(self):

        with spinner("Discovering ECS Clusters..."):
            client = boto3.client("ecs", region_name=self.region)

            response = client.list_clusters()

            clusters = []

            if response["clusterArns"]:
                details = client.describe_clusters(clusters=response["clusterArns"])

                for cluster in details["clusters"]:
                    clusters.append(
                        {
                            "name": cluster["clusterName"],
                            "arn": cluster["clusterArn"],
                        }
                    )

        info(f"Discovered {len(clusters)} ECS Cluster(s)")

        return clusters

    # ----------------------------------------------------------
    # ECS Services (Fargate)
    # ----------------------------------------------------------

    def list_ecs_services(self, cluster_name):

        with spinner("Discovering ECS Services..."):
            client = boto3.client("ecs", region_name=self.region)

            response = client.list_services(cluster=cluster_name)

            services = []

            if response["serviceArns"]:
                details = client.describe_services(
                    cluster=cluster_name, services=response["serviceArns"]
                )

                for service in details["services"]:
                    #
                    # Fargate only
                    #
                    if service.get("launchType") != "FARGATE":
                        continue

                    services.append(
                        {
                            "name": service["serviceName"],
                            "arn": service["serviceArn"],
                            "cluster": cluster_name,
                            "desired_count": service["desiredCount"],
                            "running_count": service["runningCount"],
                            "task_definition": service["taskDefinition"],
                        }
                    )

        info(f"Discovered {len(services)} ECS Fargate Service(s)")

        return services

    # ----------------------------------------------------------
    # ECS Running Tasks
    # ----------------------------------------------------------

    def list_ecs_tasks(
        self,
        cluster_name,
        service_name,
    ):

        with spinner("Discovering ECS Running Tasks..."):
            client = boto3.client(
                "ecs",
                region_name=self.region,
            )

            #
            # Get running task ARNs
            #

            response = client.list_tasks(
                cluster=cluster_name,
                serviceName=service_name,
            )

            task_arns = response.get(
                "taskArns",
                [],
            )

            if not task_arns:
                info("No running ECS Task(s) found.")

                return []

            #
            # Describe Tasks
            #

            details = client.describe_tasks(
                cluster=cluster_name,
                tasks=task_arns,
            )

            tasks = []

            for task in details["tasks"]:
                tasks.append(
                    {
                        "name": task["taskArn"].split("/")[-1][:12],
                        "task_arn": task["taskArn"],
                        "cluster": cluster_name,
                        "service": service_name,
                        "status": task["lastStatus"],
                    }
                )

        info(f"Discovered {len(tasks)} Running ECS Task(s)")

        return tasks

    def get_ecs_task_arns(
        self,
        cluster_name,
        service_name,
    ):

        tasks = self.list_ecs_tasks(
            cluster_name,
            service_name,
        )

        return [task["task_arn"] for task in tasks]

        # ----------------------------------------------------------

    # EKS Clusters
    # ----------------------------------------------------------

    def list_eks_clusters(self):

        with spinner("Discovering EKS Clusters..."):
            client_eks = boto3.client(
                "eks",
                region_name=self.region,
            )

            response = client_eks.list_clusters()

            clusters = []

            for cluster_name in response.get("clusters", []):
                details = client_eks.describe_cluster(name=cluster_name)

                cluster = details.get("cluster", {})

                clusters.append(
                    {
                        "name": cluster_name,
                        "arn": cluster.get("arn"),
                        "status": cluster.get("status"),
                        "version": cluster.get("version"),
                    }
                )

        info(f"Discovered {len(clusters)} EKS Cluster(s)")

        return clusters

    # ----------------------------------------------------------
    # EKS Kubernetes Nodes
    # ----------------------------------------------------------

    def list_eks_nodes(self, cluster_name):

        with spinner(f"Discovering Nodes for EKS Cluster '{cluster_name}'..."):
            try:
                contexts, _ = config.list_kube_config_contexts()

            except ConfigException as exc:
                raise LookupError(
                    "Kubernetes configuration was not found. "
                    "Configure an EKS context using kubeconfig before "
                    "discovering EKS nodes."
                ) from exc

            selected_context = None

            for context_entry in contexts:
                context_name = context_entry.get("name")

                context_data = context_entry.get(
                    "context",
                    {},
                )

                context_cluster = context_data.get("cluster")

                #
                # AWS CLI normally creates contexts such as:
                #
                # arn:aws:eks:<region>:<account>:cluster/<name>
                #
                # Match either the context name or the
                # underlying cluster name.
                #

                if (
                    context_name == cluster_name
                    or context_cluster == cluster_name
                    or (
                        isinstance(context_cluster, str)
                        and context_cluster.endswith(f"/{cluster_name}")
                    )
                ):
                    selected_context = context_name
                    break

            if selected_context is None:
                raise LookupError(
                    f"No Kubernetes context found for EKS cluster "
                    f"'{cluster_name}'. "
                    f"Run 'aws eks update-kubeconfig' for this cluster."
                )

            try:
                config.load_kube_config(context=selected_context)

                v1 = client.CoreV1Api()

                response = v1.list_node()

            except Exception as exc:
                raise LookupError(
                    f"Unable to discover Kubernetes nodes for "
                    f"EKS cluster '{cluster_name}': {exc}"
                ) from exc

            nodes = []

            for node in response.items:
                node_name = node.metadata.name

                nodes.append(
                    {
                        "name": node_name,
                        "cluster": cluster_name,
                        "uid": node.metadata.uid,
                    }
                )

        info(f"Discovered {len(nodes)} EKS Node(s)")

        return nodes

    def list_eks_namespaces(self, cluster_name):
        """
        List Kubernetes namespaces available in an EKS cluster.
        """

        self._configure_eks_kubernetes_client(cluster_name)

        namespaces = self.k8s_core_api.list_namespace()

        return [
            {
                "name": item.metadata.name,
                "cluster": cluster_name,
            }
            for item in namespaces.items
        ]

    def list_eks_deployments(self, cluster_name, namespace):
        """
        List Kubernetes deployments in an EKS cluster namespace.
        """

        self._configure_eks_kubernetes_client(cluster_name)

        deployments = self.k8s_apps_api.list_namespaced_deployment(namespace=namespace)

        return [
            {
                "name": item.metadata.name,
                "namespace": namespace,
                "cluster": cluster_name,
                "replicas": item.spec.replicas or 0,
            }
            for item in deployments.items
        ]

    def list_eks_pods(self, cluster_name, namespace):
        """
        List Kubernetes pods in an EKS cluster namespace.
        """

        self._configure_eks_kubernetes_client(cluster_name)

        pods = self.k8s_core_api.list_namespaced_pod(namespace=namespace)

        return [
            {
                "name": item.metadata.name,
                "namespace": namespace,
                "cluster": cluster_name,
                "status": (item.status.phase if item.status else "Unknown"),
            }
            for item in pods.items
        ]

    def get_eks_pod_context(self, cluster_name, namespace, pod_name):
        """Return the labels and owning deployment for one selected EKS pod."""
        self._configure_eks_kubernetes_client(cluster_name)
        pod = self.k8s_core_api.read_namespaced_pod(name=pod_name, namespace=namespace)
        owners = pod.metadata.owner_references or []
        owner = next((item for item in owners if item.controller), None)
        deployment = ""
        if owner and owner.kind == "Deployment":
            deployment = owner.name
        elif owner and owner.kind == "ReplicaSet":
            replica_set = self.k8s_apps_api.read_namespaced_replica_set(
                name=owner.name,
                namespace=namespace,
            )
            deployment_owner = next(
                (item for item in (replica_set.metadata.owner_references or []) if item.controller),
                None,
            )
            if deployment_owner and deployment_owner.kind == "Deployment":
                deployment = deployment_owner.name
        return {"labels": dict(pod.metadata.labels or {}), "owning_deployment": deployment}

    def get_eks_deployment_context(self, cluster_name, namespace, deployment):
        """Return the pod selector used by one selected EKS deployment."""
        self._configure_eks_kubernetes_client(cluster_name)
        resource = self.k8s_apps_api.read_namespaced_deployment(
            name=deployment, namespace=namespace
        )
        return {"labels": dict(resource.spec.selector.match_labels or {})}

    def list_eks_containers(self, cluster_name, namespace, pod_name="", deployment=""):
        """List unique containers from an exact pod or one deployment's pods."""
        self._configure_eks_kubernetes_client(cluster_name)
        if pod_name:
            pods = [self.k8s_core_api.read_namespaced_pod(name=pod_name, namespace=namespace)]
        else:
            resource = self.k8s_apps_api.read_namespaced_deployment(name=deployment, namespace=namespace)
            selector = ",".join(
                f"{key}={value}" for key, value in (resource.spec.selector.match_labels or {}).items()
            )
            pods = self.k8s_core_api.list_namespaced_pod(
                namespace=namespace, label_selector=selector
            ).items
        names = {
            container.name
            for pod in pods
            for container in (pod.spec.containers or [])
            if container.name
        }
        return [{"name": name} for name in sorted(names)]

    def eks_pod_exists(self, cluster_name, namespace, pod_name):
        """Return whether the originally selected EKS pod still exists."""
        self._configure_eks_kubernetes_client(cluster_name)
        try:
            self.k8s_core_api.read_namespaced_pod(name=pod_name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        return True

    def find_eks_pods_by_owner(
        self,
        cluster_name,
        namespace,
        owner_kind,
        owner_name,
    ):
        """
        Find pods belonging to the specified Kubernetes owner.
        """

        self._configure_eks_kubernetes_client(cluster_name)

        pods = self.k8s_core_api.list_namespaced_pod(
            namespace=namespace
        )

        matching_pods = []

        for pod in pods.items:
            owner_references = (
                pod.metadata.owner_references
                if pod.metadata
                else None
            )

            if not owner_references:
                continue

            for owner in owner_references:
                if (
                    owner.kind == owner_kind
                    and owner.name == owner_name
                ):
                    matching_pods.append(
                        {
                            "name": pod.metadata.name,
                            "namespace": namespace,
                            "cluster": cluster_name,
                            "status": (
                                pod.status.phase
                                if pod.status
                                else "Unknown"
                            ),
                            "owner_kind": owner.kind,
                            "owner_name": owner.name,
                        }
                    )
                    break

        return matching_pods

    def list_eks_volumes(self, cluster_name, namespace, pod_name):
        """
        List Kubernetes volumes defined on an EKS pod.
        """

        self._configure_eks_kubernetes_client(cluster_name)

        pod = self.k8s_core_api.read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
        )

        volumes = pod.spec.volumes or []

        return [
            {
                "name": volume.name,
                "id": volume.name,
                "cluster": cluster_name,
                "namespace": namespace,
                "pod": pod_name,
            }
            for volume in volumes
        ]

    def list_chaos_physical_machines(self, cluster_name):
        """
        List Chaos Mesh PhysicalMachine resources
        available in the EKS cluster.
        """

        self._configure_eks_kubernetes_client(cluster_name)

        response = self.k8s_custom_api.list_cluster_custom_object(
            group="chaos-mesh.org",
            version="v1alpha1",
            plural="physicalmachines",
        )

        items = response.get("items", [])

        return [
            {
                "name": item.get("metadata", {}).get("name"),
                "id": item.get("metadata", {}).get("name"),
                "namespace": item.get("metadata", {}).get(
                    "namespace",
                    "default",
                ),
                "cluster": cluster_name,
            }
            for item in items
        ]

    # ----------------------------------------------------------
    # DynamoDB
    # ----------------------------------------------------------

    def list_dynamodb_tables(self):

        with spinner("Discovering DynamoDB Tables..."):
            client = boto3.client("dynamodb", region_name=self.region)

            response = client.list_tables()

            tables = []

            for table in response.get("TableNames", []):
                desc = client.describe_table(TableName=table)

                tables.append({"name": table, "arn": desc["Table"]["TableArn"]})

        info(f"Discovered {len(tables)} DynamoDB Table(s)")

        return tables

    def list_dynamodb_global_tables(self):
        client = boto3.client("dynamodb", region_name=self.region)
        return [
            {"name": table["GlobalTableName"], "arn": table["GlobalTableArn"]}
            for table in client.list_global_tables().get("GlobalTables", [])
        ]

    # ----------------------------------------------------------
    # Kinesis
    # ----------------------------------------------------------

    def list_kinesis_streams(self):

        with spinner("Discovering Kinesis Streams..."):
            client = boto3.client(
                "kinesis",
                region_name=self.region,
            )

            response = client.list_streams()

            streams = []

            for stream_name in response.get("StreamNames", []):
                details = client.describe_stream(StreamName=stream_name)

                description = details.get(
                    "StreamDescription",
                    {},
                )

                streams.append(
                    {
                        "name": stream_name,
                        "arn": description.get("StreamARN"),
                    }
                )

        info(f"Discovered {len(streams)} Kinesis Stream(s)")

        return streams

    # ----------------------------------------------------------
    # RDS
    # ----------------------------------------------------------

    def list_rds_instances(self):

        with spinner("Discovering RDS Instances..."):
            client = boto3.client("rds", region_name=self.region)

            response = client.describe_db_instances()

            instances = []

            for db in response["DBInstances"]:
                instances.append(
                    {
                        "name": db["DBInstanceIdentifier"],
                        "identifier": db["DBInstanceIdentifier"],
                        "arn": db["DBInstanceArn"],
                    }
                )

        info(f"Discovered {len(instances)} RDS Instance(s)")

        return instances

    def list_rds_instance_classes(self, db_instance_identifier):
        """Return the instance-class changes currently approved by RDS."""
        client = boto3.client("rds", region_name=self.region)
        instance = client.describe_db_instances(
            DBInstanceIdentifier=db_instance_identifier
        )["DBInstances"][0]
        if instance.get("DBInstanceStatus") != "available":
            raise RuntimeError(
                f"RDS instance '{db_instance_identifier}' is {instance.get('DBInstanceStatus')}; "
                "wait until it is available before loading target classes."
            )
        response = client.describe_valid_db_instance_modifications(
            DBInstanceIdentifier=db_instance_identifier
        )
        modifications = response.get("ValidDBInstanceModificationsMessage", {}).get(
            "ValidDBInstanceModifications", []
        )
        return [
            {"name": instance_class}
            for instance_class in sorted(
                {
                    value
                    for modification in modifications
                    for value in modification.get("ValidDBInstanceClasses", [])
                }
            )
        ]

    def list_rds_clusters(self):
        client = boto3.client("rds", region_name=self.region)
        return [
            {"name": cluster["DBClusterIdentifier"], "arn": cluster["DBClusterArn"]}
            for cluster in client.describe_db_clusters().get("DBClusters", [])
        ]

    # ----------------------------------------------------------
    # ElastiCache (Memcached / Redis Cache Clusters)
    # ----------------------------------------------------------

    # ----------------------------------------------------------
    # ElastiCache Serverless
    # ----------------------------------------------------------

    def list_elasticache_serverless(self):

        with spinner("Discovering ElastiCache Serverless Caches..."):
            client = boto3.client("elasticache", region_name=self.region)

            response = client.describe_serverless_caches()

            print(response)

            caches = []

            for cache in response.get("ServerlessCaches", []):
                caches.append(
                    {"name": cache["ServerlessCacheName"], "arn": cache["ARN"]}
                )

        info(f"Discovered {len(caches)} ElastiCache Serverless Cache(s)")

        return caches

    def list_elasticache_replication_groups(self):
        client = boto3.client("elasticache", region_name=self.region)
        return [
            {"name": group["ReplicationGroupId"], "arn": group["ARN"]}
            for group in client.describe_replication_groups().get("ReplicationGroups", [])
        ]

    def list_elasticache_cache_clusters(self):
        client = boto3.client("elasticache", region_name=self.region)
        return [
            {"name": cluster["CacheClusterId"], "arn": cluster.get("ARN", "")}
            for cluster in client.describe_cache_clusters().get("CacheClusters", [])
        ]

    def list_ec2_ebs_volumes_all(self):
        client = boto3.client("ec2", region_name=self.region)
        return [
            {"name": volume["VolumeId"], "id": volume["VolumeId"], "arn": f"arn:aws:ec2:{self.region}:{volume.get('OwnerId', '')}:volume/{volume['VolumeId']}"}
            for volume in client.describe_volumes().get("Volumes", [])
        ]

    # ----------------------------------------------------------
    # EC2
    # ----------------------------------------------------------

    def list_ec2_instances(self):

        with spinner("Discovering EC2 Instances..."):
            client = boto3.client("ec2", region_name=self.region)

            response = client.describe_instances()

            instances = []

            for reservation in response["Reservations"]:
                owner_id = reservation.get("OwnerId")

                for instance in reservation["Instances"]:
                    name = instance["InstanceId"]

                    for tag in instance.get("Tags", []):
                        if tag["Key"] == "Name":
                            name = tag["Value"]

                    instances.append(
                        {
                            "name": name,
                            "id": instance["InstanceId"],
                            "arn": (
                                f"arn:aws:ec2:{self.region}:"
                                f"{owner_id}:instance/"
                                f"{instance['InstanceId']}"
                            )
                            if owner_id
                            else "",
                        }
                    )

        info(f"Discovered {len(instances)} EC2 Instance(s)")

        return instances

    # ----------------------------------------------------------
    # EC2 EBS Volumes
    # ----------------------------------------------------------

    def list_ec2_ebs_volumes(self, instance_id):

        with spinner("Discovering EBS Volumes..."):
            client = boto3.client(
                "ec2",
                region_name=self.region,
            )

            response = client.describe_volumes(
                Filters=[
                    {
                        "Name": "attachment.instance-id",
                        "Values": [instance_id],
                    }
                ]
            )

            volumes = []

            for volume in response.get("Volumes", []):
                attachments = volume.get("Attachments", [])

                attachment = None

                for item in attachments:
                    if item.get("InstanceId") == instance_id:
                        attachment = item
                        break

                if attachment is None:
                    continue

                volume_id = volume["VolumeId"]

                name = volume_id

                for tag in volume.get("Tags", []):
                    if tag.get("Key") == "Name":
                        name = tag.get("Value", volume_id)
                        break

                volumes.append(
                    {
                        "name": name,
                        "id": volume_id,
                        "arn": (
                            f"arn:aws:ec2:{self.region}:"
                            f"{volume['OwnerId']}:volume/"
                            f"{volume_id}"
                        )
                        if "OwnerId" in volume
                        else "",
                        "device_name": attachment.get("Device"),
                        "state": volume.get("State"),
                        "size": volume.get("Size"),
                        "volume_type": volume.get("VolumeType"),
                        "instance_id": instance_id,
                    }
                )

        info(f"Discovered {len(volumes)} EBS Volume(s)")

        return volumes

        # ----------------------------------------------------------

    # EC2 Available EBS Volumes
    # ----------------------------------------------------------

    def list_available_ec2_ebs_volumes(self, instance_id):

        with spinner("Discovering Available EBS Volumes..."):
            client = boto3.client(
                "ec2",
                region_name=self.region,
            )

            #
            # Get the selected EC2 instance AZ.
            #
            response = client.describe_instances(InstanceIds=[instance_id])

            reservations = response.get("Reservations", [])

            if not reservations:
                return []

            instances = reservations[0].get("Instances", [])

            if not instances:
                return []

            instance = instances[0]

            availability_zone = instance.get(
                "Placement",
                {},
            ).get("AvailabilityZone")

            if not availability_zone:
                return []

            #
            # Only return EBS volumes that:
            #
            # 1. Are available (not attached)
            # 2. Are in the same AZ as the EC2 instance
            #
            response = client.describe_volumes(
                Filters=[
                    {
                        "Name": "status",
                        "Values": ["available"],
                    },
                    {
                        "Name": "availability-zone",
                        "Values": [availability_zone],
                    },
                ]
            )

            volumes = []

            for volume in response.get("Volumes", []):
                volume_id = volume["VolumeId"]

                #
                # Use Name tag when available.
                #
                name = volume_id

                for tag in volume.get("Tags", []):
                    if tag.get("Key") == "Name":
                        name = tag.get(
                            "Value",
                            volume_id,
                        )

                        break

                volumes.append(
                    {
                        "name": name,
                        "id": volume_id,
                        "arn": (
                            f"arn:aws:ec2:{self.region}:"
                            f"{volume['OwnerId']}:volume/"
                            f"{volume_id}"
                        )
                        if "OwnerId" in volume
                        else "",
                        "state": volume.get("State"),
                        "size": volume.get("Size"),
                        "volume_type": volume.get("VolumeType"),
                        "availability_zone": availability_zone,
                        "instance_id": instance_id,
                    }
                )

        info(f"Discovered {len(volumes)} Available EBS Volume(s)")

        return volumes

    # ----------------------------------------------------------
    # EC2 Spot Instances
    # ----------------------------------------------------------

    def list_ec2_spot_instances(self):

        with spinner("Discovering EC2 Spot Instances..."):
            client = boto3.client(
                "ec2",
                region_name=self.region,
            )

            response = client.describe_instances(
                Filters=[
                    {
                        "Name": "instance-lifecycle",
                        "Values": ["spot"],
                    }
                ]
            )

            instances = []

            for reservation in response.get("Reservations", []):
                owner_id = reservation.get("OwnerId")

                for instance in reservation.get("Instances", []):
                    name = instance["InstanceId"]

                    for tag in instance.get("Tags", []):
                        if tag["Key"] == "Name":
                            name = tag["Value"]

                    instances.append(
                        {
                            "name": name,
                            "id": instance["InstanceId"],
                            "arn": (
                                f"arn:aws:ec2:{self.region}:"
                                f"{owner_id}:instance/"
                                f"{instance['InstanceId']}"
                            )
                            if owner_id
                            else "",
                        }
                    )

        info(f"Discovered {len(instances)} EC2 Spot Instance(s)")

        return instances

    # ----------------------------------------------------------
    # ELBv2 Load Balancers
    # ----------------------------------------------------------

    def list_elb_load_balancers(self):

        with spinner("Discovering ELB Load Balancers..."):
            client = boto3.client(
                "elbv2",
                region_name=self.region,
            )

            response = client.describe_load_balancers()

            load_balancers = []

            for load_balancer in response.get(
                "LoadBalancers",
                [],
            ):
                load_balancers.append(
                    {
                        "name": load_balancer["LoadBalancerName"],
                        "id": load_balancer["LoadBalancerArn"],
                        "arn": load_balancer["LoadBalancerArn"],
                        "type": load_balancer["Type"],
                        "scheme": load_balancer["Scheme"],
                        "vpc_id": load_balancer.get("VpcId"),
                        "state": load_balancer.get(
                            "State",
                            {},
                        ).get("Code"),
                    }
                )

        info(f"Discovered {len(load_balancers)} ELB Load Balancer(s)")

        return load_balancers

    # ----------------------------------------------------------
    # ELBv2 Listeners
    # ----------------------------------------------------------

    def list_elb_listeners(self, load_balancer_arn):

        with spinner("Discovering ELB Listeners..."):
            client = boto3.client(
                "elbv2",
                region_name=self.region,
            )

            response = client.describe_listeners(
                LoadBalancerArn=load_balancer_arn,
            )

            listeners = []

            for listener in response.get(
                "Listeners",
                [],
            ):
                listener_arn = listener["ListenerArn"]

                listeners.append(
                    {
                        "name": (
                            f"{listener.get('Protocol', 'N/A')}"
                            f":{listener.get('Port', 'N/A')}"
                        ),
                        "id": listener_arn,
                        "arn": listener_arn,
                        "protocol": listener.get("Protocol"),
                        "port": listener.get("Port"),
                        "load_balancer_arn": load_balancer_arn,
                    }
                )

        info(f"Discovered {len(listeners)} ELB Listener(s)")

        return listeners

    # ----------------------------------------------------------
    # ELBv2 Target Groups
    # ----------------------------------------------------------

    def list_elb_target_groups(self, load_balancer_arn):

        with spinner("Discovering ELB Target Groups..."):
            client = boto3.client(
                "elbv2",
                region_name=self.region,
            )

            response = client.describe_target_groups(
                LoadBalancerArn=load_balancer_arn,
            )

            target_groups = []

            for target_group in response.get(
                "TargetGroups",
                [],
            ):
                target_groups.append(
                    {
                        "name": target_group["TargetGroupName"],
                        "id": target_group["TargetGroupArn"],
                        "arn": target_group["TargetGroupArn"],
                        "target_type": target_group["TargetType"],
                        "protocol": target_group["Protocol"],
                        "port": target_group.get("Port"),
                        "vpc_id": target_group.get("VpcId"),
                        "load_balancer_arn": load_balancer_arn,
                    }
                )

        info(f"Discovered {len(target_groups)} ELB Target Group(s)")

        return target_groups

    # ----------------------------------------------------------
    # ELBv2 Targets
    # ----------------------------------------------------------

    def list_elb_targets(self, target_group_arn):

        with spinner("Discovering ELB Targets..."):
            client = boto3.client(
                "elbv2",
                region_name=self.region,
            )

            response = client.describe_target_health(
                TargetGroupArn=target_group_arn,
            )

            targets = []

            for target in response.get(
                "TargetHealthDescriptions",
                [],
            ):
                target_data = target.get(
                    "Target",
                    {},
                )

                target_id = target_data.get("Id")

                if not target_id:
                    continue

                port = target_data.get("Port")

                health = target.get(
                    "TargetHealth",
                    {},
                )

                health_state = health.get(
                    "State",
                )

                targets.append(
                    {
                        "name": (f"{target_id} ({health_state})"),
                        "id": target_id,
                        "target_id": target_id,
                        "port": port,
                        "health": health_state,
                        "target_group_arn": target_group_arn,
                    }
                )

        info(f"Discovered {len(targets)} ELB Target(s)")

        return targets

    # ----------------------------------------------------------
    # Availability Zones
    # ----------------------------------------------------------

    def list_availability_zones(self):

        with spinner("Discovering Availability Zones..."):
            client = boto3.client(
                "ec2",
                region_name=self.region,
            )

            response = client.describe_availability_zones(
                Filters=[
                    {
                        "Name": "state",
                        "Values": ["available"],
                    }
                ]
            )

            zones = []

            for zone in response.get("AvailabilityZones", []):
                zone_name = zone.get("ZoneName")

                if not zone_name:
                    continue

                zones.append(
                    {
                        "name": zone_name,
                        "id": zone.get("ZoneId"),
                        "zone_name": zone_name,
                        "zone_id": zone.get("ZoneId"),
                        "state": zone.get("State"),
                        "region": self.region,
                    }
                )

        info(f"Discovered {len(zones)} Availability Zone(s)")

        return zones

    # ----------------------------------------------------------
    # IAM Roles
    # ----------------------------------------------------------

    def list_iam_roles(self):

        with spinner("Discovering IAM Roles..."):
            client = boto3.client("iam")

            response = client.list_roles()

            roles = []

            for role in response.get("Roles", []):
                roles.append(
                    {
                        "name": role["RoleName"],
                        "id": role.get("RoleId", ""),
                        "arn": role["Arn"],
                    }
                )

        info(f"Discovered {len(roles)} IAM Role(s)")

        return roles

    # ----------------------------------------------------------
    # Auto Scaling Groups
    # ----------------------------------------------------------

    def list_auto_scaling_groups(self):

        with spinner("Discovering Auto Scaling Groups..."):
            client = boto3.client(
                "autoscaling",
                region_name=self.region,
            )

            response = client.describe_auto_scaling_groups()

            groups = []

            for group in response.get(
                "AutoScalingGroups",
                [],
            ):
                groups.append(
                    {
                        "name": group["AutoScalingGroupName"],
                        "id": group.get(
                            "AutoScalingGroupARN",
                            group["AutoScalingGroupName"],
                        ),
                        "arn": group["AutoScalingGroupARN"],
                    }
                )

        info(f"Discovered {len(groups)} Auto Scaling Group(s)")

        return groups

    def list_sns_topics(self):

        print("=" * 80)
        print("DEBUG: list_sns_topics() called")
        print("Region:", self.region)

        with spinner("Discovering SNS Topics..."):
            client = boto3.client("sns", region_name=self.region)

            response = client.list_topics()

            print("AWS Response:", response)

            topics = []

            for topic in response.get("Topics", []):
                arn = topic["TopicArn"]
                name = arn.split(":")[-1]

                topics.append({"name": name, "arn": arn})

        print("Topics:", topics)

        info(f"Discovered {len(topics)} SNS Topic(s)")

        return topics

    def list_sns_subscriptions(self):

        with spinner("Discovering SNS Subscriptions..."):
            client = boto3.client("sns", region_name=self.region)

        paginator = client.get_paginator("list_subscriptions")

        subscriptions = []

        for page in paginator.paginate():
            for sub in page["Subscriptions"]:
                if sub["SubscriptionArn"] == "PendingConfirmation":
                    continue

                subscriptions.append(
                    {
                        "name": f"{sub['Protocol']} -> {sub['Endpoint']}",
                        "arn": sub["SubscriptionArn"],
                    }
                )

        info(f"Discovered {len(subscriptions)} SNS Subscription(s)")

        return subscriptions

    # ----------------------------------------------------------
    # VPC - Security Groups
    # ----------------------------------------------------------

    def list_security_groups(self):

        with spinner("Discovering Security Groups..."):
            client = boto3.client("ec2", region_name=self.region)

            response = client.describe_security_groups()

            groups = []

            for sg in response["SecurityGroups"]:
                groups.append(
                    {
                        "name": (
                            f"{sg['GroupName']} | {sg['GroupId']} | {sg['VpcId']}"
                        ),
                        "id": sg["GroupId"],
                        "arn": sg["GroupId"],
                        "description": sg.get("Description", ""),
                    }
                )

        info(f"Discovered {len(groups)} Security Group(s)")

        return groups

    # ----------------------------------------------------------
    # API Gateway - REST APIs
    # ----------------------------------------------------------

    def list_apigateway_rest_apis(self):

        with spinner("Discovering API Gateway REST APIs..."):
            client = boto3.client("apigateway", region_name=self.region)

            response = client.get_rest_apis()

            apis = []

            for api in response.get("items", []):
                apis.append({"name": api["name"], "id": api["id"]})

        info(f"Discovered {len(apis)} REST API(s)")

        return apis

    def list_apigateway_apis(self):

        apis = []

        with spinner("Discovering API Gateway APIs..."):
            # -----------------------------
            # REST APIs (v1)
            # -----------------------------
            rest_client = boto3.client("apigateway", region_name=self.region)

            rest_response = rest_client.get_rest_apis()

            for api in rest_response.get("items", []):
                apis.append(
                    {
                        "name": api["name"],
                        "id": api["id"],
                        "protocol": "REST",
                    }
                )

            # -----------------------------
            # HTTP APIs (v2)
            # -----------------------------
            http_client = boto3.client("apigatewayv2", region_name=self.region)

            http_response = http_client.get_apis()

            for api in http_response.get("Items", []):
                apis.append(
                    {
                        "name": api["Name"],
                        "id": api["ApiId"],
                        "protocol": api["ProtocolType"],
                    }
                )

        info(f"Discovered {len(apis)} API Gateway API(s)")

        return apis

    # ----------------------------------------------------------
    # API Gateway - Stages
    # ----------------------------------------------------------

    def list_apigateway_stages(self, api_id, protocol="REST"):

        with spinner("Discovering API Gateway Stages..."):
            if protocol.upper() == "HTTP":
                client = boto3.client(
                    "apigatewayv2",
                    region_name=self.region,
                )

                response = client.get_stages(ApiId=api_id)

                stages = []

                for stage in response.get("Items", []):
                    stages.append(
                        {
                            "name": stage["StageName"],
                            "stageName": stage["StageName"],
                        }
                    )

            else:
                client = boto3.client(
                    "apigateway",
                    region_name=self.region,
                )

                response = client.get_stages(restApiId=api_id)

                stages = []

                for stage in response.get("item", []):
                    stages.append(
                        {
                            "name": stage["stageName"],
                            "stageName": stage["stageName"],
                        }
                    )

        info(f"Discovered {len(stages)} Stage(s)")

        return stages

    # ----------------------------------------------------------
    # Generic Resource Discovery
    # ----------------------------------------------------------

    def discover(self, resource_type):

        resource_type = resource_type.lower()
        mapping = {
            "lambda": self.list_lambda_functions,
            "dynamodb": self.list_dynamodb_tables,
            "dynamodb-global-table": self.list_dynamodb_global_tables,
            "rds": self.list_rds_instances,
            "rds-cluster": self.list_rds_clusters,
            "elasticache": self.list_elasticache_serverless,
            "elasticache-replication-group": self.list_elasticache_replication_groups,
            "elasticache-cache-cluster": self.list_elasticache_cache_clusters,
            "apigateway": self.list_apigateway_apis,
            "ec2": self.list_ec2_instances,
            "ebs-volume": self.list_ec2_ebs_volumes_all,
            "sns": self.list_sns_topics,
            "sns_subscription": self.list_sns_subscriptions,
            "security-group": self.list_security_groups,
            "ecs": self.list_ecs_clusters,
            "ecs_task": self.list_all_ecs_tasks,
            "s3": self.list_s3_buckets,
            "eks": self.list_eks_clusters,
            "kinesis": self.list_kinesis_streams,
            "chaos-physical-machine": self.list_chaos_physical_machines,
        }

        return mapping[resource_type]()

    def list_security_group_rules(self, security_group_id):

        ec2 = boto3.client("ec2", region_name=self.region)

        response = ec2.describe_security_groups(GroupIds=[security_group_id])

        permissions = response["SecurityGroups"][0]["IpPermissions"]

        rules = []

        for index, rule in enumerate(permissions):
            #
            # Protocol
            #

            protocol = rule.get("IpProtocol", "-1")

            if protocol == "-1":
                protocol = "ALL"
            else:
                protocol = protocol.upper()

            #
            # Port
            #

            if "FromPort" not in rule:
                port = "ALL"

            elif rule["FromPort"] == rule.get("ToPort"):
                port = str(rule["FromPort"])

            else:
                port = f"{rule['FromPort']}-{rule['ToPort']}"

            #
            # Source
            #

            sources = []

            # IPv4 CIDRs
            for ip in rule.get("IpRanges", []):
                sources.append(ip["CidrIp"])

            # IPv6 CIDRs
            for ip in rule.get("Ipv6Ranges", []):
                sources.append(ip["CidrIpv6"])

            # Security Group References
            for sg in rule.get("UserIdGroupPairs", []):
                sources.append(sg["GroupId"])

            # Prefix Lists
            for prefix in rule.get("PrefixListIds", []):
                sources.append(prefix["PrefixListId"])

            if not sources:
                source = "N/A"

            else:
                source = ", ".join(sources)

            #
            # Display Name
            #

            display = f"{protocol:<6} | {port:<10} | {source}"

            rules.append({"id": index, "name": display, "rule": rule})

        return rules

    def list_route_tables(self):

        with spinner("Discovering Route Tables..."):
            client = boto3.client("ec2", region_name=self.region)

            response = client.describe_route_tables()

            tables = []

            for table in response["RouteTables"]:
                #
                # Get VPC ID
                #

                vpc_id = table["VpcId"]

                #
                # Find Name tag
                #

                name = table["RouteTableId"]

                for tag in table.get("Tags", []):
                    if tag["Key"] == "Name":
                        name = tag["Value"]

                        break

                tables.append(
                    {
                        "id": table["RouteTableId"],
                        "name": (f"{name} | {table['RouteTableId']} | {vpc_id}"),
                    }
                )

        info(f"Discovered {len(tables)} Route Table(s)")

        return tables

    def list_routes(self, route_table_id):

        client = boto3.client("ec2", region_name=self.region)

        response = client.describe_route_tables(RouteTableIds=[route_table_id])

        routes = []

        for route in response["RouteTables"][0]["Routes"]:
            #
            # Skip propagated routes
            #

            if route.get("Origin") == "EnableVgwRoutePropagation":
                continue

            #
            # Skip local route
            #

            if route.get("GatewayId") == "local":
                continue

            #
            # Skip local route
            #

            if route.get("GatewayId") == "local":
                continue

            destination = (
                route.get("DestinationCidrBlock")
                or route.get("DestinationIpv6CidrBlock")
                or route.get("DestinationPrefixListId")
            )

            if "GatewayId" in route:
                target = f"IGW : {route['GatewayId']}"

            elif "NatGatewayId" in route:
                target = f"NAT : {route['NatGatewayId']}"

            elif "TransitGatewayId" in route:
                target = f"TGW : {route['TransitGatewayId']}"

            elif "VpcPeeringConnectionId" in route:
                target = f"Peering : {route['VpcPeeringConnectionId']}"

            elif "NetworkInterfaceId" in route:
                target = f"ENI : {route['NetworkInterfaceId']}"

            elif "InstanceId" in route:
                target = f"EC2 : {route['InstanceId']}"

            elif "VpcEndpointId" in route:
                target = f"Endpoint : {route['VpcEndpointId']}"

            else:
                target = "Unknown"

            routes.append(
                {"id": len(routes), "name": f"{destination} → {target}", "route": route}
            )

        return routes

    def list_network_acls(self):

        client = boto3.client("ec2", region_name=self.region)

        response = client.describe_network_acls()

        acls = []

        for acl in response["NetworkAcls"]:
            acls.append(
                {
                    "id": acl["NetworkAclId"],
                    "name": (f"{acl['NetworkAclId']} | {acl['VpcId']}"),
                }
            )

        return acls

    def list_network_acl_rules(self, network_acl_id):

        client = boto3.client("ec2", region_name=self.region)

        response = client.describe_network_acls(NetworkAclIds=[network_acl_id])

        rules = []

        for entry in response["NetworkAcls"][0]["Entries"]:
            #
            # Skip default deny rule
            #

            if entry["RuleNumber"] == 32767:
                continue

            direction = "Egress" if entry["Egress"] else "Ingress"

            protocol = entry["Protocol"]

            cidr = entry.get("CidrBlock", entry.get("Ipv6CidrBlock", ""))

            action = entry["RuleAction"]

            rules.append(
                {
                    "id": len(rules),
                    "name": (
                        f"{direction} | "
                        f"Rule {entry['RuleNumber']} | "
                        f"{protocol} | "
                        f"{cidr} | "
                        f"{action}"
                    ),
                    "rule": entry,
                }
            )

        return rules

    def list_internet_gateways(self):

        with spinner("Discovering Internet Gateways..."):
            client = boto3.client("ec2", region_name=self.region)

            response = client.describe_internet_gateways()

            gateways = []

            for gateway in response["InternetGateways"]:
                igw_id = gateway["InternetGatewayId"]

                vpc = "Not Attached"

                if gateway["Attachments"]:
                    vpc = gateway["Attachments"][0]["VpcId"]

                gateways.append({"id": igw_id, "name": f"{igw_id} | {vpc}"})

        info(f"Discovered {len(gateways)} Internet Gateway(s)")

        return gateways

    def list_s3_buckets(self):

        with spinner("Discovering S3 Buckets..."):
            client = boto3.client("s3", region_name=self.region)

            response = client.list_buckets()

            buckets = []

            for bucket in response["Buckets"]:
                buckets.append(
                    {
                        "id": bucket["Name"],
                        "name": bucket["Name"],
                        "arn": f"arn:aws:s3:::{bucket['Name']}",
                    }
                )

        info(f"Discovered {len(buckets)} S3 Bucket(s)")

        return buckets

    def list_all_ecs_tasks(self):

        client = boto3.client("ecs", region_name=self.region)

        tasks = []

        clusters = client.list_clusters()["clusterArns"]

        for cluster_arn in clusters:
            cluster = cluster_arn.split("/")[-1]

            response = client.list_tasks(cluster=cluster, desiredStatus="RUNNING")

            if not response["taskArns"]:
                continue

            details = client.describe_tasks(cluster=cluster, tasks=response["taskArns"])

            for task in details["tasks"]:
                task_id = task["taskArn"].split("/")[-1]

                tasks.append(
                    {"name": f"{cluster} / {task_id[:12]}", "arn": task["taskArn"]}
                )

        return tasks
