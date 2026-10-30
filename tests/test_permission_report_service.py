import json

from chaosforge.application.services.permissions import PermissionReportService
from chaosforge.models import Campaign, Experiment


class Catalog:
    def __init__(self, entries):
        self.entries = entries

    def get_experiment(self, service, experiment_id):
        return self.entries.get((service, experiment_id))


def experiment(service, experiment_id, variables=None):
    return Experiment(experiment_id, service, experiment_id, "x.json", variables or {})


def test_aws_policy_groups_deduplicated_actions_by_service_and_warns_about_scope():
    catalog = Catalog({("lambda", "one"): {"iam": {"read": ["lambda:GetFunction"], "modify": ["lambda:UpdateFunctionConfiguration"]}}, ("lambda", "two"): {"iam": {"read": ["lambda:GetFunction"]}}})
    report = PermissionReportService(catalog).generate(Campaign(experiments=[experiment("lambda", "one"), experiment("lambda", "two")]))
    assert report["policy"]["Statement"] == [{"Sid": "LambdaPermissions", "Effect": "Allow", "Action": ["lambda:GetFunction", "lambda:UpdateFunctionConfiguration"], "Resource": "*"}]
    assert "no resource-scoped mapping" in report["warnings"][0]


def test_fis_report_separates_runtime_control_plane_from_execution_role():
    catalog = Catalog({("fis", "fis-create-experiment"): {"iam": {
        "read": ["fis:GetExperiment", "sts:GetCallerIdentity"],
        "modify": ["fis:CreateExperimentTemplate", "fis:StartExperiment"],
        "additional": ["iam:PassRole"],
    }}})
    campaign = Campaign(experiments=[experiment("fis", "fis-create-experiment", {
        "service_id": "ec2", "experiment_id": "terminate-instances",
        "role_arn": "arn:aws:iam::123456789012:role/FIS",
    })])

    report = PermissionReportService(catalog).generate(campaign)

    runtime = report["iam"]["runtime"]
    assert [item["label"] for item in runtime] == ["AWS FIS control plane", "Pass the FIS execution role"]
    assert runtime[0]["actions"] == ["fis:CreateExperimentTemplate", "fis:GetExperiment", "fis:StartExperiment", "sts:GetCallerIdentity"]
    assert runtime[0]["experiments"] == [{"service": "fis", "id": "fis-create-experiment", "name": "fis-create-experiment", "reversibility": "reversible"}]
    assert report["iam"]["fis_execution"][0]["actions"] == ["ec2:DescribeInstances", "ec2:TerminateInstances"]
    assert report["iam"]["runtime"][1]["policy"]["Statement"][0]["Resource"] == ["arn:aws:iam::123456789012:role/FIS"]
    assert report["iam"]["fis_execution"][0]["policy"]["Statement"][0]["Resource"] == ["*"]
    assert report["iam"]["fis_execution"][0]["trust_policy"]["Statement"][0]["Principal"] == {"Service": "fis.amazonaws.com"}


def test_fis_report_includes_lambda_and_s3_action_specific_notes():
    catalog = Catalog({("fis", "fis-create-experiment"): {"iam": {}}})
    campaign = Campaign(experiments=[
        experiment("fis", "fis-create-experiment", {
            "service_id": "lambda", "experiment_id": "invocation-delay",
            "role_arn": "arn:aws:iam::123:role/FIS", "fis_config_bucket": "config-bucket",
        }),
        experiment("fis", "fis-create-experiment", {
            "service_id": "s3", "experiment_id": "pause-replication",
            "role_arn": "arn:aws:iam::123:role/FIS",
        }),
    ])

    service = PermissionReportService(catalog)
    requirements = service.generate(campaign)["iam"]["fis_execution"]

    assert any("s3:PutObject" in item["note"] for item in requirements)
    assert any("aws:s3:bucket-pause-replication" in item["note"] for item in requirements)
    rendered = service.render_terminal(campaign)
    assert "Lambda FIS also requires" in rendered
    assert "AWS FIS requires the S3 replication permissions" in rendered


def test_fis_report_does_not_invent_a_policy_for_an_unmodeled_action():
    catalog = Catalog({("fis", "fis-create-experiment"): {"iam": {}}})
    campaign = Campaign(experiments=[experiment("fis", "fis-create-experiment", {
        "service_id": "rds", "experiment_id": "reboot-instance",
        "role_arn": "arn:aws:iam::123:role/FIS",
    })])

    requirement = PermissionReportService(catalog).generate(campaign)["iam"]["fis_execution"][0]

    assert requirement["actions"] == []
    assert requirement["policy"] is None


def test_azure_classic_sdk_and_aks_requirements_are_separated_and_deduplicated():
    catalog = Catalog({("azure_vm", "azure-vm-shutdown"): {"engine": "Azure Chaos Studio"}, ("azure_redis", "azure-redis-flush"): {"engine": "Azure SDK"}, ("aks", "aks-pod-kill"): {}})
    campaign = Campaign(cloud_provider="azure", experiments=[experiment("azure_vm", "azure-vm-shutdown", {"resource_id": "/vm"}), experiment("azure_vm", "azure-vm-shutdown", {"resource_id": "/vm"}), experiment("azure_redis", "azure-redis-flush", {"resource_id": "/redis"}), experiment("aks", "aks-pod-kill", {"subscription_id": "sub"})])
    report = PermissionReportService(catalog).generate(campaign)
    assert report["rbac"]["chaos_studio_uami"] == [requirement("Virtual Machine Contributor", "/vm", "$CHAOS_STUDIO_UAMI_PRINCIPAL_ID", ["azure-vm-shutdown"])]
    assert report["rbac"]["runtime"] == [requirement("Contributor", "/redis", "$RUNTIME_PRINCIPAL_ID", ["azure-redis-flush"]), requirement("Contributor", "/subscriptions/sub", "$RUNTIME_PRINCIPAL_ID", ["aks-pod-kill"])]
    assert report["rbac"]["bootstrap"] == [
        requirement("Managed Identity Contributor", "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$IDENTITY_RESOURCE_GROUP", "$BOOTSTRAP_PRINCIPAL_ID", ["azure-vm-shutdown"]),
        alternative_requirement(
            ["User Access Administrator", "Owner"],
            "/vm",
            "$BOOTSTRAP_PRINCIPAL_ID",
        ),
    ]
    assert "subscription scope" in report["warnings"][0]


def requirement(role, scope, principal, experiment_ids):
    return {"role": role, "scope": scope, "principal_id": principal, "principal_type": "ServicePrincipal", "experiments": [{"service": "azure_vm" if value == "azure-vm-shutdown" else "azure_redis" if value == "azure-redis-flush" else "aks", "id": value, "name": value, "reversibility": "reversible"} for value in experiment_ids], "command": f"az role assignment create --assignee-object-id {principal} --assignee-principal-type ServicePrincipal --role '{role}' --scope {scope}"}


def alternative_requirement(roles, scope, principal):
    return {
        "role": " or ".join(roles),
        "alternatives": roles,
        "scope": scope,
        "principal_id": principal,
        "principal_type": "ServicePrincipal",
        "experiments": [{"service": "azure_vm", "id": "azure-vm-shutdown", "name": "azure-vm-shutdown", "reversibility": "reversible"}],
        "commands": [
            f"az role assignment create --assignee-object-id {principal} --assignee-principal-type ServicePrincipal --role '{role}' --scope {scope}"
            for role in roles
        ],
    }


def test_redis_classic_uses_its_uami_role_and_renderers_are_read_only():
    catalog = Catalog({("azure_redis", "azure-redis-reboot"): {"engine": "Azure Chaos Studio"}})
    service = PermissionReportService(catalog)
    campaign = Campaign(cloud_provider="azure", experiments=[experiment("azure_redis", "azure-redis-reboot")])
    report = service.generate(campaign)
    assert report["rbac"]["chaos_studio_uami"][0]["role"] == "Redis Cache Contributor"
    assert "$RESOURCE_ID" in report["rbac"]["chaos_studio_uami"][0]["command"]
    assert json.loads(service.render_json(campaign))["provider"] == "azure"
    assert "## Chaos Studio Identity" in service.render_markdown(campaign)
    assert service.render_terminal(campaign) == service.render_markdown(campaign)


def test_azure_bootstrap_uses_target_resource_group_when_available():
    catalog = Catalog({("azure_vm", "azure-vm-shutdown"): {"engine": "Azure Chaos Studio"}})
    campaign = Campaign(
        cloud_provider="azure",
        experiments=[
            experiment(
                "azure_vm",
                "azure-vm-shutdown",
                {"resource_id": "/subscriptions/sub/resourceGroups/identity-rg/providers/Microsoft.Compute/virtualMachines/vm"},
            )
        ],
    )

    report = PermissionReportService(catalog).generate(campaign)

    assert requirement(
        "Managed Identity Contributor",
        "/subscriptions/sub/resourceGroups/identity-rg",
        "$BOOTSTRAP_PRINCIPAL_ID",
        ["azure-vm-shutdown"],
    ) in report["rbac"]["bootstrap"]


def test_markdown_renderer_omits_warning_section_when_none_exist():
    catalog = Catalog({("lambda", "one"): {"iam": {"read": ["lambda:GetFunction"]}}})
    campaign = Campaign(experiments=[experiment("lambda", "one")])
    service = PermissionReportService(catalog)
    report = service.generate(campaign)
    report["warnings"] = []
    service.generate = lambda _: report

    assert "## Warnings" not in service.render_markdown(campaign)


def test_markdown_renderer_shows_fis_runtime_and_execution_role_policies():
    catalog = Catalog({("fis", "fis-create-experiment"): {"iam": {"additional": ["iam:PassRole"]}}})
    campaign = Campaign(experiments=[experiment("fis", "fis-create-experiment", {
        "service_id": "ec2", "experiment_id": "reboot-instances",
        "role_arn": "arn:aws:iam::123:role/FIS", "target_arn": "arn:aws:ec2:region:123:instance/i-1",
    })])

    rendered = PermissionReportService(catalog).render_terminal(campaign)

    assert "## ChaosForge Runtime Identity" in rendered
    assert "## AWS FIS Execution Role" in rendered
    assert "iam:PassRole" in rendered
    assert "ec2:RebootInstances" in rendered
    assert "FIS trust policy" in rendered


def test_report_warns_about_unknown_catalog_experiment_and_renders_empty_azure_sections():
    service = PermissionReportService(Catalog({}))
    aws = Campaign(experiments=[experiment("lambda", "missing")])
    azure = Campaign(cloud_provider="azure", experiments=[experiment("azure_vm", "missing")])

    assert "No catalog metadata found" in service.generate(aws)["warnings"][0]
    report = service.generate(azure)
    assert report["rbac"] == {"runtime": [], "chaos_studio_uami": [], "bootstrap": []}
    assert "No modeled permission requirements." in service.render_markdown(azure)


def test_aks_permission_scope_uses_subscription_from_resource_id_when_variable_missing():
    service = PermissionReportService(Catalog({("aks", "aks-pod-kill"): {}}))
    campaign = Campaign(
        cloud_provider="azure",
        experiments=[
            experiment(
                "aks",
                "aks-pod-kill",
                {"resource_id": "/subscriptions/arm-sub/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/cluster"},
            )
        ],
    )

    report = service.generate(campaign)

    assert report["rbac"]["runtime"][0]["scope"] == "/subscriptions/arm-sub"
