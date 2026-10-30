from unittest.mock import MagicMock

import pytest
import yaml

from chaosforge.application.services.campaign_yaml import CampaignYAMLService
from chaosforge.models import Campaign, Experiment


def _service(validation=None):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "id": "lambda-timeout",
        "name": "Lambda Timeout",
        "json": "lambda-timeout-chaos.json",
    }
    catalog.definition_path.return_value = "/tmp/lambda.json"
    validator = MagicMock()
    validator.validate_campaign.return_value = validation or {
        "valid": True,
        "experiments": [],
    }
    return CampaignYAMLService(catalog, validator), catalog, validator


def _yaml(provider="aws", service="lambda", experiment="lambda-timeout", environment=True):
    environment_block = ""
    if environment:
        identity = "account_id: '123456789012'" if provider.lower() == "aws" else "subscription_id: 'sub'"
        environment_block = f"environment:\n  {identity}\n"
    return f"""campaign:
  name: Uploaded Campaign
  continue_on_failure: true
cloud:
  provider: {provider}
{environment_block}experiments:
  - service: {service}
    experiment: {experiment}
    variables:
      aws_region: eu-central-1
      lambda_name: demo
      target_timeout: 10
""".encode()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("text", "must be bytes"),
        (b"", "empty"),
        (b"abc\x00def", "NUL"),
        (b"\xff", "UTF-8"),
        (b"---\na: 1\n---\nb: 2\n", "exactly one document"),
        (b"campaign: [\n", "Invalid YAML"),
    ],
)
def test_rejects_unsafe_or_invalid_content(content, message):
    service, _, _ = _service()

    review = service.inspect_bytes(content)

    assert review.valid is False
    assert message in review.errors[0]


def test_campaign_import_uses_safe_duplicate_key_loader_without_generic_yaml_load(monkeypatch):
    service, _, _ = _service()
    monkeypatch.setattr(
        "chaosforge.application.services.campaign_yaml.yaml.load_all",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsafe parser path")),
    )

    review = service.inspect_bytes(_yaml())

    assert review.valid is True


def test_rejects_oversized_and_duplicate_key_content():
    service, _, _ = _service()

    oversized = service.inspect_bytes(b"a" * 11, max_bytes=10)
    duplicate = service.inspect_bytes(b"campaign: {}\ncampaign: {}\nexperiments: []\n")

    assert "exceeds" in oversized.errors[0]
    assert "duplicate key" in duplicate.errors[0]


def test_structural_errors_are_returned_without_catalog_conversion():
    service, catalog, validator = _service()

    review = service.inspect_bytes(b"campaign: {}\n")

    assert review.valid is False
    assert "experiments: is required" in review.errors[0]
    catalog.get_experiment.assert_not_called()
    validator.validate_campaign.assert_not_called()


def test_valid_campaign_uses_catalog_factory_and_normalizes_provider():
    service, catalog, validator = _service()

    review = service.inspect_bytes(b"\xef\xbb\xbf" + _yaml(provider="AWS"))

    assert review.valid is True
    assert review.campaign.name == "Uploaded Campaign"
    assert review.campaign.cloud_provider == "aws"
    assert review.campaign.continue_on_failure is True
    assert review.campaign.experiments[0].engine == "Chaos Toolkit"
    catalog.get_experiment.assert_called_once_with("lambda", "lambda-timeout")
    validator.validate_campaign.assert_called_once_with(review.campaign)


def test_rejects_exact_duplicate_experiments():
    service, _, validator = _service()
    content = _yaml().replace(
        b"      target_timeout: 10\n",
        b"      target_timeout: 10\n  - service: lambda\n    experiment: lambda-timeout\n    variables:\n      aws_region: eu-central-1\n      lambda_name: demo\n      target_timeout: 10\n",
    )

    review = service.inspect_bytes(content)

    assert review.valid is False
    assert "experiments[1] duplicates experiments[0]" in review.errors[0]
    validator.validate_campaign.assert_not_called()


def test_allows_the_same_yaml_experiment_with_a_different_target():
    service, _, _ = _service()
    content = _yaml().replace(
        b"      target_timeout: 10\n",
        b"      target_timeout: 10\n  - service: lambda\n    experiment: lambda-timeout\n    variables:\n      aws_region: eu-central-1\n      lambda_name: other\n      target_timeout: 10\n",
    )

    review = service.inspect_bytes(content)

    assert review.valid is True
    assert len(review.campaign.experiments) == 2


def test_yaml_accepts_azure_resource_name_alias_without_live_resolution():
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "id": "azure-vm-toolkit-reboot",
        "name": "Reboot VM",
        "json": "reboot.json",
        "engine": "Azure SDK",
        "inputs": [{"name": "resource_id", "type": "azure_component_resource", "required": True}],
    }
    catalog.definition_path.return_value = "/tmp/reboot.json"
    validator = MagicMock()
    validator.validate_campaign.return_value = {"valid": True, "experiments": []}
    service = CampaignYAMLService(catalog, validator)
    content = b"""campaign:
  name: Azure name target
cloud:
  provider: azure
environment:
  subscription_id: sub
experiments:
  - service: azure_vm
    experiment: azure-vm-toolkit-reboot
    variables:
      resource_name: vm-a
      resource_group: rg
"""

    review = service.inspect_bytes(content)

    assert review.valid is True
    assert review.campaign.experiments[0].variables["resource_name"] == "vm-a"


def test_yaml_timezone_setting_is_preserved_for_report_presentation():
    service, _, _ = _service()
    content = _yaml().replace(
        b"experiments:", b"settings:\n  timezone: Asia/Shanghai\nexperiments:"
    )

    review = service.inspect_bytes(content)

    assert review.valid is True
    assert review.campaign.report_timezone == "Asia/Shanghai"
    assert b"timezone: Asia/Shanghai" in service.export_bytes(
        review.campaign,
        environment={"account_id": "123456789012"},
    )


def test_executable_campaign_requires_environment_identity_but_template_does_not():
    service, _, _ = _service()

    missing = service.inspect_bytes(_yaml(environment=False))
    template = service.inspect_bytes(_yaml(environment=False).replace(b"experiments:", b"template: true\nexperiments:"))

    assert "environment: is required" in missing.errors[0]
    assert template.valid is True
    assert template.is_template is True


def test_template_must_be_a_boolean():
    service, _, _ = _service()

    review = service.inspect_bytes(_yaml(environment=False).replace(b"experiments:", b"template: not-a-boolean\nexperiments:"))

    assert review.valid is False
    assert review.errors == ("template: must be a boolean.",)


def test_campaign_from_bytes_returns_valid_campaign():
    service, _, _ = _service()

    campaign = service.campaign_from_bytes(_yaml())

    assert campaign.name == "Uploaded Campaign"
    assert campaign.experiments[0].id == "lambda-timeout"


def test_export_includes_executable_environment_or_marks_template():
    service, _, _ = _service()
    campaign = Campaign(
        name="Exported",
        cloud_provider="aws",
        experiments=[Experiment("lambda-timeout", "lambda", "Lambda", "file", {"lambda_name": "demo"})],
    )

    executable = yaml.safe_load(service.export_bytes(campaign, environment={"account_id": "123"}))
    template = yaml.safe_load(service.export_bytes(campaign))

    assert executable["environment"]["account_id"] == "123"
    assert "template" not in executable
    assert template["template"] is True


def test_expected_provider_and_service_provider_mismatch_are_rejected():
    service, _, _ = _service()

    wrong_selected_cloud = service.inspect_bytes(
        _yaml(), expected_provider="azure"
    )
    wrong_service = service.inspect_bytes(
        _yaml(provider="azure", service="lambda")
    )

    assert "but 'azure' is selected" in wrong_selected_cloud.errors[0]
    assert "does not belong" in wrong_service.errors[0]


def test_missing_catalog_experiment_is_rejected():
    service, catalog, _ = _service()
    catalog.get_experiment.return_value = None

    review = service.inspect_bytes(_yaml())

    assert review.valid is False
    assert "not found" in review.errors[0]


def test_semantic_errors_and_warnings_are_preserved():
    service, _, _ = _service(
        {
            "valid": False,
            "experiments": [
                {
                    "experiment_id": "lambda-timeout",
                    "errors": ["missing function"],
                    "warnings": ["unknown variable"],
                }
            ],
        }
    )

    review = service.inspect_bytes(_yaml())

    assert review.valid is False
    assert review.errors == ("lambda-timeout: missing function",)
    assert review.warnings == ("lambda-timeout: unknown variable",)
    assert review.campaign is not None


def test_campaign_from_bytes_raises_combined_validation_error():
    service, _, _ = _service()

    with pytest.raises(ValueError, match="experiments: is required"):
        service.campaign_from_bytes(b"campaign: {}\n")


def test_export_is_portable_and_round_trips():
    campaign = Campaign(
        name="Resilience test",
        continue_on_failure=True,
        cloud_provider="aws",
        experiments=[
            Experiment(
                id="lambda-timeout",
                service="lambda",
                name="Display only",
                json_file="/local/path.json",
                variables={"aws_region": "eu-central-1", "nested": [1, {"ok": True}]},
                engine="Different derived value",
                target_service="lambda",
                status="SUCCESS",
            )
        ],
    )
    service, _, _ = _service()

    content = service.export_bytes(campaign)
    document = yaml.safe_load(content)
    review = service.inspect_bytes(content)

    assert document["campaign"] == {
        "name": "Resilience test",
        "continue_on_failure": True,
        "irreversible_operations_acknowledged": False,
    }
    assert set(document["experiments"][0]) == {"service", "experiment", "variables"}
    assert review.valid is True
    assert review.campaign.experiments[0].name == "Lambda Timeout"


@pytest.mark.parametrize("status", ["Pending", "SUCCESS", "FAILED"])
def test_export_preserves_variables_regardless_of_execution_status(status):
    variables = {
        "bucket_name": "chao-poc-ui",
        "aws_region": "eu-central-1",
        "policy_template": "readonly",
        "wait_seconds": 30,
        "region": "eu-central-1",
    }
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[
            Experiment(
                "s3-bucket-policy",
                "s3",
                "Bucket Policy",
                "file",
                dict(variables),
                status=status,
            )
        ],
    )

    document = yaml.safe_load(CampaignYAMLService().export_bytes(campaign))

    assert document["experiments"][0]["variables"] == variables


def test_export_rejects_nonportable_variable():
    campaign = Campaign(
        experiments=[
            Experiment("id", "lambda", "Name", "file", {"bad": object()})
        ]
    )

    with pytest.raises(TypeError, match="not portable"):
        CampaignYAMLService().export_bytes(campaign)


def test_azure_factory_identity_is_restored_from_yaml():
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "id": "aks-pod-kill",
        "name": "Pod Kill",
        "json": "aks-chaos.json",
    }
    catalog.definition_path.return_value = "/tmp/aks.json"
    validator = MagicMock()
    validator.validate_campaign.return_value = {"valid": True, "experiments": []}
    service = CampaignYAMLService(catalog, validator)
    content = _yaml(provider="azure", service="aks", experiment="aks-pod-kill")

    review = service.inspect_bytes(content)

    assert review.valid is True
    experiment = review.campaign.experiments[0]
    assert experiment.engine == "Azure Chaos Studio"
    assert experiment.variables["experiment_id"] == "aks-pod-kill"
