"""
Generic AWS Resource Selector

Uses AWSDiscovery to list available AWS resources
and lets the user choose one.
"""

from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import title
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.interfaces.cli.interactive.ui.status import error, info
from chaosforge.interfaces.cli.interactive.ui.tables import menu
from chaosforge.providers.aws.discovery import AWSDiscovery


class ResourceSelector:
    def __init__(self, region="eu-central-1"):

        self.discovery = AWSDiscovery(region)

    def get_resources(self, service):

        service = service.lower()

        if service == "lambda":
            return self.discovery.list_lambda_functions()

        elif service == "dynamodb":
            return self.discovery.list_dynamodb_tables()

        elif service == "dynamodb-global-table":
            return self.discovery.list_dynamodb_global_tables()

        elif service == "kinesis":
            return self.discovery.list_kinesis_streams()

        elif service == "rds":
            return self.discovery.list_rds_instances()

        elif service == "rds-cluster":
            return self.discovery.list_rds_clusters()

        elif service == "elasticache":
            return self.discovery.list_elasticache_serverless()

        elif service == "elasticache-replication-group":
            return self.discovery.list_elasticache_replication_groups()

        elif service == "elasticache-cache-cluster":
            return self.discovery.list_elasticache_cache_clusters()

        elif service == "apigateway":
            return self.discovery.list_apigateway_apis()

        elif service == "ec2":
            return self.discovery.list_ec2_instances()

        elif service == "ebs-volume":
            return self.discovery.list_ec2_ebs_volumes_all()

        elif service == "ec2-spot":
            return self.discovery.list_ec2_spot_instances()

        elif service == "availability-zone":
            return self.discovery.list_availability_zones()

        elif service == "elb":
            return self.discovery.list_elb_load_balancers()

        elif service == "iam-role":
            return self.discovery.list_iam_roles()

        elif service == "autoscaling-group":
            return self.discovery.list_auto_scaling_groups()

        elif service == "sns":
            return self.discovery.list_sns_topics()

        elif service == "sns_subscription":
            return self.discovery.list_sns_subscriptions()

        elif service == "security-group":
            return self.discovery.list_security_groups()

        elif service == "route-table":
            return self.discovery.list_route_tables()

        elif service == "network-acl":
            return self.discovery.list_network_acls()

        elif service == "internet-gateway":
            return self.discovery.list_internet_gateways()

        elif service == "ecs":
            return self.discovery.list_ecs_clusters()

        elif service == "eks":
            return self.discovery.list_eks_clusters()

        elif service == "ecs_task":
            return self.discovery.list_all_ecs_tasks()

        elif service == "s3":
            return self.discovery.list_s3_buckets()

        return []

    def select_ecs_task(self):

        #
        # Step 1 : Select Cluster
        #

        clusters = self.discovery.list_ecs_clusters()

        if not clusters:
            raise LookupError("No ECS Clusters found.")

        title("Available ECS Clusters")

        menu(
            "ECS Clusters",
            [
                (index, cluster["name"])
                for index, cluster in enumerate(clusters, start=1)
            ],
        )

        cluster = self._select_resource(
            clusters,
            "Select Cluster",
        )

        if cluster is None:
            return None
        #
        # Step 2 : Select Service
        #

        services = self.discovery.list_ecs_services(cluster["name"])

        if not services:
            raise LookupError("No ECS Services found.")

        title("Available ECS Services")

        menu(
            "ECS Services",
            [
                (index, service["name"])
                for index, service in enumerate(services, start=1)
            ],
        )

        service = self._select_resource(
            services,
            "Select Service",
        )

        if service is None:
            return None
        #
        # Step 3 : Running Tasks
        #

        tasks = self.discovery.list_ecs_tasks(
            cluster["name"],
            service["name"],
        )

        if not tasks:
            raise LookupError(
                "No running ECS Tasks found.\n"
                "Please start the ECS Service or generate workload before running AWS FIS experiments."
            )

        title("Running ECS Tasks")

        menu(
            "Running Tasks",
            [(index, task["name"]) for index, task in enumerate(tasks, start=1)],
        )

        task = self._select_resource(
            tasks,
            "Select Task",
        )

        if task is None:
            return None

        #
        # Return compatible object
        #

        return {
            "name": task["name"],
            "arn": task["task_arn"],
            "cluster": cluster["name"],
            "service": service["name"],
        }

    def select_ecs_service(self):

        #
        # Step 1 : Select Cluster
        #

        clusters = self.discovery.list_ecs_clusters()

        if not clusters:
            raise LookupError("No ECS Clusters found.")

        title("Available ECS Clusters")

        menu(
            "ECS Clusters",
            [(i, c["name"]) for i, c in enumerate(clusters, start=1)],
        )

        cluster = self._select_resource(
            clusters,
            "Select Cluster",
        )

        if cluster is None:
            return None

        #
        # Step 2 : Select Service
        #

        services = self.discovery.list_ecs_services(cluster["name"])

        if not services:
            raise LookupError("No ECS Services found.")

        title("Available ECS Services")

        menu(
            "ECS Services",
            [(i, s["name"]) for i, s in enumerate(services, start=1)],
        )

        service = self._select_resource(
            services,
            "Select Service",
        )

        if service is None:
            return None

        return {
            "name": service["name"],
            "service": service["name"],
            "cluster": cluster["name"],
            "arn": service["arn"],
        }

    def select_ebs_volume(self, instance_id):

        volumes = self.discovery.list_ec2_ebs_volumes(instance_id)

        if not volumes:
            raise LookupError(f"No EBS volumes found for EC2 instance '{instance_id}'.")

        title("Attached EBS Volumes")

        menu(
            "EBS Volumes",
            [
                (
                    index,
                    (
                        f"{volume['name']} "
                        f"({volume['id']}) - "
                        f"{volume.get('device_name', 'N/A')}"
                    ),
                )
                for index, volume in enumerate(
                    volumes,
                    start=1,
                )
            ],
        )

        volume = self._select_resource(
            volumes,
            "Select EBS Volume",
        )

        if volume is None:
            return None

        return volume

    def select_available_ebs_volume(self, instance_id):

        volumes = self.discovery.list_available_ec2_ebs_volumes(instance_id)

        if not volumes:
            raise LookupError(
                f"No available EBS volumes found for EC2 instance '{instance_id}'."
            )

        title("Available EBS Volumes")

        menu(
            "EBS Volumes",
            [
                (
                    index,
                    (f"{volume['name']} ({volume['id']})"),
                )
                for index, volume in enumerate(
                    volumes,
                    start=1,
                )
            ],
        )

        volume = self._select_resource(
            volumes,
            "Select EBS Volume",
        )

        if volume is None:
            return None

        return volume

    def list_available_ebs_volumes_for_asg(
        self,
        autoscaling_group,
    ):
        """
        Return available EBS volumes suitable for an
        InService instance belonging to an Auto Scaling Group.

        The returned volumes are restricted to the Availability
        Zone of a healthy InService ASG instance.
        """

        import boto3

        if not autoscaling_group:
            return []

        asg_client = boto3.client(
            "autoscaling",
            region_name=self.discovery.region,
        )

        response = asg_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[autoscaling_group],
        )

        groups = response.get(
            "AutoScalingGroups",
            [],
        )

        if not groups:
            return []

        instance_id = None

        for instance in groups[0].get("Instances", []):
            if (
                instance.get("LifecycleState") == "InService"
                and instance.get("HealthStatus") == "Healthy"
            ):
                instance_id = instance.get("InstanceId")
                break

        if not instance_id:
            return []

        return self.discovery.list_available_ec2_ebs_volumes(instance_id)

    def select_available_ebs_volume_for_asg(
        self,
        autoscaling_group,
    ):
        """
        Select an available EBS volume suitable for an
        InService instance belonging to an Auto Scaling Group.
        """

        volumes = self.list_available_ebs_volumes_for_asg(autoscaling_group)

        if not volumes:
            raise LookupError(
                f"No available EBS volumes found for "
                f"Auto Scaling Group '{autoscaling_group}'."
            )

        title("Available EBS Volumes")

        menu(
            "EBS Volumes",
            [
                (
                    index,
                    (f"{volume['name']} ({volume['id']})"),
                )
                for index, volume in enumerate(
                    volumes,
                    start=1,
                )
            ],
        )

        return self._select_resource(
            volumes,
            "Select EBS Volume",
        )

    def select_elb_target_group(self, load_balancer_arn):

        target_groups = self.discovery.list_elb_target_groups(load_balancer_arn)

        if not target_groups:
            raise LookupError("No ELB Target Groups found.")

        title("Available ELB Target Groups")

        menu(
            "ELB Target Groups",
            [
                (
                    index,
                    (f"{target_group['name']} ({target_group['target_type']})"),
                )
                for index, target_group in enumerate(
                    target_groups,
                    start=1,
                )
            ],
        )

        target_group = self._select_resource(
            target_groups,
            "Select Target Group",
        )

        if target_group is None:
            return None

        return target_group

    def select_elb_listener(self, load_balancer_arn):

        listeners = self.discovery.list_elb_listeners(load_balancer_arn)

        if not listeners:
            raise LookupError("No ELB Listeners found.")

        title("Available ELB Listeners")

        menu(
            "ELB Listeners",
            [
                (
                    index,
                    (f"{listener['name']} ({listener['arn']})"),
                )
                for index, listener in enumerate(
                    listeners,
                    start=1,
                )
            ],
        )

        listener = self._select_resource(
            listeners,
            "Select Listener",
        )

        if listener is None:
            return None

        return listener

    def select_elb_target(self, target_group_arn):

        targets = self.discovery.list_elb_targets(target_group_arn)

        if not targets:
            raise LookupError("No ELB Targets found.")

        title("Available ELB Targets")

        menu(
            "ELB Targets",
            [
                (
                    index,
                    target["name"],
                )
                for index, target in enumerate(
                    targets,
                    start=1,
                )
            ],
        )

        target = self._select_resource(
            targets,
            "Select Target",
        )

        if target is None:
            return None

        return target

    def select_multiple(self, service):

        service = service.lower()

        resources = self.get_resources(service)

        if not resources:
            raise LookupError(f"No {service} resources found.")

        title(f"Available {service.upper()} Resources")

        menu(
            f"{service.upper()} Resources",
            [
                (
                    index,
                    resource["name"],
                )
                for index, resource in enumerate(
                    resources,
                    start=1,
                )
            ],
        )

        print()
        print("Enter resource numbers separated by commas.")
        print("Example: 1,3,4")

        selection = prompt("Select Resources").strip()

        if not selection:
            return None

        try:
            indexes = [int(value.strip()) for value in selection.split(",")]
        except ValueError:
            error("Invalid selection.")
            return None

        selected = []

        for index in indexes:
            if index < 1 or index > len(resources):
                error(f"Invalid resource selection: {index}")
                return None

            resource = resources[index - 1]

            if resource not in selected:
                selected.append(resource)

        return selected

    def select(self, service):

        if service == "ecs_task":
            return self.select_ecs_task()

        if service == "ecs_service":
            return self.select_ecs_service()

        resources = self.get_resources(service)

        if not resources:
            raise LookupError(f"No {service} resources found.")

        title(f"Available {service.upper()} Resources")

        menu(
            f"{service.upper()} Resources",
            [
                (index, resource["name"])
                for index, resource in enumerate(resources, start=1)
            ],
        )

        return self._select_resource(
            resources,
            "Select Resource",
        )

    def select_child(self, parent_type, parent_id, child_type):

        #
        # Security Group -> Rules
        #

        if parent_type == "security-group" and child_type == "security-group-rule":
            resources = self.discovery.list_security_group_rules(parent_id)

            title("Available Security Group Rules")

            menu_title = "Security Group Rules"

            prompt_text = "Select Rule"

        #
        # EC2 -> EBS Volumes
        #

        elif parent_type == "ec2" and child_type == "ebs-volume":
            resources = self.discovery.list_ec2_ebs_volumes(parent_id)

            title("Attached EBS Volumes")

            menu_title = "EBS Volumes"

            prompt_text = "Select EBS Volume"

        #
        # EC2 -> Available EBS Volumes
        #

        elif parent_type == "ec2" and child_type == "ebs-volume-available":
            resources = self.discovery.list_available_ec2_ebs_volumes(parent_id)

            title("Available EBS Volumes")

            menu_title = "EBS Volumes"

            prompt_text = "Select EBS Volume"

        #
        # ASG -> Available EBS Volumes
        #

        elif (
            parent_type == "autoscaling-group"
            and child_type == "ebs-volume-asg-available"
        ):
            return self.select_available_ebs_volume_for_asg(parent_id)

        #
        # Route Table -> Routes
        #

        elif parent_type == "route-table" and child_type == "route":
            resources = self.discovery.list_routes(parent_id)

            title("Available Routes")

            menu_title = "Routes"

            prompt_text = "Select Route"

        #
        # Network ACL -> Entries
        #

        elif parent_type == "network-acl" and child_type == "network-acl-rule":
            resources = self.discovery.list_network_acl_rules(parent_id)

            title("Available Network ACL Rules")

            menu_title = "Network ACL Rules"

            prompt_text = "Select Rule"

        #
        # API Gateway -> Stages
        #

        elif parent_type == "apigateway" and child_type == "apigateway-stage":
            resources = self.discovery.list_apigateway_stages(parent_id)

            title("Available API Gateway Stages")

            menu_title = "API Gateway Stages"

            prompt_text = "Select Stage"

        #
        # ECS Cluster -> Services
        #

        elif parent_type == "ecs" and child_type == "ecs-service":
            resources = self.discovery.list_ecs_services(parent_id)

            title("Available ECS Services")

            menu_title = "ECS Services"

            prompt_text = "Select Service"

        #
        # EKS Cluster -> Nodes
        #

        elif parent_type == "eks" and child_type == "eks-node":
            resources = self.discovery.list_eks_nodes(parent_id)

            title("Available EKS Nodes")

            menu_title = "EKS Nodes"

            prompt_text = "Select Node"


        #
        # EKS Cluster -> Physical Machines
        #

        elif (
            parent_type == "eks"
            and child_type == "chaos-physical-machine"
        ):
            resources = self.discovery.list_chaos_physical_machines(parent_id)

            title("Available Physical Machines")

            menu_title = "Physical Machines"

            prompt_text = "Select Physical Machine"

        #
        # EKS Cluster -> Namespaces
        #

        elif parent_type == "eks" and child_type == "eks-namespace":
            resources = self.discovery.list_eks_namespaces(parent_id)

            title("Available EKS Namespaces")

            menu_title = "EKS Namespaces"

            prompt_text = "Select Namespace"

        #
        # EKS Namespace -> Deployments
        #

        elif parent_type == "eks-namespace" and child_type == "eks-deployment":
            resources = self.discovery.list_eks_deployments(
                parent_id[0],
                parent_id[1],
            )

            title("Available EKS Deployments")

            menu_title = "EKS Deployments"

            prompt_text = "Select Deployment"

        #
        # EKS Namespace -> Pods
        #

        elif parent_type == "eks-namespace" and child_type == "eks-pod":
            resources = self.discovery.list_eks_pods(
                parent_id[0],
                parent_id[1],
            )

            title("Available EKS Pods")

            menu_title = "EKS Pods"

            prompt_text = "Select Pod"

        #
        # EKS Pod -> Volumes
        #
        elif parent_type == "eks-pod" and child_type == "eks-volume":
            resources = self.discovery.list_eks_volumes(
                parent_id[0],
                parent_id[1],
                parent_id[2],
            )

            title("Available EKS Volumes")

            menu_title = "EKS Volumes"

            prompt_text = "Select Volume"

        #
        # ELB -> Target Groups
        #

        elif parent_type == "rds" and child_type == "rds-instance-class":
            resources = self.discovery.list_rds_instance_classes(parent_id)

            title("Available RDS Instance Classes")

            menu_title = "Valid RDS Instance Class Modifications"

            prompt_text = "Select Target Instance Class"

        #
        # ELB -> Target Groups
        #

        elif parent_type == "elb" and child_type == "elb-target-group":
            resources = self.discovery.list_elb_target_groups(parent_id)

            title("Available ELB Target Groups")

            menu_title = "ELB Target Groups"

            prompt_text = "Select Target Group"

        #
        # ELB -> Listeners
        #

        elif parent_type == "elb" and child_type == "elb-listener":
            resources = self.discovery.list_elb_listeners(parent_id)

            title("Available ELB Listeners")

            menu_title = "ELB Listeners"

            prompt_text = "Select Listener"

        #
        # ELB Target Group -> Targets
        #

        elif parent_type == "elb-target-group" and child_type == "elb-target":
            resources = self.discovery.list_elb_targets(parent_id)

            title("Available ELB Targets")

            menu_title = "ELB Targets"

            prompt_text = "Select Target"

        #
        # Unsupported Child Resource
        #

        else:
            raise ValueError(f"Unsupported child resource: {child_type}")

        #
        # No Resources
        #

        if not resources:
            if parent_type == "eks" and child_type == "eks-node":
                raise LookupError("No EKS Nodes found")

            raise LookupError(f"No {child_type} found.")

        #
        # Display Menu
        #

        menu(
            menu_title,
            [
                (index, resource["name"])
                for index, resource in enumerate(resources, start=1)
            ],
        )

        return self._select_resource(
            resources,
            prompt_text,
        )

    def _select_resource(
        self,
        resources,
        prompt_text,
    ):

        console.print()
        console.print("[bold cyan]0.[/bold cyan] Back")
        console.print("[bold cyan]M.[/bold cyan] Main Menu")
        console.print()

        while True:
            choice = prompt(prompt_text).strip().lower()

            if choice == "0":
                return None

            if choice == "m":
                raise BackToMainMenu

            try:
                resource = resources[int(choice) - 1]

                info(f"Selected : {resource['name']}")

                return resource

            except (ValueError, IndexError):
                error("Invalid Selection")

    def select_child_resources(
        self,
        parent_type,
        parent_id,
        child_type,
    ):

        if parent_type == "rds" and child_type == "rds-instance-class":
            return self.discovery.list_rds_instance_classes(parent_id)

        elif parent_type == "ecs" and child_type == "ecs-service":
            return self.discovery.list_ecs_services(parent_id)

        elif parent_type == "eks" and child_type == "eks-node":
            return self.discovery.list_eks_nodes(parent_id)

        elif parent_type == "eks" and child_type == "eks-namespace":
            return self.discovery.list_eks_namespaces(parent_id)

        elif (
            parent_type == "eks"
            and child_type == "chaos-physical-machine"
        ):
            return self.discovery.list_chaos_physical_machines(parent_id)

        elif parent_type == "eks-namespace" and child_type == "eks-deployment":
            return self.discovery.list_eks_deployments(
                parent_id[0],
                parent_id[1],
            )

        elif parent_type == "eks-namespace" and child_type == "eks-pod":
            return self.discovery.list_eks_pods(
                parent_id[0],
                parent_id[1],
            )

        elif parent_type == "eks-namespace" and child_type == "eks-container":
            cluster, namespace, target = parent_id
            return self.discovery.list_eks_containers(
                cluster,
                namespace,
                pod_name=target.get("pod", ""),
                deployment=target.get("deployment", ""),
            )

        elif parent_type == "eks-pod" and child_type == "eks-volume":
            return self.discovery.list_eks_volumes(
                parent_id[0],
                parent_id[1],
                parent_id[2],
            )

        elif parent_type == "apigateway" and child_type == "apigateway-stage":
            return self.discovery.list_apigateway_stages(parent_id)

        elif parent_type == "elb" and child_type == "elb-target-group":
            return self.discovery.list_elb_target_groups(parent_id)

        elif parent_type == "elb-target-group" and child_type == "elb-target":
            return self.discovery.list_elb_targets(parent_id)

        elif parent_type == "elb" and child_type == "elb-listener":
            return self.discovery.list_elb_listeners(parent_id)

        elif parent_type == "security-group" and child_type == "security-group-rule":
            return self.discovery.list_security_group_rules(parent_id)

        elif parent_type == "route-table" and child_type == "route":
            return self.discovery.list_routes(parent_id)

        elif parent_type == "network-acl" and child_type == "network-acl-rule":
            return self.discovery.list_network_acl_rules(parent_id)

        elif parent_type == "ec2" and child_type == "ebs-volume":
            return self.discovery.list_ec2_ebs_volumes(parent_id)

        elif parent_type == "ec2" and child_type == "ebs-volume-available":
            return self.discovery.list_available_ec2_ebs_volumes(parent_id)

        elif (
            parent_type == "autoscaling-group"
            and child_type == "ebs-volume-asg-available"
        ):
            return self.list_available_ebs_volumes_for_asg(parent_id)

        return []
