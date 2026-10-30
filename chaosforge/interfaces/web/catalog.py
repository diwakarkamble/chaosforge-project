"""Web presentation metadata for cloud and service cards."""

from chaosforge.application.discovery import discover_services, display_name

CLOUDS = {
    "aws": {
        "id": "aws",
        "name": "Amazon Web Services",
        "short_name": "AWS",
        "description": "Cloud services, AWS FIS, and Amazon EKS",
        "icon": "AWS-Cloud-logo_32.svg",
    },
    "azure": {
        "id": "azure",
        "name": "Microsoft Azure",
        "short_name": "Azure",
        "description": "Azure Chaos Studio and Chaos Toolkit resilience experiments",
        "icon": "Azure-Cloud.svg",
    },
}

SERVICE_ICONS = {
    "lambda": "Arch_AWS-Lambda_32.svg",
    "dynamodb": "Arch_Amazon-DynamoDB_32.svg",
    "rds": "Arch_Amazon-RDS_32.svg",
    "elasticache": "Arch_Amazon-ElastiCache_32.svg",
    "sns": "Arch_Amazon-Simple-Notification-Service_32.svg",
    "apigateway": "Arch_Amazon-API-Gateway_32.svg",
    "fis": "Arch_AWS-Fault-Injection-Service_32.svg",
    "ecs": "Arch_Amazon-Elastic-Container-Service_32.svg",
    "s3": "Arch_Amazon-Simple-Storage-Service_32.svg",
    "ec2": "EC2-instance-contents_32.svg",
    "elb": "Arch_Amazon-Elastic-Load-Balancing_32.svg",
    "eks": "Arch_Amazon-Elastic-Kubernetes-Service_32.svg",
    "vpc": "Arch_Amazon-Virtual-Private-Cloud_32.svg",
    "kinesis": "Arch_Amazon-Kinesis_32.svg",
    "aks": "Fluent-Cube.svg",
    "azure_redis": "Fluent-Flash.svg",
    "azure_vm": "Fluent-Server.svg",
    "azure_vmss": "Fluent-Server-Multiple.svg",
    "azure_app_service": "Fluent-Web-Asset.svg",
    "azure_key_vault": "Fluent-Key.svg",
    "azure_cosmos_db": "Fluent-Globe.svg",
    "azure_event_hub": "Fluent-Channel.svg",
    "azure_postgres_flexible": "Fluent-Database.svg",
    "azure_container_apps": "Fluent-Box.svg",
    "azure_functions": "Fluent-Code.svg",
}

SERVICE_DESCRIPTIONS = {
    "aks": "Managed Kubernetes experiments through Chaos Studio and Kubernetes",
    "azure_redis": "Redis reboot, flush, and access-disruption experiments",
    "azure_vm": "Classic Chaos Studio VM faults and Toolkit experiments",
    "azure_vmss": "Classic Chaos Studio scale-set faults and Toolkit experiments",
    "azure_app_service": "Classic stop fault and Toolkit experiments",
    "azure_key_vault": "Classic Chaos Studio Key Vault faults",
    "azure_cosmos_db": "Classic Chaos Studio failover fault",
    "azure_event_hub": "Classic Chaos Studio Event Hub state fault",
    "azure_postgres_flexible": "Chaos Toolkit experiment definitions",
    "azure_container_apps": "Revision restart, traffic-shift, and scale-to-zero experiments",
    "azure_functions": "Classic Chaos Studio App Service stop fault",
    "eks": "Managed Kubernetes with Toolkit, FIS, and direct Chaos Mesh",
    "lambda": "Serverless compute resilience experiments",
    "ec2": "Virtual machine and EBS resilience experiments",
    "kinesis": "Real-time streaming fault injection through AWS FIS",
}


def cloud_cards():
    return list(CLOUDS.values())


def service_cards(cloud):
    if cloud not in CLOUDS:
        raise ValueError(f"Unsupported cloud provider: {cloud}")
    cards = [
        {
            "id": service,
            "name": display_name(service),
            "icon": SERVICE_ICONS.get(
                service,
                "Azure-Cloud.svg" if cloud == "azure" else "AWS-Cloud_32.svg",
            ),
            "description": SERVICE_DESCRIPTIONS.get(
                service, "Configure and execute controlled resilience experiments"
            ),
        }
        for service in discover_services(cloud)
    ]
    if cloud == "aws":
        cards.extend(
            [
                {
                    "id": "fis",
                    "name": "AWS Fault Injection Service",
                    "icon": SERVICE_ICONS["fis"],
                    "description": "AWS-managed infrastructure fault injection",
                },
            ]
        )
    return cards


def service_cloud(service):
    return "azure" if service in {
        "aks", "azure_redis", "azure_vm", "azure_vmss", "azure_app_service",
        "azure_key_vault", "azure_cosmos_db", "azure_event_hub",
        "azure_postgres_flexible", "azure_container_apps", "azure_functions",
    } else "aws"
