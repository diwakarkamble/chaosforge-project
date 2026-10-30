import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from chaosforge.application.services.campaign_executor import CampaignExecutor
from chaosforge.engines.chaos_mesh.version_policy import ChaosMeshVersionAssessment
from chaosforge.interfaces.cli import main as cli_main
from chaosforge.models import Campaign, Experiment


def _chaos_mesh_campaign():
    return Campaign(
        name="Mesh",
        cloud_provider="aws",
        experiments=[Experiment(
            "chaos-mesh-pod-kill", "chaos_mesh", "Pod Kill", "file.json",
            {"aws_region": "eu-central-1", "eks_cluster": "cluster"},
            engine="Chaos Mesh",
        )],
    )


def test_interactive_chaos_mesh_version_choice_is_reused(monkeypatch):
    campaign = _chaos_mesh_campaign()
    assessment = ChaosMeshVersionAssessment(
        "eu-central-1:cluster", "cluster", "eu-central-1", "older", "2.8.4"
    )
    monkeypatch.setattr(cli_main, "assess_campaign", lambda _: [assessment])
    monkeypatch.setattr(cli_main, "_active_campaign", lambda: campaign)
    prompt = MagicMock(return_value="2")
    monkeypatch.setattr(cli_main, "prompt", prompt)
    save = MagicMock()
    monkeypatch.setattr(cli_main, "save_chaos_mesh_version_decisions", save)

    assert cli_main.confirm_chaos_mesh_versions(campaign, persist=True)
    assert campaign.experiments[0].chaos_mesh_version_action == "continue"
    save.assert_called_once()

    campaign.chaos_mesh_version_decisions = save.call_args.args[0]
    prompt.reset_mock()
    assert cli_main.confirm_chaos_mesh_versions(campaign, persist=True)
    prompt.assert_not_called()


@pytest.mark.parametrize(
    ("state", "policy", "expected"),
    [
        ("absent", "upgrade", True),
        ("absent", "require-current", False),
        ("older", "allow-older", True),
        ("older", "require-current", False),
        ("newer", "require-current", True),
        ("incompatible", "upgrade", False),
    ],
)
def test_noninteractive_chaos_mesh_policies(monkeypatch, state, policy, expected):
    campaign = _chaos_mesh_campaign()
    version = None if state == "absent" else "2.8.4"
    if state == "newer":
        version = "2.8.8"
    if state == "incompatible":
        version = "2.9.0"
    assessment = ChaosMeshVersionAssessment(
        "eu-central-1:cluster", "cluster", "eu-central-1", state, version
    )
    monkeypatch.setattr(cli_main, "assess_campaign", lambda _: [assessment])

    assert cli_main.confirm_chaos_mesh_versions(campaign, policy=policy) is expected


def _campaign():
    return Campaign(
        name="CLI Campaign",
        cloud_provider="aws",
        experiments=[
            Experiment(
                "lambda-timeout",
                "lambda",
                "Lambda Timeout",
                "file.json",
                {"aws_region": "eu-central-1", "lambda_name": "demo"},
            )
        ],
    )


def test_export_campaign_yaml_writes_service_bytes(tmp_path, monkeypatch):
    source = _campaign()
    monkeypatch.setattr(cli_main, "campaign", source)
    export = MagicMock(return_value=b"campaign yaml")
    monkeypatch.setattr(cli_main.campaign_yaml_service, "export_bytes", export)
    report_success = MagicMock()
    monkeypatch.setattr(cli_main, "success", report_success)
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"account_id": "123", "name": "engineering"}),
    )

    path = cli_main.export_campaign_yaml(tmp_path / "campaign")

    assert path == tmp_path / "campaign.yaml"
    assert path.read_bytes() == b"campaign yaml"
    export.assert_called_once_with(
        source,
        environment={"account_id": "123", "account_alias": "engineering"},
    )
    report_success.assert_called_once()


def test_export_campaign_yaml_rejects_empty_and_write_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_main, "campaign", Campaign())
    warning = MagicMock()
    monkeypatch.setattr(cli_main, "warning", warning)
    assert cli_main.export_campaign_yaml(tmp_path / "empty.yaml") is None
    warning.assert_called_once_with("Campaign is empty.")

    monkeypatch.setattr(cli_main, "campaign", _campaign())
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"account_id": "123", "name": "engineering"}),
    )
    monkeypatch.setattr(
        cli_main.campaign_yaml_service,
        "export_bytes",
        MagicMock(side_effect=TypeError("bad value")),
    )
    error = MagicMock()
    monkeypatch.setattr(cli_main, "error", error)
    assert cli_main.export_campaign_yaml(tmp_path / "bad.yaml") is None
    error.assert_called_once_with("Failed to export campaign YAML: bad value")


@pytest.mark.parametrize("status", ["SUCCESS", "FAILED"])
def test_cli_yaml_export_preserves_variables_after_campaign_execution(
    tmp_path, monkeypatch, status
):
    variables = {
        "bucket_name": "chao-poc-ui",
        "aws_region": "eu-central-1",
        "policy_template": "readonly",
        "wait_seconds": 30,
        "region": "eu-central-1",
    }
    source = Campaign(
        cloud_provider="aws",
        experiments=[
            Experiment(
                "s3-bucket-policy",
                "s3",
                "Bucket Policy",
                "file.json",
                dict(variables),
            )
        ],
    )
    monkeypatch.setattr(cli_main, "campaign", source)
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"account_id": "123", "name": "engineering"}),
    )
    monkeypatch.setattr(cli_main, "success", MagicMock())

    def mutate_runtime_variables(experiment):
        experiment.variables.clear()
        experiment.status = status

    CampaignExecutor().execute(source, mutate_runtime_variables)
    path = cli_main.export_campaign_yaml(tmp_path / "campaign.yaml")

    assert path is not None
    document = yaml.safe_load(path.read_bytes())
    assert document["experiments"][0]["variables"] == variables


def test_import_yaml_replaces_campaign_and_context(tmp_path, monkeypatch):
    path = tmp_path / "azure.yaml"
    path.write_bytes(b"yaml")
    imported = Campaign(name="Imported", cloud_provider="azure", experiments=[])
    review = SimpleNamespace(
        valid=True,
        campaign=imported,
        errors=(),
        document={"environment": {"subscription_id": "sub"}},
    )
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=str(path)))
    monkeypatch.setattr(
        cli_main.campaign_yaml_service,
        "inspect_bytes",
        MagicMock(return_value=review),
    )
    replace = MagicMock(side_effect=lambda source: setattr(cli_main, "campaign", source))
    monkeypatch.setattr(cli_main, "replace_campaign", replace)
    monkeypatch.setattr(
        cli_main,
        "create_campaign_draft",
        MagicMock(return_value=Campaign(
            name="Imported", cloud_provider="azure", campaign_id="campaign-new",
            created_at="created", updated_at="updated",
        )),
    )
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    monkeypatch.setattr(cli_main, "success", MagicMock())
    monkeypatch.setattr(cli_main.campaign_preflight, "preflight", MagicMock(return_value=SimpleNamespace(ready=True)))
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "label": "AWS", "name": "Test"}),
    )

    original_cloud = cli_main.context.cloud
    original_region = cli_main.context.region
    try:
        cli_main.context.cloud = "azure"
        cli_main.context.region = "azure"
        cli_main.import_yaml_campaign()

        assert imported.campaign_id == "campaign-new"
        assert imported.created_at == "created"
        assert imported.updated_at == "updated"

        replace.assert_called_once_with(imported)
        assert cli_main.context.cloud == "azure"
        assert cli_main.context.region == "azure"
    finally:
        cli_main.context.cloud = original_cloud
        cli_main.context.region = original_region


def test_import_yaml_validation_failure_does_not_replace(tmp_path, monkeypatch):
    path = tmp_path / "bad.yaml"
    path.write_bytes(b"bad")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=str(path)))
    monkeypatch.setattr(
        cli_main.campaign_yaml_service,
        "inspect_bytes",
        MagicMock(return_value=SimpleNamespace(valid=False, errors=("invalid",))),
    )
    replace = MagicMock()
    monkeypatch.setattr(cli_main, "replace_campaign", replace)
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    error = MagicMock()
    monkeypatch.setattr(cli_main, "error", error)
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main.context, "region", "eu-west-1")
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "label": "AWS", "name": "Test"}),
    )

    cli_main.import_yaml_campaign()

    replace.assert_not_called()
    error.assert_called_once_with("Campaign YAML validation failed.")


def test_import_yaml_preflight_failure_does_not_replace(tmp_path, monkeypatch):
    path = tmp_path / "missing-target.yaml"
    path.write_bytes(b"yaml")
    campaign = Campaign(name="Blocked", cloud_provider="aws")
    review = SimpleNamespace(
        valid=True,
        campaign=campaign,
        errors=(),
        document={"environment": {"account_id": "123"}},
    )
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main.context, "region", "eu-west-1")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=str(path)))
    monkeypatch.setattr(cli_main.campaign_yaml_service, "inspect_bytes", MagicMock(return_value=review))
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "account_id": "123", "name": "engineering"}),
    )
    monkeypatch.setattr(
        cli_main.campaign_preflight,
        "preflight",
        MagicMock(return_value=SimpleNamespace(ready=False, errors=("Lambda 'missing' was not found.",))),
    )
    replace = MagicMock()
    monkeypatch.setattr(cli_main, "replace_campaign", replace)
    report_error = MagicMock()
    monkeypatch.setattr(cli_main, "error", report_error)
    monkeypatch.setattr(cli_main, "pause", MagicMock())

    cli_main.import_yaml_campaign()

    report_error.assert_called_once_with("Campaign target preflight failed.")
    replace.assert_not_called()


@pytest.mark.parametrize("cloud", ("aws", "azure"))
def test_import_yaml_requires_selected_cloud_login(monkeypatch, cloud):
    monkeypatch.setattr(cli_main.context, "cloud", cloud)
    monkeypatch.setattr(cli_main.context, "region", "azure" if cloud == "azure" else "eu-west-1")
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": False, "label": cloud, "name": "Not logged in"}),
    )
    report_error = MagicMock()
    monkeypatch.setattr(cli_main, "error", report_error)
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    prompt = MagicMock()
    monkeypatch.setattr(cli_main, "prompt", prompt)

    cli_main.import_yaml_campaign()

    report_error.assert_called_once_with(
        f"Log in to {cloud.upper()} before importing a campaign YAML."
    )
    prompt.assert_not_called()


def test_import_yaml_rejects_provider_mismatch_before_replacing_campaign(tmp_path, monkeypatch):
    path = tmp_path / "azure.yaml"
    path.write_bytes(b"yaml")
    monkeypatch.setattr(cli_main.context, "cloud", "aws")
    monkeypatch.setattr(cli_main.context, "region", "eu-west-1")
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value=str(path)))
    monkeypatch.setattr(
        cli_main,
        "get_cloud_identity",
        MagicMock(return_value={"authenticated": True, "label": "AWS", "name": "Test"}),
    )
    inspect = MagicMock(return_value=SimpleNamespace(valid=False, errors=("provider mismatch",)))
    monkeypatch.setattr(cli_main.campaign_yaml_service, "inspect_bytes", inspect)
    replace = MagicMock()
    monkeypatch.setattr(cli_main, "replace_campaign", replace)
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    monkeypatch.setattr(cli_main, "error", MagicMock())

    cli_main.import_yaml_campaign()

    assert inspect.call_args.kwargs["expected_provider"] == "aws"
    replace.assert_not_called()


def test_campaign_summary_yaml_option_invokes_export(monkeypatch):
    source = _campaign()
    monkeypatch.setattr(cli_main, "campaign", source)
    monkeypatch.setattr(cli_main, "list_all", lambda: source.experiments)
    monkeypatch.setattr(cli_main, "clear_screen", MagicMock())
    monkeypatch.setattr(cli_main, "print_banner", MagicMock())
    monkeypatch.setattr(cli_main, "dashboard", MagicMock())
    monkeypatch.setattr(cli_main, "title", MagicMock())
    monkeypatch.setattr(cli_main, "pause", MagicMock())
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="2"))
    export = MagicMock()
    monkeypatch.setattr(cli_main, "export_campaign_yaml", export)

    cli_main.view_campaign()

    export.assert_called_once_with()


def test_permissions_command_uses_safe_yaml_validation_without_cloud_or_planning(tmp_path, monkeypatch):
    path = tmp_path / "campaign.yaml"
    path.write_bytes(b"campaign")
    campaign = _campaign()
    inspect = MagicMock(return_value=SimpleNamespace(valid=True, campaign=campaign, errors=()))
    monkeypatch.setattr(cli_main.campaign_yaml_service, "inspect_bytes", inspect)
    monkeypatch.setattr(cli_main.permission_reports, "render_json", MagicMock(return_value="{\"provider\": \"aws\"}"))
    monkeypatch.setattr(cli_main, "get_cloud_identity", MagicMock())

    assert cli_main.permission_report_yaml(path, "json") == 0

    inspect.assert_called_once_with(b"campaign", source_name=str(path))
    cli_main.get_cloud_identity.assert_not_called()


def test_permissions_command_writes_requested_output(tmp_path, monkeypatch):
    path = tmp_path / "campaign.yaml"
    output = tmp_path / "permissions.md"
    path.write_bytes(b"campaign")
    monkeypatch.setattr(
        cli_main.campaign_yaml_service,
        "inspect_bytes",
        MagicMock(return_value=SimpleNamespace(valid=True, campaign=_campaign(), errors=())),
    )
    monkeypatch.setattr(cli_main.permission_reports, "render_markdown", MagicMock(return_value="# Permission Report"))

    assert cli_main.permission_report_yaml(path, "markdown", output) == 0
    assert output.read_text() == "# Permission Report\n"


def test_permissions_command_reports_read_and_validation_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_main, "error", MagicMock())
    assert cli_main.permission_report_yaml(tmp_path / "missing.yaml") == 1

    path = tmp_path / "campaign.yaml"
    path.write_bytes(b"campaign")
    monkeypatch.setattr(
        cli_main.campaign_yaml_service,
        "inspect_bytes",
        MagicMock(return_value=SimpleNamespace(valid=False, campaign=None, errors=("invalid",))),
    )
    assert cli_main.permission_report_yaml(path) == 1
    assert cli_main.error.call_args.args[0] == "Campaign YAML validation failed."

    monkeypatch.setattr(
        cli_main.campaign_yaml_service,
        "inspect_bytes",
        MagicMock(return_value=SimpleNamespace(valid=True, campaign=_campaign(), errors=())),
    )
    monkeypatch.setattr(cli_main.permission_reports, "render_terminal", MagicMock(return_value="report"))
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.main.Path.write_text",
        MagicMock(side_effect=OSError("read-only")),
    )
    assert cli_main.permission_report_yaml(path, "terminal", tmp_path / "out.txt") == 1
    assert "Failed to write permission report" in cli_main.error.call_args.args[0]


def test_permissions_cli_command_requires_a_yaml_file(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["chaosforge", "permissions"])

    with pytest.raises(SystemExit) as result:
        cli_main.main()

    assert result.value.code == 2


def test_permissions_cli_command_runs_report_for_supplied_yaml(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["chaosforge", "permissions", "campaign.yaml"])
    report = MagicMock(return_value=0)
    monkeypatch.setattr(cli_main, "permission_report_yaml", report)

    with pytest.raises(SystemExit) as result:
        cli_main.main()

    assert result.value.code == 0
    report.assert_called_once_with("campaign.yaml", "terminal", None)


def test_load_campaign_yaml_option_works_without_saved_json(monkeypatch):
    monkeypatch.setattr(cli_main, "clear_screen", MagicMock())
    monkeypatch.setattr(cli_main, "print_banner", MagicMock())
    monkeypatch.setattr(cli_main, "title", MagicMock())
    monkeypatch.setattr(cli_main, "list_saved_campaigns", MagicMock(return_value=[]))
    monkeypatch.setattr(cli_main, "prompt", MagicMock(return_value="y"))
    load_yaml = MagicMock()
    monkeypatch.setattr(cli_main, "import_yaml_campaign", load_yaml)

    cli_main.load_campaign()

    load_yaml.assert_called_once_with()
