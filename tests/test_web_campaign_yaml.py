import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.engines.chaos_mesh.version_policy import ChaosMeshVersionAssessment
from chaosforge.interfaces.web import app as web_app
from chaosforge.models import Campaign, Experiment


@pytest.fixture
def client(monkeypatch):
    web_app.app.config.update(TESTING=True)
    monkeypatch.setattr(
        web_app,
        "get_current_campaign",
        MagicMock(return_value=Campaign(name="Current", cloud_provider="aws")),
    )
    monkeypatch.setattr(
        web_app,
        "get_cached_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "label": "Account",
            "name": "Test",
            "account_id": "123",
        },
    )
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "label": "Account",
            "name": "Test",
            "account_id": "123",
        },
    )
    return web_app.app.test_client()


def test_cloud_page_puts_upload_before_components_and_shows_cart(client):
    response = client.get("/cloud/aws")
    body = response.get_data(as_text=True)

    assert body.index("top-campaign-cart") < body.index("hero-header")
    assert "Choose an AWS campaign" in body
    assert "Choose Campaign" in body
    assert 'href="/campaign?cloud=aws"' in body
    assert "Current AWS campaign with 0 experiments" in body
    assert "Validate Campaign" not in body
    assert "provider-workbench-top" not in body


def test_campaign_page_offers_yaml_download_without_legacy_save_or_load(client, monkeypatch):
    campaign = Campaign(
        name="Current",
        cloud_provider="aws",
        experiments=[Experiment("id", "lambda", "Name", "file", {})],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)

    response = client.get("/campaign")

    assert b"Download YAML" in response.data
    assert b"Save Campaign" not in response.data
    assert b"Load Campaign" not in response.data
    assert b'href="/campaign/save"' not in response.data
    assert b'href="/campaign/load"' not in response.data


def test_immediate_download_exports_current_campaign_name(client, monkeypatch):
    campaign = Campaign(
        name="Current",
        cloud_provider="aws",
        experiments=[Experiment("id", "lambda", "Name", "file", {})],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"account_id": "123", "name": "engineering"},
    )
    export = MagicMock(return_value=b"yaml")
    monkeypatch.setattr(web_app.yaml_service, "export_bytes", export)

    immediate = client.get("/campaign/export-yaml")

    assert "Current.yaml" in immediate.headers["Content-Disposition"]
    assert export.call_count == 1
    assert export.call_args.kwargs["environment"]["account_id"] == "123"
    assert campaign.report_timezone == "Europe/Berlin"


def test_legacy_web_save_and_load_routes_are_removed(client):
    assert client.get("/campaign/save").status_code == 404
    assert client.get("/campaign/load").status_code == 404


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "Select a .yaml"),
        ({"campaign_yaml": (io.BytesIO(b"x"), "bad.txt")}, ".yaml"),
    ],
)
def test_upload_rejects_missing_or_wrong_extension(client, data, message):
    response = client.post(
        "/cloud/aws/campaign-yaml/review",
        data=data,
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert message.encode() in response.data


def test_invalid_upload_does_not_replace_campaign(client, monkeypatch):
    replace = MagicMock()
    monkeypatch.setattr(web_app, "replace_campaign", replace)
    monkeypatch.setattr(web_app, "create_campaign_draft", MagicMock())

    response = client.post(
        "/cloud/aws/campaign-yaml/review",
        data={"campaign_yaml": (io.BytesIO(b"campaign: {}\n"), "bad.yaml")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    replace.assert_not_called()


def test_valid_upload_authenticates_loads_and_redirects_to_campaign(client, monkeypatch):
    campaign = Campaign(
        name="Uploaded",
        cloud_provider="aws",
        experiments=[Experiment("id", "lambda", "Name", "file", {})],
    )
    review = SimpleNamespace(
        valid=True,
        campaign=campaign,
        errors=(),
        warnings=(),
        experiments=campaign.experiments,
        document={"environment": {"account_id": "123"}},
    )
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", MagicMock(return_value=review))
    replace = MagicMock()
    monkeypatch.setattr(web_app, "replace_campaign", replace)
    draft = Campaign(
        name="Uploaded",
        cloud_provider="aws",
        campaign_id="campaign-new",
        created_at="created",
        updated_at="updated",
    )
    monkeypatch.setattr(web_app, "create_campaign_draft", MagicMock(return_value=draft))
    monkeypatch.setattr(web_app.campaign_preflight, "preflight", MagicMock(return_value=SimpleNamespace(ready=True)))

    response = client.post(
        "/cloud/aws/campaign-yaml/review",
        data={"campaign_yaml": (io.BytesIO(b"valid"), "campaign.yaml")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/campaign?cloud=aws"
    replace.assert_called_once_with(campaign, "aws")
    assert campaign.campaign_id == "campaign-new"
    assert campaign.created_at == "created"
    assert campaign.updated_at == "updated"


def test_campaign_redirects_are_generated_from_the_cloud_allowlist(client, monkeypatch):
    review = SimpleNamespace(valid=True, campaign=Campaign(cloud_provider="aws"), document={})
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "account_id": "account"},
    )
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(web_app.campaign_preflight, "preflight", lambda *_args: SimpleNamespace(ready=True))
    monkeypatch.setattr(web_app, "replace_campaign", MagicMock())
    monkeypatch.setattr(
        web_app,
        "create_campaign_draft",
        MagicMock(return_value=Campaign(campaign_id="campaign-new")),
    )

    response = client.post(
        "/cloud/aws/campaign-yaml/review?cloud=https://attacker.invalid",
        data={"campaign_yaml": (io.BytesIO(b"campaign: test"), "campaign.yaml")},
    )

    assert response.headers["Location"] == "/campaign?cloud=aws"


def test_upload_requires_name_and_rejects_duplicate_draft(client, monkeypatch):
    nameless = SimpleNamespace(valid=True, campaign=SimpleNamespace(name=""), document={})
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", lambda *_args, **_kwargs: nameless)
    monkeypatch.setattr(web_app.campaign_preflight, "preflight", lambda *_args: SimpleNamespace(ready=True))
    response = client.post("/cloud/aws/campaign-yaml/review", data={"campaign_yaml": (io.BytesIO(b"x"), "campaign.yaml")})
    assert response.status_code == 400
    assert b"Campaign name is required" in response.data

    named = SimpleNamespace(valid=True, campaign=Campaign(name="Existing"), document={})
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", lambda *_args, **_kwargs: named)
    monkeypatch.setattr(web_app, "create_campaign_draft", MagicMock(side_effect=ValueError("duplicate")))
    response = client.post("/cloud/aws/campaign-yaml/review", data={"campaign_yaml": (io.BytesIO(b"x"), "campaign.yaml")})
    assert response.status_code == 400
    assert b"duplicate" in response.data


def test_upload_provider_mismatch_is_rendered(client, monkeypatch):
    inspect = MagicMock(
        return_value=SimpleNamespace(valid=False, errors=("provider mismatch",))
    )
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", inspect)

    response = client.post(
        "/cloud/azure/campaign-yaml/review",
        data={"campaign_yaml": (io.BytesIO(b"valid"), "campaign.yaml")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"provider mismatch" in response.data
    assert inspect.call_args.kwargs["expected_provider"] == "azure"


def test_upload_rejects_a_real_different_cloud_campaign(client):
    aws_yaml = b"""campaign:\n  name: AWS\n  continue_on_failure: false\ncloud:\n  provider: aws\nenvironment:\n  account_id: '123'\nexperiments:\n  - service: lambda\n    experiment: lambda-memory\n    variables:\n      lambda_name: demo\n      aws_region: eu-west-1\n      target_memory_size: 256\n      wait_seconds: 30\n"""

    response = client.post(
        "/cloud/azure/campaign-yaml/review",
        data={"campaign_yaml": (io.BytesIO(aws_yaml), "aws.yaml")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"Uploaded campaign targets" in response.data
    assert b"azure&#39; is selected" in response.data


def test_upload_template_and_missing_target_do_not_replace_campaign(client, monkeypatch):
    template = SimpleNamespace(
        valid=True,
        campaign=Campaign(cloud_provider="aws"),
        errors=(),
        document={"template": True},
    )
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", MagicMock(return_value=template))
    monkeypatch.setattr(
        web_app.campaign_preflight,
        "preflight",
        MagicMock(return_value=SimpleNamespace(ready=False, errors=("Campaign YAML is a template.",))),
    )
    replace = MagicMock()
    monkeypatch.setattr(web_app, "replace_campaign", replace)

    response = client.post(
        "/cloud/aws/campaign-yaml/review",
        data={"campaign_yaml": (io.BytesIO(b"template"), "template.yaml")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert b"template" in response.data
    replace.assert_not_called()


@pytest.mark.parametrize("cloud", ("aws", "azure"))
def test_cloud_page_hides_yaml_upload_until_logged_in(client, monkeypatch, cloud):
    monkeypatch.setattr(
        web_app,
        "get_cached_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": False, "label": cloud, "name": "Not logged in"},
    )

    response = client.get(f"/cloud/{cloud}")

    assert response.status_code == 200
    assert b"Log in to" in response.data
    assert b"campaign-yaml-input" in response.data
    assert b"data-yaml-upload-panel hidden" in response.data


@pytest.mark.parametrize("cloud", ("aws", "azure"))
def test_upload_requires_cloud_login_before_reading_file(client, monkeypatch, cloud):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": False, "label": cloud, "name": "Not logged in"},
    )
    inspect = MagicMock()
    monkeypatch.setattr(web_app.yaml_service, "inspect_bytes", inspect)

    response = client.post(
        f"/cloud/{cloud}/campaign-yaml/review",
        data={"campaign_yaml": (io.BytesIO(b"campaign: {}"), "campaign.yaml")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 401
    assert b"before uploading a campaign" in response.data
    inspect.assert_not_called()


def test_export_yaml_response_and_safe_filename(client, monkeypatch):
    campaign = Campaign(
        name="My unsafe / campaign",
        cloud_provider="aws",
        experiments=[Experiment("id", "lambda", "Name", "file", {})],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)
    monkeypatch.setattr(web_app.yaml_service, "export_bytes", lambda *_args, **_kwargs: b"yaml")

    response = client.get("/campaign/export-yaml")

    assert response.status_code == 200
    assert response.data == b"yaml"
    assert response.mimetype == "application/yaml"
    assert "My-unsafe-campaign.yaml" in response.headers["Content-Disposition"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_export_empty_campaign_is_rejected(client):
    assert client.get("/campaign/export-yaml").status_code == 400


def test_cart_count_is_visible_on_cloud_service_and_experiment(client, monkeypatch):
    campaign = Campaign(
        experiments=[
            Experiment("id", "azure_redis", "Redis", "file", {}),
            Experiment("id2", "azure_redis", "Redis 2", "file", {}),
            Experiment("id3", "lambda", "Lambda", "file", {}),
        ]
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *_: None)

    for route in (
        "/cloud/azure",
        "/service/azure_redis",
        "/experiment/azure_redis/azure-redis-flush",
    ):
        response = client.get(route)
        assert response.status_code == 200
        assert b"campaign with 2 experiments" in response.data
        assert b"campaign-cart-count\">2<" in response.data
        assert b'href="/campaign?cloud=azure"' in response.data

    aws = client.get("/cloud/aws")
    assert b"Current AWS campaign with 1 experiments" in aws.data
    assert b"campaign-cart-count\">1<" in aws.data
    assert b'href="/campaign?cloud=aws"' in aws.data

    assert b"campaign-cart" not in client.get("/").data


def test_execute_selected_filters_requested_cloud_and_avoids_empty_execution(client, monkeypatch):
    aws = Experiment("aws", "lambda", "Lambda", "file", {})
    azure = Experiment("azure", "azure_redis", "Redis", "file", {})
    campaign = Campaign(cloud_provider="aws", experiments=[aws, azure])
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda _: [azure])

    response = client.get("/campaign/execute-selected?ids=0&cloud=aws")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/campaign?cloud=aws")


def test_execute_selected_rejects_external_redirect_values(client, monkeypatch):
    campaign = Campaign(cloud_provider="https://attacker.invalid")
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda _: [])

    response = client.get(
        "/campaign/execute-selected?ids=0&cloud=https://attacker.invalid"
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/campaign?cloud=aws")
    assert "attacker.invalid" not in response.headers["Location"]


def test_execute_selected_preserves_the_active_campaign_name(client, monkeypatch):
    campaign = Campaign(
        name="Test",
        cloud_provider="azure",
        campaign_id="campaign-1",
        experiments=[Experiment("reboot", "azure_redis", "Reboot", "file", {})],
    )
    executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda *_args: campaign.experiments)
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)

    token = web_app._permission_review_token("azure", [0])
    web_app._confirm_permission_review_token(token)
    response = client.get(f"/campaign/execute-selected?ids=0&cloud=azure&review={token}")

    assert response.status_code == 302
    submitted = executor.start.call_args.args[0]
    assert submitted.name == "Test"
    assert submitted.campaign_id == "campaign-1"
    assert response.headers["Location"].endswith("/execution?cloud=azure")


def test_execute_rejects_concurrent_same_cloud_campaign(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[Experiment("id", "lambda", "Lambda", "file", {})],
    )
    executor = SimpleNamespace(
        start=MagicMock(
            side_effect=web_app.ExecutionAlreadyRunning("aws", "active-run")
        )
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)
    token = web_app._permission_review_token("aws", None)
    web_app._confirm_permission_review_token(token)

    response = client.get(f"/campaign/execute?cloud=aws&review={token}")

    assert response.status_code == 409
    assert response.data == b"A AWS campaign is already running."
    executor.start.assert_called_once()


def test_execute_selected_rejects_concurrent_same_cloud_campaign(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="azure",
        experiments=[Experiment("id", "azure_vm", "VM", "file", {})],
    )
    executor = SimpleNamespace(
        start=MagicMock(
            side_effect=web_app.ExecutionAlreadyRunning("azure", "active-run")
        )
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(
        web_app, "get_selected_experiments", lambda *_args: campaign.experiments
    )
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)
    token = web_app._permission_review_token("azure", [0])
    web_app._confirm_permission_review_token(token)

    response = client.get(
        f"/campaign/execute-selected?ids=0&cloud=azure&review={token}"
    )

    assert response.status_code == 409
    assert response.data == b"A AZURE campaign is already running."


def test_campaign_import_drop_zone_uses_non_regex_yaml_extension_checks():
    script = (
        Path(web_app.app.static_folder) / "campaign-import.js"
    ).read_text(encoding="utf-8")

    assert 'filename.endsWith(".yaml")' in script
    assert 'filename.endsWith(".yml")' in script
    assert "/\\.ya?ml$/i" not in script


def test_execute_selected_submits_checkbox_indices_as_numbers():
    script = (Path(web_app.app.static_folder) / "campaign.js").read_text(encoding="utf-8")

    assert "cb => Number(cb.value)" in script


def test_campaign_download_name_sanitizer_does_not_use_regex():
    assert web_app._safe_download_name("My unsafe / campaign") == "My-unsafe-campaign"
    assert web_app._safe_download_name("...///...") == ""


def test_execute_routes_scope_campaign_by_cloud(client, monkeypatch):
    aws = Experiment("aws", "lambda", "Lambda", "file", {})
    azure = Experiment("azure", "azure_redis", "Redis", "file", {})
    campaign = Campaign(name="Mixed", cloud_provider="aws", experiments=[aws, azure])
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)
    executors = {
        "aws": SimpleNamespace(start=MagicMock(return_value="aws-run")),
        "azure": SimpleNamespace(start=MagicMock(return_value="azure-run")),
    }
    monkeypatch.setattr(web_app, "get_executor", lambda cloud: executors[cloud])

    token = web_app._permission_review_token("azure", None)
    web_app._confirm_permission_review_token(token)
    response = client.get(f"/campaign/execute?cloud=azure&review={token}")
    assert response.status_code == 302
    submitted = executors["azure"].start.call_args.args[0]
    assert submitted.cloud_provider == "azure"
    assert submitted.experiments == [azure]

    token = web_app._permission_review_token("aws", None)
    web_app._confirm_permission_review_token(token)
    response = client.get(f"/campaign/execute?cloud=aws&review={token}")
    assert response.status_code == 302
    assert executors["aws"].start.call_args.args[0].experiments == [aws]

    monkeypatch.setattr(web_app, "get_current_campaign", lambda: Campaign(cloud_provider="aws"))
    assert client.get("/campaign/execute?cloud=azure").headers["Location"].endswith(
        "/campaign?cloud=azure"
    )


def test_execute_empty_selected_cloud_uses_only_constant_internal_routes(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: Campaign(cloud_provider="aws"))
    azure_executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_executor", lambda cloud: azure_executor)

    azure = client.get("/campaign/execute?cloud=azure")
    external = client.get("/campaign/execute?cloud=https://attacker.invalid")

    assert azure.headers["Location"].endswith("/campaign?cloud=azure")
    assert external.headers["Location"] == "/campaign?cloud=aws"
    assert "attacker.invalid" not in external.headers["Location"]


def test_campaign_returns_to_selected_provider(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="azure",
        experiments=[Experiment("id", "aks", "Pod Kill", "file", {})],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)

    response = client.get("/campaign")

    assert response.status_code == 200
    assert b"Back to AZURE Components" in response.data
    assert b'href="/cloud/azure"' in response.data
    assert response.data.count(b"Back to AZURE Components") == 1


def test_campaign_page_filters_experiments_by_requested_cloud(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[
            Experiment("aws-index", "lambda", "AWS Experiment", "file", {}),
            Experiment("azure-index", "aks", "Azure Experiment", "file", {}),
        ],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: campaign)

    aws = client.get("/campaign?cloud=aws")
    azure = client.get("/campaign?cloud=azure")

    assert b"AWS Experiment" in aws.data
    assert b"Azure Experiment" not in aws.data
    assert b"Azure Experiment" in azure.data
    assert b"AWS Experiment" not in azure.data
    assert b'value="1"' in azure.data


def test_provider_scoped_execution_filters_selected_entries(client, monkeypatch):
    current = Campaign(
        name="Mixed",
        cloud_provider="aws",
        experiments=[
            Experiment("aws", "lambda", "AWS", "file", {}),
            Experiment("azure", "aks", "Azure", "file", {}),
        ],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: current)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda _: current.experiments)
    azure_executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_executor", lambda cloud: azure_executor)

    token = web_app._permission_review_token("azure", [0, 1])
    web_app._confirm_permission_review_token(token)
    response = client.get(f"/campaign/execute-selected?ids=0,1&cloud=azure&review={token}")

    assert response.status_code == 302
    submitted = azure_executor.start.call_args.args[0]
    assert [item.name for item in submitted.experiments] == ["Azure"]
    assert submitted.cloud_provider == "azure"


def test_selected_execution_can_explicitly_continue_after_failures(client, monkeypatch):
    current = Campaign(
        cloud_provider="azure",
        experiments=[Experiment("first", "azure_vmss", "First", "file", {})],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda: current)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda _: current.experiments)
    executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)

    token = web_app._permission_review_token("azure", [0])
    web_app._confirm_permission_review_token(token)
    response = client.get(
        f"/campaign/execute-selected?ids=0&cloud=azure&review={token}&continue_on_failure=true"
    )

    assert response.status_code == 302
    assert executor.start.call_args.args[0].continue_on_failure is True


def test_permission_report_is_read_only_and_execution_requires_its_review_token(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[Experiment("id", "lambda", "Lambda", "file", {})],
    )
    executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)
    generate = MagicMock(return_value={"provider": "aws", "policy": {}, "warnings": []})
    monkeypatch.setattr(web_app.permission_reports, "generate", generate)

    blocked = client.get("/campaign/execute?cloud=aws")
    assert blocked.headers["Location"] == "/campaign?cloud=aws"
    executor.start.assert_not_called()

    review = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": None})
    assert review.status_code == 200
    assert review.json["report"]["provider"] == "aws"
    generate.assert_called_once()
    executor.start.assert_not_called()

    token = review.json["review_token"]
    unconfirmed = client.get(f"/campaign/execute?cloud=aws&review={token}")
    assert unconfirmed.headers["Location"] == "/campaign?cloud=aws"
    # Fetch a new report because an attempted execution consumes the old token.
    review = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": None})
    token = review.json["review_token"]
    assert client.post("/api/campaign/permissions/confirm", json={"review_token": token}).json == {"confirmed": True}
    started = client.get(f"/campaign/execute?cloud=aws&review={token}")
    assert started.headers["Location"] == "/execution?cloud=aws"
    executor.start.assert_called_once()


@pytest.mark.parametrize(
    ("cloud", "experiment", "report_section"),
    [
        (
            "aws",
            Experiment("lambda-timeout", "lambda", "Lambda timeout", "file", {}),
            ("policy", "Statement"),
        ),
        (
            "azure",
            Experiment(
                "azure-redis-flush",
                "azure_redis",
                "Redis flush",
                "file",
                {"resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/Redis/cache"},
                engine="Azure SDK",
            ),
            ("rbac", "runtime"),
        ),
    ],
)
def test_permission_review_api_returns_visible_requirements_for_each_cloud(
    client, monkeypatch, cloud, experiment, report_section
):
    campaign = Campaign(cloud_provider=cloud, experiments=[experiment])
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)

    response = client.post("/api/campaign/permissions", json={"cloud": cloud, "ids": None})

    assert response.status_code == 200
    assert response.json["report"]["provider"] == cloud
    outer, inner = report_section
    assert response.json["report"][outer][inner]


def test_selected_permission_review_token_is_scoped_and_single_use(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[Experiment("id", "lambda", "Lambda", "file", {})],
    )
    executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda *_args: campaign.experiments)
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)

    review = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": [0]})
    token = review.json["review_token"]
    mismatch = client.get(f"/campaign/execute-selected?ids=1&cloud=aws&review={token}")
    assert mismatch.headers["Location"] == "/campaign?cloud=aws"
    assert executor.start.call_count == 0

    review = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": [0]})
    token = review.json["review_token"]
    client.post("/api/campaign/permissions/confirm", json={"review_token": token})
    client.get(f"/campaign/execute-selected?ids=0&cloud=aws&review={token}")
    client.get(f"/campaign/execute-selected?ids=0&cloud=aws&review={token}")
    assert executor.start.call_count == 1


def test_permission_review_exposes_only_the_selected_target_identity(client, monkeypatch):
    experiment = Experiment(
        "s3-versioning",
        "s3",
        "S3 Versioning",
        "file",
        {"bucket_name": "chaosforge-e2e", "access_key": "must-not-be-exposed"},
    )
    campaign = Campaign(cloud_provider="aws", experiments=[experiment])
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda *_args: campaign.experiments)

    response = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": [0]})

    assert response.status_code == 200
    assert response.json["experiments"][0]["target"] == {
        "variable": "bucket_name", "value": "chaosforge-e2e"
    }
    assert "access_key" not in str(response.json)


def test_permission_review_api_rejects_invalid_selection_empty_campaign_and_expired_token(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: Campaign(cloud_provider="aws"))
    assert client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": ["bad"]}).status_code == 400
    assert client.post("/api/campaign/permissions", json={"cloud": "invalid", "ids": None}).status_code == 400
    assert client.post("/api/campaign/permissions", data="not-json").status_code == 400
    assert client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": None}).status_code == 400
    assert client.post("/api/campaign/permissions/confirm", json={"review_token": "missing"}).status_code == 400

    token = web_app._permission_review_token("aws", None)
    web_app.permission_review_tokens[token]["created_at"] -= web_app.PERMISSION_REVIEW_TOKEN_TTL_SECONDS
    assert client.post("/api/campaign/permissions/confirm", json={"review_token": token}).status_code == 400


def test_permission_review_requires_irreversible_acknowledgement(monkeypatch):
    monkeypatch.setattr(web_app, "permission_review_tokens", {})
    token = web_app._permission_review_token(
        "azure", [0], requires_irreversible_acknowledgement=True
    )

    assert web_app._confirm_permission_review_token(token) is False
    assert web_app._confirm_permission_review_token(
        token, irreversible_acknowledged=True
    ) is True


def test_permission_review_prunes_expired_tokens_and_rejects_execution_edge_cases(client, monkeypatch):
    monkeypatch.setattr(web_app, "permission_review_tokens", {})
    try:
        stale = web_app._permission_review_token("aws", None)
        web_app.permission_review_tokens[stale]["created_at"] -= web_app.PERMISSION_REVIEW_TOKEN_TTL_SECONDS
        web_app._permission_review_token("aws", None)
        assert stale not in web_app.permission_review_tokens
        campaign = Campaign(cloud_provider="aws", experiments=[])
        monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
        monkeypatch.setattr(web_app, "get_selected_experiments", lambda *_args: [])

        review = client.post("/api/campaign/permissions", json={"cloud": "aws", "ids": None})
        assert review.status_code == 400
        assert client.get("/campaign/execute-selected?ids=bad&cloud=aws").headers["Location"] == "/campaign?cloud=aws"

        token = web_app._permission_review_token("aws", [0])
        web_app._confirm_permission_review_token(token)
        assert client.get(f"/campaign/execute-selected?ids=0&cloud=aws&review={token}").headers["Location"] == "/campaign?cloud=aws"

        token = web_app._permission_review_token("aws", None)
        web_app._confirm_permission_review_token(token)
        assert client.get(f"/campaign/execute?cloud=aws&review={token}").headers["Location"] == "/campaign?cloud=aws"
    finally:
        web_app.permission_review_tokens.clear()


def test_permission_review_empty_azure_campaign_returns_azure_route(client, monkeypatch):
    campaign = Campaign(cloud_provider="azure", experiments=[])
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_selected_experiments", lambda *_args: [])

    selected_token = web_app._permission_review_token("azure", [0])
    web_app._confirm_permission_review_token(selected_token)
    assert client.get(f"/campaign/execute-selected?ids=0&cloud=azure&review={selected_token}").headers["Location"] == "/campaign?cloud=azure"

    all_token = web_app._permission_review_token("azure", None)
    web_app._confirm_permission_review_token(all_token)
    assert client.get(f"/campaign/execute?cloud=azure&review={all_token}").headers["Location"] == "/campaign?cloud=azure"


def test_web_chaos_mesh_review_requires_and_applies_version_choice(client, monkeypatch):
    campaign = Campaign(
        name="Mesh",
        cloud_provider="aws",
        experiments=[Experiment(
            "chaos-mesh-pod-kill", "chaos_mesh", "Pod Kill", "file",
            {"aws_region": "eu-central-1", "eks_cluster": "cluster"},
            engine="Chaos Mesh",
        )],
    )
    assessment = ChaosMeshVersionAssessment(
        "eu-central-1:cluster", "cluster", "eu-central-1", "older", "2.8.4"
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "assess_campaign", lambda _: [assessment])
    saved = MagicMock()
    monkeypatch.setattr(web_app, "save_chaos_mesh_version_decisions", saved)
    executor = SimpleNamespace(start=MagicMock(return_value="run-1"))
    monkeypatch.setattr(web_app, "get_executor", lambda _: executor)

    review = client.post(
        "/api/campaign/permissions", json={"cloud": "aws", "ids": None}
    ).get_json()
    assert review["chaos_mesh_versions"][0]["requires_decision"] is True
    token = review["review_token"]

    missing = client.post(
        "/api/campaign/permissions/confirm",
        json={"review_token": token, "chaos_mesh_decisions": {}},
    )
    assert missing.status_code == 400

    review = client.post(
        "/api/campaign/permissions", json={"cloud": "aws", "ids": None}
    ).get_json()
    token = review["review_token"]
    confirmed = client.post(
        "/api/campaign/permissions/confirm",
        json={
            "review_token": token,
            "chaos_mesh_decisions": {"eu-central-1:cluster": "continue"},
        },
    )
    assert confirmed.status_code == 200
    saved.assert_called_once()

    response = client.get(f"/campaign/execute?cloud=aws&review={token}")
    assert response.status_code == 302
    accepted = executor.start.call_args.args[0]
    assert accepted.experiments[0].chaos_mesh_version_action == "continue"


def test_web_chaos_mesh_review_reuses_saved_decision_and_warns_for_newer(client, monkeypatch):
    older = ChaosMeshVersionAssessment(
        "region:cluster", "cluster", "region", "older", "2.8.4"
    )
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[Experiment(
            "mesh", "chaos_mesh", "Mesh", "file",
            {"aws_region": "region", "eks_cluster": "cluster"}, engine="Chaos Mesh",
        )],
        chaos_mesh_version_decisions={
            "region:cluster": {
                "action": "continue",
                "installed_version": "2.8.4",
                "target_version": "2.8.7",
            }
        },
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "assess_campaign", lambda _: [older])

    body = client.post(
        "/api/campaign/permissions", json={"cloud": "aws", "ids": None}
    ).get_json()
    assert body["chaos_mesh_versions"][0]["requires_decision"] is False
    assert client.post(
        "/api/campaign/permissions/confirm",
        json={"review_token": body["review_token"], "chaos_mesh_decisions": {}},
    ).status_code == 200

    newer = ChaosMeshVersionAssessment(
        "region:cluster", "cluster", "region", "newer", "2.8.8"
    )
    monkeypatch.setattr(web_app, "assess_campaign", lambda _: [newer])
    body = client.post(
        "/api/campaign/permissions", json={"cloud": "aws", "ids": None}
    ).get_json()
    assert body["chaos_mesh_versions"][0]["state"] == "newer"
    assert body["chaos_mesh_versions"][0]["requires_decision"] is False


def test_web_chaos_mesh_review_blocks_incompatible_version(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[Experiment(
            "mesh", "chaos_mesh", "Mesh", "file",
            {"aws_region": "region", "eks_cluster": "cluster"}, engine="Chaos Mesh",
        )],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(
        web_app,
        "assess_campaign",
        lambda _: [ChaosMeshVersionAssessment(
            "region:cluster", "cluster", "region", "incompatible", "2.9.0",
            message="unsupported version",
        )],
    )

    response = client.post(
        "/api/campaign/permissions", json={"cloud": "aws", "ids": None}
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "unsupported version"
