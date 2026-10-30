"""Tag-resolvable component roots available to manifest-free tag mode."""

from chaosforge.application.metadata_loader import load_metadata
from chaosforge.providers.aws.fis.catalog import FISCatalog
from e2e.webui.functional.manifest import ManifestError

TAG_CATALOG = {
    "aws": {
        "apigateway": {},
        "dynamodb": {},
        "ec2": {},
        "ecs": {},
        "eks": {},
        "elasticache": {},
        "elb": {},
        "lambda": {},
        "kinesis": {},
        "rds": {},
        "s3": {},
        "sns": {},
        "vpc": {},
    },
    "azure": {
        "azure_vm": {
            "resource_type": "Microsoft.Compute/virtualMachines",
        },
        "azure_vmss": {
            "resource_type": "Microsoft.Compute/virtualMachineScaleSets",
        },
        "azure_app_service": {
            "resource_type": "Microsoft.Web/sites",
        },
        "azure_functions": {
            "resource_type": "Microsoft.Web/sites",
        },
        "azure_key_vault": {
            "resource_type": "Microsoft.KeyVault/vaults",
        },
        "azure_cosmos_db": {
            "resource_type": "Microsoft.DocumentDB/databaseAccounts",
        },
        "azure_event_hub": {
            "resource_type": "Microsoft.EventHub/namespaces",
        },
        "azure_postgres_flexible": {
            "resource_type": "Microsoft.DBforPostgreSQL/flexibleServers",
        },
        "azure_container_apps": {
            "resource_type": "Microsoft.App/containerApps",
        },
        "azure_redis": {
            "resource_type": "Microsoft.Cache/Redis",
        },
    },
}

# Live functional tests verify wiring and recovery, not resilience over a long
# observation window. Input files can override these values per run.
FUNCTIONAL_DEFAULTS = {
    "duration": "PT1M",
    "duration_seconds": 60,
    "fault_duration_seconds": 60,
    "wait_seconds": 60,
}

# Defaults represent the least-surprising reversible fault behavior for E2E.
# Developers can override them through --e2e-inputs when a fixture needs a
# different scenario.
EXPERIMENT_DEFAULTS = {
    ("azure_event_hub", "azure-event-hub-state"): {"desired_state": "Disabled"},
}

# Metadata occasionally represents a dependent resource as a text field (or a
# component-specific input).  These contracts make that relationship available
# to the E2E provider graph without changing production metadata or the UI.
GRAPH_CONTRACTS = {
    "elasticache": {
        "fields": {
            "target_security_group_id": {"resource_type": "security-group", "parent": "replication_group_id"},
        },
    },
    "azure_vmss": {
        "fields": {
            "instances": {"resource_type": "azure_vmss_instances", "parent": "resource_id"},
            "instance_criteria": {"resource_type": "azure_vmss_instances", "parent": "resource_id"},
        },
    },
    "azure_app_service": {
        "fields": {"source_slot": {"resource_type": "azure_app_service_slots", "parent": "resource_id"}},
    },
    "azure_functions": {
        "fields": {"source_slot": {"resource_type": "azure_function_slots", "parent": "resource_id"}},
    },
    "azure_container_apps": {
        "fields": {"revision_name": {"resource_type": "azure_container_app_revisions", "parent": "resource_id"}},
    },
    "azure_key_vault": {
        "fields": {
            "certificate_name": {"resource_type": "azure_key_vault_certificates", "parent": "resource_id"},
            "secret_name": {"resource_type": "azure_key_vault_secrets", "parent": "resource_id"},
        },
    },
    "azure_postgres_flexible": {
        "fields": {"rule_name": {"resource_type": "azure_postgres_flexible_firewall_rules", "parent": "resource_id"}},
    },
    "azure_cosmos_db": {
        "fields": {"read_region": {"resource_type": "azure_cosmos_db_regions", "parent": "resource_id"}},
    },
    "azure_redis": {
        "fields": {"redis_name": {"resource_type": "Microsoft.Cache/Redis"}},
    },
    # Kubernetes descendants need an authenticated kubectl context, which the
    # AWS API resolver deliberately does not attempt to manufacture.
    "eks": {"skip_reason": "EKS child discovery requires a Kubernetes context and is unsupported in tag-mode E2E."},
}


def graph_resource_fields(cloud, service, fields):
    """Return metadata resource inputs plus catalog-declared graph children."""
    contract = GRAPH_CONTRACTS.get(service, {}).get("fields", {})
    result = []
    for field in fields:
        override = contract.get(field.get("name"))
        is_resource = (
            field.get("type") == "aws_resource"
            if cloud == "aws"
            else field.get("type") == "azure_component_resource"
        )
        if not is_resource and not override:
            continue
        projected = dict(field)
        if override:
            projected.update(override)
            projected["type"] = "aws_resource" if cloud == "aws" else "azure_component_resource"
        result.append(projected)
    return result


def graph_skip_reason(service):
    return GRAPH_CONTRACTS.get(service, {}).get("skip_reason", "")


def validate_tag_catalog():
    """Reject roots without installed metadata before browser collection begins."""
    for services in TAG_CATALOG.values():
        for service, config in services.items():
            metadata = load_metadata(service) or {}
            if not metadata.get("experiments") and not FISCatalog().get_experiments(service):
                raise ManifestError(f"Built-in E2E catalog has no metadata experiments for {service}.")


def experiment_metadata(service, experiment_id):
    metadata = load_metadata(service) or {}
    return next(
        (item for item in metadata.get("experiments", []) if item.get("id") == experiment_id),
        None,
    )


def catalog_experiments(service, config):
    """Return installed experiments, retaining an explicit list for test fixtures."""
    configured = config.get("experiments")
    if configured is not None:
        return [
            {**(experiment_metadata(service, item["id"]) or {}), **item}
            for item in configured
        ]
    return (load_metadata(service) or {}).get("experiments", [])
