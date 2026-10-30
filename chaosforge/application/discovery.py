from chaosforge.catalog import ExperimentCatalog

# Azure services drive the Add Experiment menu when cloud == "azure".
AZURE_SERVICES = {
    "aks", "azure_redis", "azure_vm", "azure_vmss", "azure_app_service",
    "azure_key_vault", "azure_cosmos_db", "azure_event_hub",
    "azure_postgres_flexible", "azure_container_apps", "azure_functions",
}

# Services that are available through AWS FIS only (no dedicated
# Chaos Toolkit experiment directory of their own).
FIS_ONLY_SERVICES = {
    "kinesis",
}


def discover_services(cloud="aws"):
    """Return service folder names for the given cloud provider."""
    services = []

    for service in ExperimentCatalog().list_services():
        if service.startswith("__"):
            continue

        #
        # Hide execution engines from normal service lists
        #
        if service.lower() in ("fis", "chaos_mesh"):
            continue

        if cloud == "azure":
            if service.lower() in AZURE_SERVICES:
                services.append(service)
        elif service.lower() not in AZURE_SERVICES:
            services.append(service)

    #
    # Add FIS-only services that do not have a
    # dedicated Chaos Toolkit experiment directory (AWS only —
    # these are not applicable to Azure).
    #
    if cloud != "azure":
        for service in FIS_ONLY_SERVICES:
            if service not in services:
                services.append(service)

    return sorted(services)


def display_name(service):

    names = {
        "lambda": "Amazon Lambda",
        "dynamodb": "Amazon DynamoDB",
        "rds": "Amazon RDS",
        "sns": "Amazon SNS",
        "fis": "AWS FIS",
        "eventbridge": "Amazon EventBridge",
        "s3": "Amazon S3",
        "elasticache": "Amazon ElastiCache",
        "ec2": "Amazon EC2",
        "vpc": "Amazon VPC",
        "apigateway": "Amazon API Gateway",
        "ecs": "Amazon ECS",
        "elb": "Amazon Elastic Load Balancing",
        "eks": "Amazon EKS",
        "kinesis": "Amazon Kinesis",
        "aks": "Azure Kubernetes Service (AKS)",
        "azure_redis": "Azure Cache for Redis",
        "azure_vm": "Azure Virtual Machines",
        "azure_vmss": "Azure Virtual Machine Scale Sets",
        "azure_app_service": "Azure App Service",
        "azure_key_vault": "Azure Key Vault",
        "azure_cosmos_db": "Azure Cosmos DB",
        "azure_event_hub": "Azure Event Hubs",
        "azure_postgres_flexible": "Azure Database for PostgreSQL Flexible Server",
        "azure_container_apps": "Azure Container Apps",
        "azure_functions": "Azure Functions",
    }

    return names.get(service.lower(), service.title())
