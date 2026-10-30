from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.application.campaigns.factory import create_experiment
from chaosforge.application.discovery import discover_services
from chaosforge.application.experiment_presentation import present_experiment
from chaosforge.catalog import ExperimentCatalog
from chaosforge.interfaces.web import app as web_app
from chaosforge.interfaces.web.catalog import service_cards
from chaosforge.interfaces.web.forms import normalize_values
from chaosforge.interfaces.web.runner import WebExperimentRunner
from chaosforge.models import Campaign, Experiment


@pytest.fixture
def client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


@pytest.fixture(autouse=True)
def opened_campaign(monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_current_campaign",
        lambda cloud=None: Campaign(name="Test campaign", cloud_provider=cloud or "aws", campaign_id="campaign-test"),
    )


def test_landing_page_requires_cloud_selection(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Choose Your Cloud" in response.data
    assert b"Amazon Web Services" in response.data
    assert b"Microsoft Azure" in response.data
    assert b"AWS Services" not in response.data
    assert b'aria-label="Settings"' in response.data
    assert b"landing-mark-intro" in response.data
    assert b"chaosforge-resilience-forge.svg" in response.data
    assert b'rel="icon" type="image/svg+xml"' in response.data


def test_provider_page_does_not_replay_landing_mark_animation(client):
    response = client.get("/cloud/aws")

    assert response.status_code == 200
    assert b"landing-mark-intro" not in response.data


def test_provider_page_requires_campaign_selection_when_no_draft_is_open(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: Campaign(cloud_provider="aws"))
    monkeypatch.setattr(web_app, "list_campaign_drafts", lambda _: [])

    response = client.get("/cloud/aws")

    assert b"Choose an AWS campaign" in response.data
    assert b"Choose Campaign" in response.data
    assert b"View experiments" not in response.data


def test_web_utility_navigation_uses_compact_icons(client):
    response = client.get("/cloud/aws")

    assert response.status_code == 200
    assert b"utility-timezone" in response.data
    assert b"bi-cart3" in response.data
    assert b"bi-gear-fill" in response.data
    assert b">Campaign<" not in response.data
    assert b"UTC+" in response.data
    assert b'title="' in response.data
    assert b"utility-timezone-name" in response.data
    assert b'role="tooltip"' not in response.data


def test_internal_web_pages_use_shared_utility_navigation(client):
    response = client.get("/service/rds")

    assert response.status_code == 200
    assert b"utility-timezone" in response.data
    assert b"bi-cart3" in response.data
    assert b"bi-gear-fill" in response.data
    assert b'icons/chaosforge-resilience-forge.svg' in response.data


def test_cloud_component_cards_keep_provider_specific_hover_identity(client):
    aws = client.get("/cloud/aws")
    azure = client.get("/cloud/azure")
    stylesheet = (Path(web_app.app.static_folder) / "style.css").read_text(encoding="utf-8")

    assert aws.status_code == 200
    assert azure.status_code == 200
    assert b"service-card aws-service-card" in aws.data
    assert b"service-card azure-service-card" in azure.data
    assert ".aws-service-card::after" in stylesheet
    assert "rgba(180, 83, 9, .7)" in stylesheet
    assert ".azure-service-card::after" in stylesheet
    assert "rgba(3, 105, 161, .72)" in stylesheet
    assert ".azure-service-card .service-icon" in stylesheet
    assert "background: linear-gradient(145deg, #f0f9ff, #ccecff);" in stylesheet
    assert "filter: invert(17%)" in stylesheet
    assert b"service-icon-azure_vm" in azure.data
    assert ".azure-service-card .service-icon-azure_redis" in stylesheet
    assert ".azure-service-card .service-icon-azure_functions" in stylesheet


def test_experiment_form_closes_before_runtime_scripts(client):
    response = client.get("/experiment/lambda/lambda-memory")
    body = response.get_data(as_text=True)

    assert body.index("</form>") < body.index("<script>")
    assert 'for="aws_region"' in body
    assert "Add Experiment" in body
    assert "Update Campaign Experiment" not in body

    invalid = client.post("/experiment/lambda/lambda-memory", data={})
    assert invalid.status_code == 400
    assert 'role="alert"' in invalid.get_data(as_text=True)


def test_campaign_page_has_accessible_responsive_selection_controls(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    response = client.get("/campaign?cloud=aws")
    body = response.get_data(as_text=True)

    assert "table-responsive" in body or "Campaign is empty." in body
    if "select-all" in body:
        assert 'aria-label="Select all campaign experiments"' in body
        assert 'role="status"' in body


def test_campaign_and_execution_refresh_the_selected_cloud_identity(client, monkeypatch):
    refresh = MagicMock(
        return_value={"authenticated": True, "label": "Azure subscription", "name": "Engineering"}
    )
    monkeypatch.setattr(web_app, "get_cloud_identity", refresh)
    campaign = web_app.get_current_campaign()
    campaign.cloud_provider = "azure"

    campaign_response = client.get("/campaign?cloud=azure")
    execution_response = client.get("/execution?cloud=azure")

    assert campaign_response.status_code == 200
    assert execution_response.status_code == 200
    assert b"Engineering" in campaign_response.data
    assert b"Engineering" in execution_response.data
    assert refresh.call_args_list[-2:] == [
        (("azure",), {"refresh": True}),
        (("azure",), {"refresh": True}),
    ]


def test_unauthenticated_campaign_cart_redirects_with_a_login_notice(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": False})

    response = client.get("/campaign?cloud=aws", follow_redirects=True)

    assert response.status_code == 200
    assert b"Log in to Amazon Web Services before viewing campaigns." in response.data


def test_web_styles_include_reduced_motion_and_focus_contracts():
    stylesheet = (Path(web_app.app.static_folder) / "style.css").read_text(encoding="utf-8")

    assert "prefers-reduced-motion" in stylesheet
    assert ":focus-visible" in stylesheet
    assert ".action-toolbar" in stylesheet
    assert ".table-responsive" in stylesheet
    assert "--surface-foreground" in stylesheet
    assert "--surface-card" in stylesheet
    assert "backdrop-filter: blur(24px)" in stylesheet
    assert "tbody tr:hover" in stylesheet
    assert ".utility-icon:hover" in stylesheet
    assert "scale(.98)" in stylesheet
    assert ".cloud-card::after" in stylesheet
    assert ".service-card::after" in stylesheet
    assert "rgba(67, 56, 202, .72)" in stylesheet
    assert ".cloud-card-aws::after" in stylesheet
    assert ".cloud-card-azure::after" in stylesheet
    assert ".dashboard-section" in stylesheet
    assert "rgba(49, 46, 129, .58)" in stylesheet
    assert "rgba(24, 35, 70, .72)" in stylesheet
    assert "backdrop-filter:blur(18px) saturate(1.16)" in stylesheet


def test_web_pages_include_accessible_resilience_signal_field(client):
    for route in ("/", "/cloud/aws", "/service/rds", "/settings"):
        response = client.get(route)

        assert response.status_code == 200
        assert b'id="resilience-signal-field"' in response.data
        assert b'aria-hidden="true"' in response.data
        assert b"resilience-signal-field.js" in response.data


def test_resilience_signal_field_respects_motion_performance_and_page_intensity():
    script = (Path(web_app.app.static_folder) / "resilience-signal-field.js").read_text(
        encoding="utf-8"
    )
    stylesheet = (Path(web_app.app.static_folder) / "style.css").read_text(
        encoding="utf-8"
    )

    assert "prefers-reduced-motion: reduce" in script
    assert "visibilitychange" in script
    assert 'pathname === "/"' in script
    assert 'pathname === "/execution"' in script
    assert "window.innerWidth < 720" in script
    assert "requestAnimationFrame" in script
    assert "devicePixelRatio" in script
    assert "buildTopology" in script
    assert "architectureBlueprints" in script
    assert "addArchitectureCluster" in script
    assert "clusterCount" in script
    assert "height * 0.88" in script
    assert "largeTopologyPage" in script
    assert "0.38" in script
    assert "preloadIcons" in script
    assert "iconSources" in script
    assert "startFault" in script
    assert 'node.health = "recovering"' in script
    assert "packets" in script
    assert "curvePoint" in script
    assert "bezierCurveTo" in script
    assert "failover" in script
    assert "setLineDash" in script
    assert 'signal: "healthy"' in script
    assert '"degraded"' in script
    assert '"failed"' in script
    assert "251,191,36" in script
    assert "248,113,113" in script
    assert 'currentLink.signal === "failed" ? 3' in script
    assert "glowRadius = failed ? 12" in script
    assert "createRadialGradient" in script
    assert "nebula.png" not in stylesheet
    assert "ambient-credit" not in stylesheet
    assert ".resilience-signal-field" in stylesheet
    assert "pointer-events: none" in stylesheet
    assert "opacity: .58" in stylesheet
    assert "2500ms" in stylesheet
    assert "landing-mark-arrival" in stylesheet
    assert "landing-mark-recovery-pulse" in stylesheet
    assert ".landing-mark-intro::after" in stylesheet
    mark = (Path(web_app.app.static_folder) / "icons" / "chaosforge-resilience-forge.svg").read_text(encoding="utf-8")
    assert "viewBox=\"0 0 128 128\"" in mark
    assert "protected anvil with a controlled resilience signal" in mark
    assert "linearGradient id=\"shield\"" in mark
    assert "linearGradient id=\"anvil\"" in mark
    assert "linearGradient id=\"inlay\"" in mark
    assert "M26 58h28" in mark
    assert "hero-lightning-strike" not in stylesheet
    assert 'stop-color="#38bdf8"' in mark
    assert "2500ms cubic-bezier(.2, .75, .25, 1)" in stylesheet
    assert "translateY(16vh) scale(8)" in stylesheet
    assert "rotate(-1.2deg)" in stylesheet
    assert "scale(1.55)" in stylesheet
    assert ".landing-mark-intro" in stylesheet
    assert "padding-top: 12px" in stylesheet
    assert "utility-timezone-name" in stylesheet


def test_execution_console_supports_experiment_result_focus():
    script = (Path(web_app.app.static_folder) / "execution.js").read_text(encoding="utf-8")

    assert "chaosforgeFocus" in script
    assert "scrollTop" in script


def test_execution_script_handles_failed_polls_and_accessible_progress_contract():
    script = (Path(web_app.app.static_folder) / "execution.js").read_text(encoding="utf-8")
    template = (Path(web_app.app.template_folder) / "execution.html").read_text(encoding="utf-8")

    assert "response.ok" in script
    assert "setTimeout(updateConsole, 1000)" in script
    assert "textContent" in script
    assert 'role="progressbar"' in template
    assert 'aria-valuenow="0"' in template


def test_web_timezone_settings_persist_selection(client, monkeypatch):
    save_timezone = MagicMock()
    monkeypatch.setattr(web_app, "set_timezone_id", save_timezone)
    monkeypatch.setattr(web_app, "get_timezone_id", lambda: "Europe/Berlin")

    response = client.get("/settings?cloud=aws")
    assert response.status_code == 200
    assert b"Report Timezone" in response.data
    assert b"Asia/Shanghai" in response.data

    response = client.post("/settings?cloud=aws", data={"timezone": "Asia/Shanghai"})
    assert response.status_code == 200
    save_timezone.assert_called_once_with("Asia/Shanghai")
    assert b"Timezone updated" in response.data
    assert b'href="/cloud/aws"' in response.data


def test_web_timezone_settings_reject_invalid_selection(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_timezone_id", lambda: "Europe/Berlin")
    monkeypatch.setattr(web_app, "set_timezone_id", MagicMock(side_effect=ValueError("Select a supported timezone.")))

    response = client.post("/settings", data={"timezone": "Mars/Olympus"})

    assert response.status_code == 400
    assert b"Select a supported timezone" in response.data


def test_cloud_pages_filter_components_and_include_capabilities(client):
    aws = client.get("/cloud/aws")
    azure = client.get("/cloud/azure")

    assert b"Amazon EKS" in aws.data
    assert b"AWS Fault Injection Service" in aws.data
    assert b"Chaos Mesh for Amazon EKS" not in aws.data
    assert b"Azure Cache for Redis" not in aws.data
    assert b"Azure Kubernetes Service" in azure.data
    assert b"Azure Cache for Redis" in azure.data
    assert b"AWS Lambda" not in azure.data


def test_cloud_page_displays_detected_identity_next_to_campaign_cart(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cached_cloud_identity",
        lambda _: {"authenticated": True, "label": "AWS account", "name": "engineering"},
    )

    response = client.get("/cloud/aws")

    assert b"AWS account" in response.data
    assert b"engineering" in response.data
    assert b"bi-shield-check" in response.data


def test_cloud_page_identifies_missing_login(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cached_cloud_identity",
        lambda _: {"authenticated": False, "label": "Azure", "name": "Not logged in"},
    )

    response = client.get("/cloud/azure")

    assert b"Not logged in" in response.data
    assert b"bi-shield-exclamation" in response.data


def test_cloud_identity_api_refreshes_selected_provider(client, monkeypatch):
    identity = {"authenticated": False, "label": "AWS", "name": "Not logged in"}
    refresh = MagicMock(return_value=identity)
    monkeypatch.setattr(web_app, "get_cloud_identity", refresh)

    response = client.get("/api/cloud-identity/aws")

    assert response.get_json() == identity
    refresh.assert_called_once_with("aws")


def test_cloud_identity_api_rejects_unknown_provider(client):
    response = client.get("/api/cloud-identity/gcp")

    assert response.status_code == 404


def test_web_identity_poll_uses_the_twenty_second_identity_cache():
    script = (
        Path(web_app.app.static_folder) / "cloud-identity.js"
    ).read_text(encoding="utf-8")

    assert "window.setInterval(refreshIdentity, 20000)" in script
    assert 'status === "unknown" && authenticated' in script
    assert "let authenticated" in script
    assert "window.sessionStorage" in script
    assert "chaosforge-cloud-authenticated" in script


def test_utility_navigation_loads_identity_refresh_on_component_and_experiment_pages():
    navigation = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/templates/_utility_nav.html").read_text()
    landing_page = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/templates/index.html").read_text()

    assert 'defer src="{{ url_for(\'static\', filename=\'cloud-identity.js\') }}"' in navigation
    assert "cloud-identity.js" not in landing_page


def test_azure_cards_use_packaged_open_source_icons():
    cards = {card["id"]: card for card in service_cards("azure")}

    assert cards["aks"]["icon"] == "Fluent-Cube.svg"
    assert cards["azure_redis"]["icon"] == "Fluent-Flash.svg"


def test_azure_service_pages_show_every_cli_catalog_experiment(client):
    catalog = ExperimentCatalog()

    for service in ("aks", "azure_redis"):
        response = client.get(f"/service/{service}")
        assert response.status_code == 200
        for experiment in catalog.load_service(service)["experiments"]:
            assert experiment["name"].encode() in response.data


def test_standalone_fis_page_hides_internal_component_wrapper(client):
    response = client.get("/service/fis")

    assert response.status_code == 200
    assert b"Create and Start FIS Experiment" not in response.data
    assert b"Start FIS Experiment Template" in response.data
    assert b"Delete FIS Template" in response.data
    assert b"List FIS Templates" not in response.data


def test_fis_management_form_renders_a_dynamic_template_selector(client):
    response = client.get("/experiment/fis/fis-start-template")

    assert response.status_code == 200
    assert b'data-fis-template-select' in response.data
    assert b'id="experiment_template_id"' in response.data


def test_permission_review_request_is_explicitly_same_origin():
    script = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/campaign.js").read_text()

    assert 'fetch("/api/campaign/permissions", {' in script
    assert 'method: "POST"' in script
    assert 'credentials: "same-origin"' in script
    assert "permissionsUrl" not in script
    assert "renderAwsCards(body.report)" in script


def test_permission_review_explains_aws_and_azure_responsibilities():
    script = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/campaign.js").read_text()

    assert "Apply the complete policy below to the AWS identity" in script
    assert "AZURE REQUIRED PERMISSIONS" in script
    assert "Run each command with the object ID" in script
    assert "Choose ONE" in script
    assert "CHAOS STUDIO IDENTITY" in script
    assert "BOOTSTRAP / SETUP IDENTITY" in script
    assert "CHAOSFORGE RUNTIME IDENTITY" in script
    assert "administrator or automation identity ($BOOTSTRAP_PRINCIPAL_ID)" in script
    assert "AZURE RUNTIME PERMISSIONS" in script
    assert "runtime.length && !chaosStudio.length && !bootstrap.length" in script


def test_permission_review_hides_bootstrap_permissions_by_default():
    script = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/campaign.js").read_text()
    template = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/templates/campaign.html").read_text()

    assert "formatBootstrapPermissions" in script
    assert "bootstrapPermissions.parentElement.hidden = !bootstrap" in script
    assert "Optional: first-time Chaos Studio identity setup permissions" in template


def test_permission_review_renders_structured_identity_cards_with_experiment_provenance():
    script = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/campaign.js").read_text()
    template = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/templates/campaign.html").read_text()
    stylesheet = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/style.css").read_text()

    assert "renderIdentityCards" in script
    assert "permission-experiment-badge" in script
    assert "Copy command" in script
    assert "Copy IAM policy" in script
    assert "Copy FIS trust policy" in script
    assert 'id="permission-review-cards"' in template
    assert ".permission-identity-card" in stylesheet


def test_campaign_table_displays_the_owning_component_for_fis_experiments(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[Experiment(
            "fis-create-experiment", "fis", "Invocation Delay (AWS FIS)", "", {},
            engine="AWS FIS", target_service="lambda",
        )],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "execution_sessions", lambda _: [])

    response = client.get("/campaign?cloud=aws")

    assert b"Amazon Lambda" in response.data
    assert b"<td>fis</td>" not in response.data


def test_campaign_table_displays_the_component_name_for_native_experiments(client, monkeypatch):
    campaign = Campaign(
        cloud_provider="aws",
        experiments=[Experiment(
            "elasticache-reboot", "elasticache", "Reboot Cache Cluster", "", {},
        )],
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: campaign)
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True})
    monkeypatch.setattr(web_app, "execution_sessions", lambda _: [])

    response = client.get("/campaign?cloud=aws")

    assert b"Amazon ElastiCache" in response.data
    assert b"<td>elasticache</td>" not in response.data


def test_permission_review_modal_has_explicit_readable_colors():
    stylesheet = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/style.css").read_text()

    assert "#permission-review-modal .modal-content" in stylesheet
    assert "color: var(--text-primary);" in stylesheet
    assert "#permission-review-report" in stylesheet
    assert "background: #020617;" in stylesheet
    assert "color: #e2e8f0;" in stylesheet


def test_engine_and_reversibility_labels_share_pill_treatment():
    stylesheet = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/style.css").read_text()

    assert ".engine-label {" in stylesheet
    assert "border-radius: 999px;" in stylesheet
    assert ".reversibility-label-reversible" in stylesheet
    assert "color: #67e8f9;" in stylesheet
    assert ".engine-label-custom" in stylesheet
    assert "color: #86efac;" in stylesheet
    assert ".campaign-table-wrap .reversibility-label-reversible" in stylesheet
    assert "background: #cffafe;" in stylesheet
    assert ".campaign-table-wrap .reversibility-label-irreversible" in stylesheet
    assert "background: #fee2e2;" in stylesheet


def test_experiment_page_renders_safety_badge_only_for_known_classifications():
    template = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/templates/experiment.html").read_text()

    assert '{% if experiment.reversibility in ("reversible", "irreversible") %}' in template


@pytest.mark.parametrize(
    "experiment_id",
    [
        "azure-redis-reboot",
        "azure-redis-flush",
        "azure-redis-access-disruption",
    ],
)
def test_azure_redis_service_links_and_experiment_pages_are_available(client, experiment_id):
    service_page = client.get("/service/azure_redis")
    experiment_page = client.get(f"/experiment/azure_redis/{experiment_id}")

    assert f'href="/experiment/azure_redis/{experiment_id}"'.encode() in service_page.data
    assert b"Chaos Studio" in service_page.data
    assert b"Custom" in service_page.data
    assert experiment_page.status_code == 200


def test_eks_page_groups_chaos_mesh_and_eks_fis_experiments(client):
    response = client.get("/service/eks")

    assert response.status_code == 200
    assert b"Chaos Mesh" in response.data
    assert b"FIS" in response.data
    assert b"/experiment/chaos_mesh/" in response.data
    assert b"/experiment/fis/fis-create-experiment?" in response.data
    assert b"fis_service_id=eks" in response.data


def test_dashboard_displays_chaosforge_version(client, monkeypatch):
    monkeypatch.setattr(web_app, "chaosforge_version", lambda: "9.9.9")

    response = client.get("/")

    assert b"ChaosForge v9.9.9" in response.data


def test_all_web_pages_include_the_shared_version_footer():
    from pathlib import Path

    templates = Path(web_app.__file__).resolve().parent / "templates"
    pages = [path for path in templates.glob("*.html") if path.name.startswith("_") is False]

    assert pages
    assert all('{% include "_version_footer.html" %}' in path.read_text(encoding="utf-8") for path in pages)


def test_component_fis_form_uses_catalog_name_and_canonical_target_arn(client, monkeypatch):
    resources = MagicMock()
    resources.discover.return_value = [
        {"name": "database", "arn": "arn:aws:rds:region:account:db:database"}
    ]
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=resources))

    response = client.get(
        "/experiment/fis/fis-create-experiment?fis_service_id=rds&fis_experiment_id=reboot-instance"
    )

    assert response.status_code == 200
    assert b"<h2>Reboot Instance</h2>" in response.data
    assert b"Amazon RDS" in response.data
    assert b"Reboot Instance (AWS FIS)" not in response.data
    assert b'name="fis_service_picker"' not in response.data
    assert b'name="fis_experiment_picker"' not in response.data
    assert b'name="service_id" value="rds"' in response.data
    assert b'name="experiment_id" value="reboot-instance"' in response.data
    assert b'option value="arn:aws:rds:region:account:db:database"' in response.data
    assert b"RDS Target" in response.data
    assert b'name="created_by"' in response.data
    assert b"readonly" in response.data


def test_rds_instance_class_form_uses_a_dependent_target_class_selector(client):
    response = client.get("/experiment/rds/rds-instance-class")

    assert response.status_code == 200
    assert b'name="target_instance_class"' in response.data
    assert b'data-resource="rds-instance-class"' in response.data
    assert b'data-parent="db_instance_identifier"' in response.data
    assert b'disabled' in response.data


def test_rds_instance_class_api_returns_rds_approved_choices(client, monkeypatch):
    selector = MagicMock()
    selector.select_child_resources.return_value = [{"name": "db.t4g.large"}]
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))

    response = client.get(
        "/api/resources/rds/database/rds-instance-class/eu-central-1"
    )

    assert response.get_json() == [{"name": "db.t4g.large"}]
    selector.select_child_resources.assert_called_once_with(
        "rds", "database", "rds-instance-class"
    )


def test_rds_instance_class_api_reports_when_the_instance_is_busy(client, monkeypatch):
    selector = MagicMock()
    selector.select_child_resources.side_effect = RuntimeError(
        "RDS instance 'database' is storage-optimization; wait until it is available before loading target classes."
    )
    monkeypatch.setattr(web_app, "ResourceSelector", MagicMock(return_value=selector))

    response = client.get(
        "/api/resources/rds/database/rds-instance-class/eu-central-1"
    )

    assert response.status_code == 409
    assert "storage-optimization" in response.get_json()["error"]


def test_elasticache_fis_form_uses_replication_group_target_selector(client, monkeypatch):
    resources = MagicMock()
    resources.discover.return_value = [
        {
            "name": "chaosforge-e2e-redis",
            "arn": "arn:aws:elasticache:eu-central-1:123:replicationgroup:chaosforge-e2e-redis",
        }
    ]
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=resources))

    response = client.get(
        "/experiment/fis/fis-create-experiment?"
        "fis_service_id=elasticache&fis_experiment_id=interrupt-az-power"
    )

    assert response.status_code == 200
    resources.discover.assert_called_once_with("elasticache-replication-group")
    assert b'option value="arn:aws:elasticache:eu-central-1:123:replicationgroup:chaosforge-e2e-redis"' in response.data


def test_component_fis_post_submits_selected_target_arn_and_catalog_name(client, monkeypatch):
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "principal_arn": "arn:aws:sts::123456789012:assumed-role/Administrator/operator@example.com",
        },
    )
    monkeypatch.setattr(
        web_app.AzureRedisChaosIdentityService,
        "readiness",
        lambda *_args: {"status": "ready"},
    )

    response = client.post(
        "/experiment/fis/fis-create-experiment?fis_service_id=rds&fis_experiment_id=reboot-instance",
        data={
            "experiment_name": "RDS reboot test",
            "description": "Controlled reboot",
            "created_by": "operator",
            "aws_region": "eu-central-1",
            "target_arn": "arn:aws:rds:eu-central-1:123456789012:db:database",
            "role_arn": "arn:aws:iam::123456789012:role/FISRole",
            "auto_delete_template": "N",
            "service_id": "rds",
            "experiment_id": "reboot-instance",
        },
    )

    assert response.status_code == 302
    selected = add.call_args.args[1]
    created = create_experiment("fis", selected, add.call_args.args[2])
    assert created.name == "Reboot Instance (AWS FIS)"
    assert created.variables["target_arn"].endswith(":db:database")
    assert created.variables["service_id"] == "rds"
    assert created.variables["experiment_id"] == "reboot-instance"
    assert created.variables["created_by"] == "operator@example.com"


def test_lambda_invocation_delay_fis_form_binds_component_and_hides_derived_inputs(client, monkeypatch):
    resources = MagicMock()
    resources.discover.return_value = [{"name": "processor", "arn": "arn:aws:lambda:eu-central-1:123:function:processor"}]
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=resources))
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "principal_arn": "arn:aws:sts::123456789012:assumed-role/Administrator/chaos-operator@example.com"
        },
    )

    response = client.get(
        "/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id=invocation-delay"
    )

    assert response.status_code == 200
    assert b"<h2>Invocation Delay</h2>" in response.data
    assert b'name="fis_service_picker"' not in response.data
    assert b'name="fis_experiment_picker"' not in response.data
    assert b'name="service_id" value="lambda"' in response.data
    assert b'name="experiment_id" value="invocation-delay"' in response.data
    assert b'name="startup_delay_milliseconds"' in response.data
    assert b'name="percentage"' in response.data
    assert b'name="duration"' in response.data
    assert b'name="fis_config_bucket"' in response.data
    assert b'name="fis_extension_layer_arn"' not in response.data
    assert b"FIS Configuration S3 Bucket" in response.data
    assert b"View Lambda Execution Role Policy" in response.data
    assert b"your_s3_bucket/FisConfigs/*" in response.data
    assert b"Lambda Function" in response.data
    assert b'option value="arn:aws:lambda:eu-central-1:123:function:processor"' in response.data
    assert b'style="display:block;"' in response.data
    assert b'name="created_by"' in response.data
    assert b"readonly" in response.data
    assert b"chaos-operator@example.com" in response.data


def test_lambda_invocation_delay_fis_post_uses_authenticated_principal(client, monkeypatch):
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "principal_arn": "arn:aws:sts::123456789012:assumed-role/Administrator/chaos-operator@example.com",
        },
    )

    response = client.post(
        "/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id=invocation-delay",
        data={
            "experiment_name": "Lambda delay test",
            "description": "Controlled invocation delay",
            "aws_region": "eu-central-1",
            "target_arn": "arn:aws:lambda:eu-central-1:123456789012:function:processor",
            "role_arn": "arn:aws:iam::123456789012:role/FISRole",
            "startup_delay_milliseconds": "1500",
            "percentage": "75",
            "duration": "PT2M",
            "fis_config_bucket": "fis-config",
            "created_by": "spoofed-operator",
            "auto_delete_template": "N",
        },
    )

    assert response.status_code == 302
    values = add.call_args.args[2]
    assert values["service_id"] == "lambda"
    assert values["experiment_id"] == "invocation-delay"
    assert values["created_by"] == "chaos-operator@example.com"
    assert values["startup_delay_milliseconds"] == 1500
    assert values["percentage"] == 75
    assert values["duration"] == "PT2M"
    assert values["fis_config_bucket"] == "fis-config"


def test_lambda_invocation_delay_fis_requires_authenticated_principal(client, monkeypatch):
    add = MagicMock()
    discovery = MagicMock()
    discovery.discover.side_effect = RuntimeError("AWS discovery unavailable")
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": False, "name": "Not logged in"},
    )

    response = client.post(
        "/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id=invocation-delay",
        data={
            "experiment_name": "Lambda delay test",
            "description": "Controlled invocation delay",
            "aws_region": "eu-central-1",
            "target_arn": "arn:aws:lambda:eu-central-1:123456789012:function:processor",
            "role_arn": "arn:aws:iam::123456789012:role/FISRole",
            "fis_config_bucket": "fis-config",
            "auto_delete_template": "N",
        },
    )

    assert response.status_code == 400
    assert b"Log in with the AWS CLI before adding this experiment" in response.data
    add.assert_not_called()


@pytest.mark.parametrize(
    ("experiment_id", "parameter"),
    [
        ("invocation-error", "prevent_execution"),
        ("http-response", "status_code"),
    ],
)
def test_other_lambda_fis_actions_share_lambda_prerequisites(client, monkeypatch, experiment_id, parameter):
    resources = MagicMock()
    resources.discover.return_value = [
        {"name": "processor", "arn": "arn:aws:lambda:eu-central-1:123:function:processor"}
    ]
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock(return_value=resources))
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"principal_arn": "arn:aws:sts::123:assumed-role/Admin/operator@example.com"},
    )

    response = client.get(
        f"/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id={experiment_id}"
    )

    assert response.status_code == 200
    assert parameter.encode() in response.data
    assert b'name="fis_config_bucket"' in response.data
    assert b"View Lambda Execution Role Policy" in response.data
    assert b"Lambda Function" in response.data


def test_experiment_template_keeps_iam_policy_as_bootstrap_modal(client):
    response = client.get(
        "/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id=invocation-delay"
    )
    body = response.get_data(as_text=True)
    stylesheet = (Path(web_app.app.static_folder) / "style.css").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert 'data-bs-toggle="modal"' in body
    assert 'id="iamPolicyModal"' in body
    assert "bootstrap.bundle.min.js" in body
    assert ":not(.modal):not(script)" in stylesheet


def test_component_fis_metadata_ignores_unknown_catalog_action(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = None
    monkeypatch.setattr(web_app, "FISCatalog", MagicMock(return_value=catalog))
    selected = {"id": "fis-create-experiment", "name": "Create and Start FIS Experiment"}

    assert web_app._component_fis_metadata(selected, "rds", "unknown") is selected


def test_aws_service_pages_include_every_cli_visible_native_and_fis_experiment(client):
    fis_catalog = web_app.FISCatalog()

    for service in discover_services("aws"):
        response = client.get(f"/service/{service}")

        assert response.status_code == 200
        for experiment in ExperimentCatalog().load_service(service)["experiments"] if service != "kinesis" else []:
            assert experiment["name"].encode() in response.data
        for experiment in fis_catalog.get_experiments(service):
            assert experiment["name"].encode() in response.data
            assert (
                f"fis_service_id={service}&amp;fis_experiment_id={experiment['id']}".encode()
                in response.data
            )
            assert b"engine-label-fis" in response.data
            assert f"Run the AWS FIS {experiment['name'].lower()} action".encode() in response.data


def test_kinesis_service_page_shows_its_fis_only_catalog(client):
    response = client.get("/service/kinesis")
    fis_experiments = web_app.FISCatalog().get_experiments("kinesis")

    assert response.status_code == 200
    assert response.data.count(b"engine-label-fis") == len(fis_experiments)
    for experiment in fis_experiments:
        assert experiment["name"].encode() in response.data


def test_service_cards_show_uniform_engine_labels_and_descriptions(client):
    lambda_page = client.get("/service/lambda")
    eks_page = client.get("/service/eks")
    redis_page = client.get("/service/azure_redis")

    assert b"engine-label-chaos-toolkit" in lambda_page.data
    assert b"Runs the controlled memory modification resilience experiment." in lambda_page.data
    assert b"engine-label-fis" in eks_page.data
    assert b"engine-label-chaos-mesh" in eks_page.data
    assert b"engine-label-chaos-studio" in redis_page.data


@pytest.mark.parametrize(
    ("service", "experiment", "label"),
    [
        ("lambda", {"id": "memory", "name": "Memory"}, "Chaos Toolkit"),
        ("fis", {"id": "fault", "name": "Fault"}, "FIS"),
        ("chaos_mesh", {"id": "pod", "name": "Pod"}, "Chaos Mesh"),
        ("aks", {"id": "aks-pod-kill", "name": "Pod Kill"}, "Chaos Studio"),
        (
            "azure_redis",
            {"id": "reboot", "name": "Reboot", "engine": "Azure Chaos Studio"},
            "Chaos Studio",
        ),
        (
            "azure_redis",
            {"id": "flush", "name": "Flush", "engine": "Azure SDK"},
            "Custom",
        ),
    ],
)
def test_presentation_maps_each_experiment_to_its_execution_engine_label(
    service, experiment, label
):
    assert present_experiment(service, experiment)["engine_label"] == label


def test_eks_fis_link_preselects_the_catalog_action(client):
    response = client.get(
        "/experiment/fis/fis-create-experiment?fis_service_id=eks&"
        "fis_experiment_id=pod-cpu-stress"
    )

    assert response.status_code == 200
    assert b'name="fis_service_picker"' not in response.data
    assert b'name="fis_experiment_picker"' not in response.data
    assert b'name="service_id" value="eks"' in response.data
    assert b'name="experiment_id" value="pod-cpu-stress"' in response.data
    assert b'href="/service/eks"' in response.data


def test_redis_form_uses_choice_and_number_controls(client):
    response = client.get("/experiment/azure_redis/azure-redis-reboot")

    assert response.status_code == 200
    assert b'name="subscription_id"' in response.data
    assert b'name="resource_group"' in response.data
    assert b"data-azure-resource-groups" in response.data
    assert b"data-azure-redis-caches" in response.data
    assert b"azure-resource-context.js" in response.data
    assert b'name="reboot_type"' in response.data
    assert b"PrimaryNode" in response.data
    assert b'name="shard_id"' not in response.data
    assert b"azure-redis-chaos-identity-help" in response.data


def test_aks_form_loads_resource_groups_without_location_field(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Development subscription",
        },
    )

    response = client.get("/experiment/aks/aks-container-kill")

    assert response.status_code == 200
    assert b"data-azure-resource-groups" in response.data
    assert b"azure-resource-context.js" in response.data
    assert b"Azure Location" not in response.data
    assert b'azure-subscription-name">Development subscription' in response.data
    assert b'id="azure-resource-group-error"' in response.data


def test_aks_forms_use_only_azure_target_loading(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    for experiment in ExperimentCatalog().load_service("aks")["experiments"]:
        experiment_id = experiment["id"]
        response = client.get(f"/experiment/aks/{experiment_id}")

        assert response.status_code == 200, experiment_id
        assert b'name="aws_region"' not in response.data, experiment_id
        assert b"loadSelectedEksTarget" not in response.data, experiment_id
        assert b"azure-experiment.js" in response.data, experiment_id


def test_chaos_mesh_forms_retain_eks_aws_target_loading(client):
    for experiment in ExperimentCatalog().load_service("chaos_mesh")["experiments"]:
        experiment_id = experiment["id"]
        response = client.get(f"/experiment/chaos_mesh/{experiment_id}")

        assert response.status_code == 200, experiment_id
        assert b'name="aws_region"' in response.data, experiment_id
        assert b"loadSelectedEksTarget" in response.data, experiment_id
        assert b"azure-experiment.js" not in response.data, experiment_id


def test_form_normalization_enforces_defaults_choices_and_ranges():
    fields = [
        {"name": "mode", "type": "choice", "choices": ["one", "all"], "required": True},
        {"name": "count", "type": "integer", "default": 2, "min": 1, "max": 3},
    ]

    values, errors = normalize_values(fields, {"mode": "one", "count": "3"})
    assert values == {"mode": "one", "count": 3}
    assert errors == {}

    _, errors = normalize_values(fields, {"mode": "invalid", "count": "5"})
    assert set(errors) == {"mode", "count"}


def test_legacy_aws_catalogs_render_the_shared_region_selector(client):
    response = client.get("/experiment/sns/sns-publish-message")

    assert response.status_code == 200
    assert b'name="aws_region"' in response.data
    assert b"Select AWS Region" in response.data


def test_every_aws_web_experiment_exposes_the_cli_region_contract(client):
    catalog = ExperimentCatalog()
    for service in discover_services("aws"):
        if service == "kinesis":
            continue
        for experiment in catalog.load_service(service)["experiments"]:
            response = client.get(f"/experiment/{service}/{experiment['id']}")

            assert response.status_code == 200
            assert b'name="aws_region"' in response.data


def test_web_form_renders_configuration_hints_and_defaults(client):
    response = client.get("/experiment/lambda/lambda-memory")

    assert response.status_code == 200
    assert b"Enter a numeric value" in response.data
    assert b'value="512"' in response.data


def test_rds_auto_minor_upgrade_web_form_explains_boolean_fault_target(client):
    response = client.get("/experiment/rds/rds-auto-minor-version-upgrade")

    assert response.status_code == 200
    assert b'name="target_auto_minor_version_upgrade"' in response.data
    assert b"Select true or false" in response.data
    assert b"Enter the opposite of the instance" in response.data
    assert b"current Auto Minor Version Upgrade setting" in response.data


def test_every_component_web_experiment_renders_complete_description(client):
    catalog = ExperimentCatalog()
    for service in (*discover_services("aws"), "aks", "azure_redis"):
        if service == "kinesis":
            continue
        for experiment in catalog.load_service(service)["experiments"]:
            response = client.get(f"/experiment/{service}/{experiment['id']}")

            assert response.status_code == 200
            assert response.data.count(b"Experiment Description") == 1
            assert b"Potential Impact" in response.data
            assert b"Expected Behavior" in response.data
            assert b"Runs the controlled" in response.data or b"Adds a configurable" in response.data


def test_web_post_builds_azure_redis_with_shared_factory(client, monkeypatch):
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Test subscription",
        },
    )
    monkeypatch.setattr(
        web_app.AzureRedisChaosIdentityService,
        "readiness",
        lambda *_args: {"status": "ready"},
    )

    response = client.post(
        "/experiment/azure_redis/azure-redis-reboot",
        data={
            "subscription_id": "sub",
            "resource_group": "rg",
            "redis_name": "cache",
            "chaos_identity_id": "/identities/chaosforge-managed-identity",
            "reboot_type": "PrimaryNode",
        },
    )

    assert response.status_code == 302
    metadata, selected, values = add.call_args.args
    assert metadata["service"] == "azure_redis"
    assert selected["id"] == "azure-redis-reboot"
    assert "shard_id" not in values
    assert values["subscription_id"] == "sub"


def test_azure_redis_identity_bootstrap_requires_identity_and_target(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Test subscription",
        },
    )
    bootstrap = MagicMock(return_value={"status": "ready"})
    monkeypatch.setattr(web_app.AzureRedisChaosIdentityService, "bootstrap", bootstrap)

    assert client.post("/api/azure/redis/chaos-identities/sub/bootstrap", json={}).status_code == 400
    response = client.post(
        "/api/azure/redis/chaos-identities/sub/bootstrap",
        json={"resource_group": "rg", "redis_name": "cache"},
    )

    assert response.get_json()["status"] == "ready"
    bootstrap.assert_called_once_with(
        "rg", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache"
    )


def test_azure_redis_identity_bootstrap_normalizes_cache_id_and_reports_work_done(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    bootstrap = MagicMock(return_value={"status": "ready", "role_assigned": True})
    monkeypatch.setattr(web_app.AzureRedisChaosIdentityService, "bootstrap", bootstrap)

    response = client.post(
        "/api/azure/redis/chaos-identities/sub/bootstrap",
        json={"resource_group": "rg", "redis_name": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache"},
    )

    assert response.get_json()["message"] == "Granted Redis Cache Contributor to chaosforge-managed-identity."
    bootstrap.assert_called_once_with(
        "rg", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache"
    )


def test_azure_redis_identity_bootstrap_reports_identity_creation(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    bootstrap = MagicMock(return_value={"status": "ready", "identity_created": True})
    monkeypatch.setattr(web_app.AzureRedisChaosIdentityService, "bootstrap", bootstrap)

    response = client.post(
        "/api/azure/redis/chaos-identities/sub/bootstrap",
        json={"resource_group": "rg", "redis_name": "cache"},
    )

    assert response.get_json()["message"] == "Created chaosforge-managed-identity and confirmed Redis Cache Contributor."


def test_web_assigns_a_new_campaign_before_adding_experiments(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: Campaign(cloud_provider="azure"))
    create = MagicMock()
    add = MagicMock()
    monkeypatch.setattr(web_app, "create_campaign_draft", create)
    monkeypatch.setattr(web_app, "add_experiment", add)

    response = client.post(
        "/experiment/azure_redis/azure-redis-flush",
        data={
            "subscription_id": "sub", "resource_group": "rg", "resource_id": "/redis/cache",
            "new_campaign_name": "Redis validation",
        },
    )

    assert response.status_code == 302
    create.assert_called_once_with("Redis validation", "azure")
    add.assert_called_once()


def test_experiment_form_always_shows_campaign_destination(client):
    response = client.get("/experiment/azure_redis/azure-redis-flush")

    assert response.status_code == 200
    assert b"Campaign destination" in response.data
    assert b"Test campaign" in response.data
    assert b"Change campaign" in response.data


def test_web_requires_campaign_assignment_when_no_draft_is_open(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: Campaign(cloud_provider="azure"))
    monkeypatch.setattr(web_app, "list_campaign_drafts", lambda _: [])

    response = client.post(
        "/experiment/azure_redis/azure-redis-flush",
        data={"subscription_id": "sub", "resource_group": "rg", "resource_id": "/redis/cache"},
    )

    assert response.status_code == 400
    assert b"Choose an existing campaign or enter a new campaign name" in response.data


def test_web_assigns_an_existing_campaign_before_adding_experiments(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(web_app, "get_current_campaign", lambda *_args: Campaign(cloud_provider="azure"))
    open_draft = MagicMock()
    monkeypatch.setattr(web_app, "open_campaign_draft", open_draft)
    monkeypatch.setattr(web_app, "add_experiment", MagicMock())

    response = client.post(
        "/experiment/azure_redis/azure-redis-flush",
        data={"subscription_id": "sub", "resource_group": "rg", "resource_id": "/redis/cache", "campaign_id": "campaign-1"},
    )

    assert response.status_code == 302
    open_draft.assert_called_once_with("campaign-1", "azure")


def test_redis_edit_form_preserves_cache_and_identity_selections(client, monkeypatch):
    experiment = create_experiment(
        "azure_redis",
        {
            "id": "azure-redis-reboot",
            "name": "Reboot Redis",
            "json": "chaos_studio/definitions/azure-redis-reboot.json",
        },
        {
            "subscription_id": "sub",
            "resource_group": "rg",
            "redis_name": "cache",
            "chaos_identity_id": "identity",
            "reboot_type": "AllNodes",
        },
    )
    monkeypatch.setattr(web_app, "get_experiment", lambda index, cloud=None: experiment)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )

    response = client.get("/campaign/edit/0?cloud=azure")

    assert response.status_code == 200
    assert b'data-initial-value="cache"' in response.data
    assert b'data-initial-value="identity"' in response.data


def test_azure_event_hub_edit_form_preserves_namespace_selection(client, monkeypatch):
    resource_id = (
        "/subscriptions/sub/resourceGroups/rg/providers/"
        "Microsoft.EventHub/namespaces/events"
    )
    experiment = create_experiment(
        "azure_event_hub",
        ExperimentCatalog().get_experiment(
            "azure_event_hub", "azure-event-hub-state"
        ),
        {
            "subscription_id": "sub",
            "resource_group": "rg",
            "resource_id": resource_id,
            "desired_state": "Disabled",
            "event_hubs": "*",
            "duration_seconds": "PT5M",
        },
    )
    monkeypatch.setattr(web_app, "get_experiment", lambda index, cloud=None: experiment)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Test subscription",
        },
    )

    response = client.get("/campaign/edit/0?cloud=azure")

    assert response.status_code == 200
    assert f'data-initial-value="{resource_id}"'.encode() in response.data
    assert f'<option value="{resource_id}" selected>events</option>'.encode() in response.data


def test_aws_dynamic_resource_edit_form_preserves_selection(client, monkeypatch):
    metadata = ExperimentCatalog().get_experiment("lambda", "lambda-timeout")
    experiment = create_experiment(
        "lambda",
        metadata,
        {
            "lambda_name": "selected-function",
            "aws_region": "eu-central-1",
            "target_timeout": 10,
            "wait_seconds": "PT30S",
        },
    )
    monkeypatch.setattr(web_app, "get_experiment", lambda index, cloud=None: experiment)
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())

    response = client.get("/campaign/edit/0?cloud=aws")

    assert response.status_code == 200
    assert b'data-initial-value="selected-function"' in response.data


def test_redis_edit_form_accepts_legacy_one_argument_experiment_lookup(client, monkeypatch):
    experiment = SimpleNamespace(
        variables={"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache", "chaos_identity_id": "identity"}
    )
    monkeypatch.setattr(web_app, "get_experiment", lambda _index: experiment)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )

    response = client.get("/experiment/azure_redis/azure-redis-reboot?edit_index=0")

    assert response.status_code == 200


def test_redis_edit_updates_the_azure_campaign(client, monkeypatch):
    update = MagicMock()
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(web_app, "update_experiment", update)
    monkeypatch.setattr(web_app, "create_experiment", MagicMock(return_value=SimpleNamespace()))

    response = client.post(
        "/experiment/azure_redis/azure-redis-flush?edit_index=0",
        data={"subscription_id": "sub", "resource_group": "rg", "resource_id": "/redis/cache"},
    )

    assert response.status_code == 302
    assert update.call_args.args[0] == 0
    assert update.call_args.args[2] == "azure"


def test_dynamic_selectors_render_visible_loading_states(client):
    response = client.get("/experiment/azure_redis/azure-redis-reboot")

    assert b"Loading resource groups" in response.data
    assert b"Loading Azure Chaos identity" in response.data
    assert b"Loading resources" in response.data
    loader = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/azure-resource-context.js").read_text()
    assert 'placeholder.replace(/^Select\\s+/i, "")' in loader
    assert 'select.innerHTML = `<option value="">${placeholder}</option>`;' in loader
    assert b"azure-redis-identity-status" in response.data
    assert b"Set Up Azure Chaos Identity and Redis Permission" in response.data
    assert 'chaosIdentity.innerHTML = `<option value="">${error.message}</option>`;' not in loader


def test_azure_sdk_custom_experiment_uses_component_target_selector_without_identity_setup(client):
    response = client.get("/experiment/azure_redis/azure-redis-flush")
    script = (web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/azure-component-context.js").read_text()

    assert response.status_code == 200
    assert b'data-azure-component-resource="azure_redis"' in response.data
    assert b"Set Up Azure Chaos Identity and Redis Permission" not in response.data
    assert "if (!subscription || !resourceGroup || !resource) return;" in script
    assert "bootstrap?.addEventListener" in script


def test_dynamic_edit_selectors_preserve_azure_and_aws_values():
    azure_script = (
        web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/azure-component-context.js"
    ).read_text()
    template = (
        web_app.PROJECT_ROOT / "chaosforge/interfaces/web/templates/experiment.html"
    ).read_text()

    assert "sameArmId(item.id, initial)" in azure_script
    assert "if (initial && !matched)" in azure_script
    assert "option.textContent = displayName(initial)" in azure_script
    assert 'resourceGroup.addEventListener("azure-options-loaded", loadResources)' in azure_script
    assert "!Array.from(select.options).some(option => option.value === preservedValue)" in template
    assert "!Array.from(child.options).some(option => option.value === preservedChildValue)" in template
    assert "option.textContent = storedResourceLabel(preservedValue)" in template
    assert "option.textContent = storedResourceLabel(preservedChildValue)" in template


def test_azure_component_identity_loader_ignores_stale_requests():
    script = (
        web_app.PROJECT_ROOT / "chaosforge/interfaces/web/static/azure-component-context.js"
    ).read_text()

    assert "const loadVersions = new WeakMap();" in script
    assert "if (loadVersions.get(select) !== version) return;" in script
    assert "identity?.addEventListener(\"chaosforge-load-identity\", loadIdentities);" in script


def test_azure_redis_identity_endpoints_require_matching_login_and_report_errors(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": False})
    assert client.get("/api/azure/redis/chaos-identities/sub").status_code == 401
    assert client.post("/api/azure/redis/chaos-identities/sub/bootstrap", json={}).status_code == 401

    monkeypatch.setattr(
        web_app, "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(web_app.AzureRedisChaosIdentityService, "list_identities", lambda *_: (_ for _ in ()).throw(RuntimeError("denied")))
    response = client.get("/api/azure/redis/chaos-identities/sub")
    assert response.status_code == 400
    assert response.get_json()["error"] == "denied"

    monkeypatch.setattr(web_app.AzureRedisChaosIdentityService, "bootstrap", lambda *_: (_ for _ in ()).throw(RuntimeError("no permission")))
    response = client.post(
        "/api/azure/redis/chaos-identities/sub/bootstrap",
        json={"resource_group": "rg", "redis_name": "cache"},
    )
    assert response.status_code == 400
    assert "no permission" in response.get_json()["error"]


def test_azure_redis_identity_list_endpoint_returns_available_identities(client, monkeypatch):
    monkeypatch.setattr(
        web_app, "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(
        web_app.AzureRedisChaosIdentityService, "list_identities",
        lambda *_: [{"id": "identity", "name": "chaosforge-managed-identity"}],
    )

    response = client.get("/api/azure/redis/chaos-identities/sub")

    assert response.status_code == 200
    assert response.get_json()[0]["id"] == "identity"


def test_fis_template_options_return_provider_errors(client, monkeypatch):
    monkeypatch.setattr(web_app, "FISService", MagicMock(side_effect=RuntimeError("FIS access denied")))

    response = client.get("/api/fis/templates/eu-central-1")

    assert response.status_code == 400
    assert response.get_json() == {"error": "FIS access denied"}


def test_generic_azure_component_resource_and_identity_endpoints(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(web_app, "list_component_resources", lambda *_args: [{"id": "/vm", "name": "vm"}])
    monkeypatch.setattr(web_app.AzureChaosIdentityService, "list_identities", lambda *_: [{"id": "/identity"}])
    monkeypatch.setattr(web_app, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))
    bootstrap = MagicMock(return_value={"status": "ready"})
    monkeypatch.setattr(web_app.AzureChaosIdentityService, "bootstrap", bootstrap)

    resources = client.post("/api/azure/components/azure_vm/resources/sub", json={"resource_group": "rg"})
    identities = client.post("/api/azure/components/azure_vm/chaos-identities/sub")
    setup = client.post(
        "/api/azure/components/azure_vm/chaos-identities/sub/bootstrap",
        json={"resource_group": "rg", "resource_id": "/vm", "experiment_id": "azure-vm-redeploy"},
    )

    assert resources.get_json() == [{"id": "/vm", "name": "vm"}]
    assert identities.get_json() == [{"id": "/identity"}]
    assert setup.get_json()["message"] == "chaosforge-managed-identity already has VM Contributor on this target."
    bootstrap.assert_called_once_with("rg", "/vm", "VM Contributor")


def test_vmss_instance_endpoint_requires_azure_identity_and_lists_instances(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    instances = MagicMock(return_value=[{"id": "0", "name": "Instance 0"}])
    monkeypatch.setattr(web_app.AzureResourceDiscovery, "list_virtual_machine_scale_set_instances", instances)

    response = client.post(
        "/api/azure/components/azure_vmss/instances/sub",
        json={"resource_group": "rg", "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/set"},
    )

    assert response.get_json() == [{"id": "0", "name": "Instance 0"}]
    instances.assert_called_once_with("rg", "set")


def test_vmss_instance_endpoint_rejects_wrong_identity_and_reports_provider_errors(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": False})
    unauthorized = client.post("/api/azure/components/azure_vmss/instances/sub", json={})
    assert unauthorized.status_code == 401

    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(
        web_app.AzureResourceDiscovery,
        "list_virtual_machine_scale_set_instances",
        lambda *_: (_ for _ in ()).throw(RuntimeError("instance denied")),
    )
    response = client.post(
        "/api/azure/components/azure_vmss/instances/sub",
        json={"resource_group": "rg", "resource_id": "/scale-sets/set"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "instance denied"


def test_generic_azure_component_endpoints_reject_unknown_or_incomplete_requests(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": False})
    assert client.post("/api/azure/components/unknown/resources/sub", json={}).status_code == 404
    assert client.post("/api/azure/components/azure_vm/resources/sub", json={}).status_code == 401
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"})
    assert client.post("/api/azure/components/azure_vm/chaos-identities/sub/bootstrap", json={}).status_code == 400


def test_generic_azure_component_endpoints_report_provider_errors_and_bootstrap_outcomes(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(
        web_app,
        "list_component_resources",
        lambda *_: (_ for _ in ()).throw(RuntimeError("resource denied")),
    )
    resources = client.post("/api/azure/components/azure_vm/resources/sub", json={"resource_group": "rg"})
    assert resources.status_code == 400
    assert resources.get_json()["error"] == "resource denied"

    monkeypatch.setattr(
        web_app.AzureChaosIdentityService,
        "list_identities",
        lambda *_: (_ for _ in ()).throw(RuntimeError("identity denied")),
    )
    identities = client.get("/api/azure/components/azure_vm/chaos-identities/sub")
    assert identities.status_code == 400
    assert identities.get_json()["error"] == "identity denied"

    monkeypatch.setattr(web_app, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))
    bootstrap = MagicMock(return_value={"status": "ready"})
    monkeypatch.setattr(web_app.AzureChaosIdentityService, "bootstrap", bootstrap)
    response = client.post(
        "/api/azure/components/azure_vm/chaos-identities/sub/bootstrap",
        json={"resource_group": "rg", "resource_id": "/vm", "experiment_id": "fault"},
    )
    assert response.status_code == 200
    assert response.get_json()["message"] == "chaosforge-managed-identity already has VM Contributor on this target."


def test_generic_azure_component_identity_endpoint_includes_requested_identity(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(web_app.AzureChaosIdentityService, "list_identities", lambda *_: [])
    requested = {"id": "/identities/custom", "name": "custom", "principal_id": "principal"}
    monkeypatch.setattr(web_app.AzureChaosIdentityService, "get_identity", lambda *_: requested)

    response = client.post(
        "/api/azure/components/azure_vm/chaos-identities/sub",
        json={"identity_id": "/identities/custom"},
    )

    assert response.status_code == 200
    assert response.get_json() == [requested]


def test_generic_azure_component_identity_endpoints_reject_and_report_bootstrap_variants(client, monkeypatch):
    monkeypatch.setattr(web_app, "get_cloud_identity", lambda *_args, **_kwargs: {"authenticated": False})
    unsupported = client.get("/api/azure/components/unknown/chaos-identities/sub")
    unauthorized = client.get("/api/azure/components/azure_vm/chaos-identities/sub")
    bootstrap_unauthorized = client.post(
        "/api/azure/components/azure_vm/chaos-identities/sub/bootstrap", json={}
    )

    assert unsupported.status_code == 404
    assert unauthorized.status_code == 401
    assert bootstrap_unauthorized.status_code == 401

    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(web_app, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))

    for outcome, message in (
        ({"identity_created": True, "role_assigned": False}, "Created chaosforge-managed-identity and confirmed VM Contributor."),
        ({"identity_created": False, "role_assigned": True}, "Granted VM Contributor to chaosforge-managed-identity."),
    ):
        service = MagicMock()
        service.bootstrap.return_value = {"status": "ready"}
        service.last_bootstrap_outcome = outcome
        monkeypatch.setattr(web_app, "AzureChaosIdentityService", MagicMock(return_value=service))

        response = client.post(
            "/api/azure/components/azure_vm/chaos-identities/sub/bootstrap",
            json={"resource_group": "rg", "resource_id": "/vm", "experiment_id": "fault"},
        )

        assert response.status_code == 200
        assert response.get_json()["message"] == message

    monkeypatch.setattr(web_app, "fault_details", lambda *_: (_ for _ in ()).throw(RuntimeError("denied")))
    response = client.post(
        "/api/azure/components/azure_vm/chaos-identities/sub/bootstrap",
        json={"resource_group": "rg", "resource_id": "/vm", "experiment_id": "fault"},
    )
    assert response.status_code == 400
    assert "denied" in response.get_json()["error"]


def test_generic_azure_component_web_post_does_not_block_identity_readiness(client, monkeypatch):
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )
    monkeypatch.setattr(web_app, "fault_details", lambda *_: ("urn", "target", "VM Contributor"))
    monkeypatch.setattr(
        web_app.AzureChaosIdentityService,
        "readiness",
        lambda *_: {"status": "missing_role", "message": "Grant VM Contributor"},
    )

    response = client.post(
        "/experiment/azure_vm/azure-vm-redeploy",
        data={"resource_group": "rg", "resource_id": "/vm", "chaos_identity_id": "/identity"},
    )

    assert response.status_code == 302
    add.assert_called_once()

    monkeypatch.setattr(
        web_app.AzureChaosIdentityService,
        "readiness",
        lambda *_: (_ for _ in ()).throw(RuntimeError("identity lookup failed")),
    )


def test_azure_redis_web_post_allows_unready_identity_for_later_execution_preflight(client, monkeypatch):
    monkeypatch.setattr(
        web_app, "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)

    response = client.post(
        "/experiment/azure_redis/azure-redis-reboot",
        data={"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache", "chaos_identity_id": "identity", "reboot_type": "AllNodes", "shard_id": "0"},
    )

    assert response.status_code == 302
    add.assert_called_once()


def test_azure_redis_web_post_does_not_query_identity_readiness(client, monkeypatch):
    monkeypatch.setattr(
        web_app, "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(
        web_app.AzureRedisChaosIdentityService, "readiness",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("identity denied")),
    )
    monkeypatch.setattr(web_app, "add_experiment", MagicMock())

    response = client.post(
        "/experiment/azure_redis/azure-redis-reboot",
        data={"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache", "chaos_identity_id": "identity", "reboot_type": "AllNodes", "shard_id": "0"},
    )

    assert response.status_code == 302


def test_azure_redis_web_post_does_not_query_unhandled_identity_sdk_errors(client, monkeypatch):
    monkeypatch.setattr(
        web_app, "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(
        web_app.AzureRedisChaosIdentityService, "readiness",
        lambda *_args: (_ for _ in ()).throw(Exception("Azure role lookup denied")),
    )
    monkeypatch.setattr(web_app, "add_experiment", MagicMock())

    response = client.post(
        "/experiment/azure_redis/azure-redis-reboot",
        data={"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache", "chaos_identity_id": "identity", "reboot_type": "AllNodes"},
    )

    assert response.status_code == 302


def test_web_post_reports_campaign_persistence_errors(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(web_app, "add_experiment", MagicMock(side_effect=ValueError("invalid draft")))

    response = client.post(
        "/experiment/azure_redis/azure-redis-flush",
        data={"subscription_id": "sub", "resource_group": "rg", "resource_id": "/redis/cache"},
    )

    assert response.status_code == 400
    assert b"Could not add experiment to the campaign: invalid draft" in response.data


def test_web_post_reports_duplicate_experiment_errors(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub", "name": "Test subscription"},
    )
    monkeypatch.setattr(
        web_app,
        "add_experiment",
        MagicMock(side_effect=ValueError("Campaign already contains an identical experiment configuration.")),
    )

    response = client.post(
        "/experiment/azure_redis/azure-redis-reboot",
        data={"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache", "chaos_identity_id": "identity", "reboot_type": "AllNodes"},
    )

    assert response.status_code == 400
    assert b"Campaign already contains an identical experiment configuration" in response.data


def test_web_post_builds_aks_without_location_input(client, monkeypatch):
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Development subscription",
        },
    )
    discovery = MagicMock()
    discovery.get_label_selector.return_value = ("app", "api")
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))

    response = client.post(
        "/experiment/aks/aks-pod-kill",
        data={
            "resource_group": "rg",
            "aks_context": "cluster",
            "namespace": "apps",
            "deployment": "api",
            "location": "ignored",
        },
    )

    assert response.status_code == 302
    values = add.call_args.args[2]
    assert values["subscription_id"] == "sub"
    assert values["resource_group"] == "rg"
    assert values["aks_name"] == "cluster"
    assert "location" not in values


def test_web_post_expands_aks_zone_failure_to_zone_nodes(client, monkeypatch):
    add = MagicMock()
    monkeypatch.setattr(web_app, "add_experiment", add)
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Development subscription",
        },
    )
    discovery = MagicMock()
    discovery.list_nodes_in_zone.return_value = ["node-a", "node-b"]
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))

    response = client.post(
        "/experiment/aks/aks-node-zone-failure",
        data={
            "resource_group": "rg",
            "aks_context": "cluster",
            "target_zone": "zone-1",
            "duration": "PT60S",
        },
    )

    assert response.status_code == 302
    values = add.call_args.args[2]
    assert values["target_node"] == "node-a,node-b"
    discovery.list_nodes_in_zone.assert_called_once_with("cluster", "zone-1")


def test_web_post_rejects_aks_zone_without_worker_nodes(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "subscription_id": "sub",
            "name": "Development subscription",
        },
    )
    discovery = MagicMock()
    discovery.list_nodes_in_zone.return_value = []
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))

    response = client.post(
        "/experiment/aks/aks-node-zone-failure",
        data={
            "resource_group": "rg",
            "aks_context": "cluster",
            "target_zone": "zone-1",
            "duration": "PT60S",
        },
    )

    assert response.status_code == 400
    assert b"No worker nodes were found" in response.data


def test_factory_gives_web_and_cli_identical_azure_execution_identity():
    metadata = ExperimentCatalog().get_experiment("aks", "aks-pod-kill")
    variables = {
        "subscription_id": "sub",
        "resource_group": "rg",
        "aks_context": "cluster",
        "namespace": "apps",
        "deployment": "api",
    }

    experiment = create_experiment("aks", metadata, variables)

    assert experiment.engine == "Azure Chaos Studio"
    assert experiment.variables["experiment_id"] == "aks-pod-kill"
    assert "aws_region" not in experiment.variables


def test_azure_discovery_api_reuses_provider_discovery(client, monkeypatch):
    discovery = MagicMock()
    discovery.list_contexts.return_value = ["cluster-a"]
    discovery.list_namespaces.return_value = ["apps"]
    monkeypatch.setattr(web_app, "AzureAKSDiscovery", MagicMock(return_value=discovery))

    assert client.get("/api/azure/aks/contexts").get_json() == [
        {"id": "cluster-a", "name": "cluster-a"}
    ]
    assert client.get("/api/azure/aks/namespaces/cluster-a").get_json() == [
        {"id": "apps", "name": "apps"}
    ]


def test_eks_chaos_mesh_web_form_shows_target_mode_choices(client):
    response = client.get("/experiment/chaos_mesh/chaos-mesh-pod-failure")

    assert response.status_code == 200
    assert b"Target Mode" in response.data
    assert b"By Deployment - target pods via deployment label selector" in response.data
    assert b"By Pod - target a single specific pod directly" in response.data
    assert b'const targetMode = document.getElementById("target_mode")' in response.data


def test_eks_container_kill_web_form_reloads_containers_after_target_selection(client):
    response = client.get("/experiment/chaos_mesh/chaos-mesh-container-kill")

    assert response.status_code == 200
    assert b'const containerSelect = document.querySelector(\'select[data-resource="eks-container"]\')' in response.data
    assert b'targetModeSelect?.addEventListener("change", loadSelectedEksTarget)' in response.data
    assert b'deploymentSelect?.addEventListener("change", loadSelectedEksContainers)' in response.data
    assert b'podSelect?.addEventListener("change", loadSelectedEksContainers)' in response.data


def test_aks_web_form_shows_target_mode_choices(client):
    response = client.get("/experiment/aks/aks-container-kill")

    assert response.status_code == 200
    assert b"Target Mode" in response.data
    assert b'azure_aks_pod' in response.data


def test_apigateway_web_form_uses_one_region_selector_and_api_gateway_label(client):
    response = client.get("/experiment/apigateway/apigateway-stage-throttling")

    assert response.status_code == 200
    assert response.data.count(b'name="aws_region"') == 1
    assert b"API Gateway" in response.data
    assert b"REST API" not in response.data
    assert b"function loadTopLevelResources()" in response.data
    assert b"if (getSelectedRegion())" in response.data


def test_bound_fis_s3_form_loads_target_selector_with_selected_region(client):
    response = client.get(
        "/experiment/fis/fis-create-experiment?fis_service_id=s3&fis_experiment_id=pause-replication"
    )

    assert response.status_code == 200
    assert b'data-resource="s3"' in response.data
    assert b"loadTopLevelResources();" in response.data


def test_azure_redis_discovery_apis_reuse_shared_provider_discovery(client, monkeypatch):
    discovery = MagicMock()
    discovery.list_resource_groups.return_value = [{"id": "rg-a", "name": "rg-a"}]
    discovery.list_redis_caches.return_value = [{"id": "cache-a", "name": "cache-a"}]
    monkeypatch.setattr(web_app, "AzureResourceDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )

    assert client.get("/api/azure/resource-groups/sub").get_json() == [
        {"id": "rg-a", "name": "rg-a"}
    ]
    assert client.get("/api/azure/redis/caches/sub/rg-a").get_json() == [
        {"id": "cache-a", "name": "cache-a"}
    ]
    discovery.list_resource_groups.assert_called_once_with()
    discovery.list_redis_caches.assert_called_once_with("rg-a")


def test_azure_redis_discovery_api_returns_provider_errors(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "AzureResourceDiscovery",
        MagicMock(side_effect=ValueError("Azure subscription ID is required.")),
    )
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "sub"},
    )

    response = client.get("/api/azure/resource-groups/sub")

    assert response.status_code == 400
    assert response.get_json()["error"] == "Azure subscription ID is required."


def test_azure_redis_discovery_api_rejects_an_unselected_subscription(client, monkeypatch):
    monkeypatch.setattr(
        web_app,
        "get_cloud_identity",
        lambda *_args, **_kwargs: {"authenticated": True, "subscription_id": "other"},
    )

    response = client.get("/api/azure/resource-groups/sub")

    assert response.status_code == 401
    assert "Log in" in response.get_json()["error"]


def test_web_runner_uses_shared_lifecycle_service_not_subprocess(monkeypatch):
    service = MagicMock()
    service.execute_campaign.return_value = SimpleNamespace(
        status="SUCCESS", executed=[], failed=[]
    )
    runner = WebExperimentRunner(lifecycle_service=service)
    monkeypatch.setattr("chaosforge.interfaces.web.runner.generate_report", MagicMock())
    campaign = SimpleNamespace(experiments=[])

    result = runner.execute_campaign(campaign)

    assert result.status == "SUCCESS"
    service.execute_campaign.assert_called_once()


def test_execution_console_preserves_manual_scroll_contract():
    script = (
        web_app.app.static_folder
        and open(
            f"{web_app.app.static_folder}/execution.js",
            encoding="utf-8",
        ).read()
    )

    assert "wasFollowingTail" in script
    assert "previousScrollTop" in script
    assert "consoleBox.scrollTop = previousScrollTop" in script
    assert "consoleBox.scrollTop = consoleBox.scrollHeight" in script
