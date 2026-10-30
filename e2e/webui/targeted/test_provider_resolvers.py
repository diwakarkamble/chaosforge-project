import pytest

from e2e.webui.targeted.providers import aws, azure


@pytest.mark.parametrize(
    ("target_type", "target"),
    [
        ("name", "app-one"),
        ("resource_id", "arn:example:app-one"),
    ],
)
def test_aws_resolves_exact_name_or_id(monkeypatch, target_type, target):
    monkeypatch.setattr(
        aws,
        "_direct_resources",
        lambda _: [
            {"id": "arn:example:app-one", "name": "app-one"},
            {"id": "arn:example:app-two", "name": "app-two"},
        ],
    )

    config = {
        "cloud": "aws",
        "service": "lambda",
        "region": "eu-central-1",
        "target_type": target_type,
        "target": target,
    }

    result = aws.resolve_aws_targets(config)

    assert result == [
        {"id": "arn:example:app-one", "name": "app-one"}
    ]


def test_aws_tag_target_returns_matching_resources(monkeypatch):
    monkeypatch.setattr(
        aws,
        "_tagged_resources",
        lambda _: [
            {"id": "arn:example:app-one", "name": "app-one"}
        ],
    )

    config = {
        "cloud": "aws",
        "service": "lambda",
        "region": "eu-central-1",
        "target_type": "tags",
        "target": {"Environment": "E2E"},
    }

    assert len(aws.resolve_aws_targets(config)) == 1


@pytest.mark.parametrize(
    ("target_type", "target"),
    [
        ("name", "app-one"),
        ("resource_id", "/subscriptions/sub1/resourcegroups/rg1/"
                       "providers/microsoft.app/containerapps/app-one"),
        ("tags", {"Environment": "E2E"}),
    ],
)
def test_azure_resolves_configured_target(monkeypatch, target_type, target):
    resource = {
        "id": "/subscriptions/sub1/resourceGroups/rg1/providers/"
              "Microsoft.App/containerApps/app-one",
        "name": "app-one",
        "type": "Microsoft.App/containerApps",
        "tags": {"Environment": "E2E"},
    }

    monkeypatch.setattr(azure, "_run_az", lambda _: [resource])

    config = {
        "cloud": "azure",
        "service": "azure_container_apps",
        "resource_type": "Microsoft.App/containerApps",
        "resource_group": "rg1",
        "target_type": target_type,
        "target": target,
    }

    result = azure.resolve_azure_targets(config)

    assert len(result) == 1
    assert result[0]["name"] == "app-one"


def test_azure_rejects_missing_name(monkeypatch):
    monkeypatch.setattr(azure, "_run_az", lambda _: [])

    config = {
        "cloud": "azure",
        "service": "azure_container_apps",
        "resource_type": "Microsoft.App/containerApps",
        "target_type": "name",
        "target": "missing-app",
    }

    with pytest.raises(pytest.fail.Exception):
        azure.resolve_azure_targets(config)


def test_aws_supports_configured_service_types():
    assert {
        "s3",
        "lambda",
        "dynamodb",
        "elasticache",
        "rds",
        "sns",
        "elb",
        "kinesis",
    } <= set(aws.RESOURCE_TYPE_FILTERS)
