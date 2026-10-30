import json
import re
import secrets
import time
from importlib import import_module
from pathlib import Path

# ------------------------------------------------------------------
# Project Root
# ------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]

REPORTS_DIR = PROJECT_ROOT / "runtime" / "reports"

# ------------------------------------------------------------------
# Standard Imports
# ------------------------------------------------------------------

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from chaosforge.application.campaigns.factory import AZURE_SERVICES, create_experiment
from chaosforge.application.campaigns.manager import replace_campaign

# ------------------------------------------------------------------
# Project Imports
# ------------------------------------------------------------------
from chaosforge.application.component_fis import bind_component_fis, prepare_component_fis_variables
from chaosforge.application.discovery import display_name
from chaosforge.application.experiment_descriptions import get_experiment_description
from chaosforge.application.experiment_presentation import present_experiment
from chaosforge.application.field_help import display_label, field_help
from chaosforge.application.iam import iam_actions
from chaosforge.application.metadata_loader import load_metadata
from chaosforge.application.services.campaign_preflight import CampaignPreflightService
from chaosforge.application.services.campaign_service import (
    add_experiment,
    clear_current_campaign,
    create_campaign_draft,
    delete_campaign_draft,
    get_current_campaign,
    get_experiment,
    get_selected_experiments,
    list_campaign_drafts,
    open_campaign_draft,
    remove_experiment,
    save_chaos_mesh_version_decisions,
    update_experiment,
)
from chaosforge.application.services.campaign_yaml import (
    MAX_CAMPAIGN_YAML_BYTES,
    CampaignYAMLService,
)
from chaosforge.application.services.cloud_identity import (
    get_cached_cloud_identity,
    get_cloud_identity,
)
from chaosforge.application.services.permissions import PermissionReportService
from chaosforge.application.services.user_settings import (
    format_timezone,
    format_timezone_offset,
    get_timezone_id,
    set_timezone_id,
    timezone_options,
)
from chaosforge.catalog.loader import AZURE_COMPONENT_PACKAGES
from chaosforge.common.version import chaosforge_version
from chaosforge.engines.chaos_mesh.target_contract import is_workload_experiment
from chaosforge.engines.chaos_mesh.version_policy import (
    apply_execution_actions,
    assess_campaign,
    decision_is_current,
    saved_decision,
)
from chaosforge.interfaces.cli.interactive.region_selector import RegionSelector
from chaosforge.interfaces.cli.interactive.resource_selector import ResourceSelector
from chaosforge.interfaces.web.catalog import (
    CLOUDS,
    cloud_cards,
    service_cards,
    service_cloud,
)
from chaosforge.interfaces.web.config import AWS_REGION
from chaosforge.interfaces.web.execution import (
    ExecutionAlreadyRunning,
    execution_session,
    execution_sessions,
    experiment_target,
    get_executor,
)
from chaosforge.interfaces.web.forms import normalize_values

# ------------------------------------------------------------------
# Web Imports
# ------------------------------------------------------------------
from chaosforge.interfaces.web.log_manager import get_log_manager
from chaosforge.providers.aws.discovery import AWSDiscovery
from chaosforge.providers.aws.fis.catalog import FISCatalog
from chaosforge.providers.azure.chaos_studio.classic import AzureChaosIdentityService
from chaosforge.providers.azure.chaos_studio.classic_faults import fault_details
from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
    AzureRedisChaosIdentityService,
    redis_target_id,
)
from chaosforge.providers.azure.components.registry import list_component_resources
from chaosforge.storage.campaign_history import CampaignHistoryStore

_lambda_fis_prerequisites = import_module(
    "chaosforge.providers.aws.components.lambda.experiments.fis.prerequisites"
)
fis_s3_policy = _lambda_fis_prerequisites.fis_s3_policy
lambda_s3_policy = _lambda_fis_prerequisites.lambda_s3_policy
from chaosforge.providers.aws.fis.service import FISService
from chaosforge.providers.azure.components.aks.discovery import AzureAKSDiscovery
from chaosforge.providers.azure.discovery import AzureResourceDiscovery

app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent / "templates"),
    static_folder=str(Path(__file__).resolve().parent / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = MAX_CAMPAIGN_YAML_BYTES
app.jinja_env.globals["field_help"] = field_help
app.jinja_env.globals["display_label"] = display_label

yaml_service = CampaignYAMLService()
campaign_preflight = CampaignPreflightService()
campaign_history = CampaignHistoryStore()
permission_reports = PermissionReportService()
permission_review_tokens = {}
PERMISSION_REVIEW_TOKEN_TTL_SECONDS = 600


def _safe_download_name(value):
    name = []
    previous_was_replacement = False
    for character in str(value):
        allowed = character.isascii() and (character.isalnum() or character in "._-")
        if allowed:
            name.append(character)
            previous_was_replacement = False
        elif not previous_was_replacement:
            name.append("-")
            previous_was_replacement = True
    return "".join(name).strip("-.")


def _aws_campaign_redirect():
    return redirect("/campaign?cloud=aws")


def _azure_campaign_redirect():
    return redirect("/campaign?cloud=azure")


def _aws_execution_redirect(_run_id=None):
    return redirect("/execution?cloud=aws")


def _azure_execution_redirect(_run_id=None):
    return redirect("/execution?cloud=azure")


def _start_web_execution(campaign, active_campaign=None):
    selected_executor = get_executor(campaign.cloud_provider)

    def sync_outcome(executed_experiment):
        if active_campaign is None:
            return
        from chaosforge.application.campaigns.duplicates import experiment_fingerprint

        fingerprint = experiment_fingerprint(executed_experiment)
        for index, active_experiment in enumerate(active_campaign.experiments):
            if experiment_fingerprint(active_experiment) != fingerprint:
                continue
            active_experiment.status = executed_experiment.status
            active_experiment.error_message = getattr(executed_experiment, "error_message", "")
            active_experiment.warnings = list(getattr(executed_experiment, "warnings", []))
            update_experiment(index, active_experiment, campaign.cloud_provider)
            return

    try:
        return selected_executor.start(campaign, on_experiment_complete=sync_outcome), None
    except ExecutionAlreadyRunning as exc:
        return None, (str(exc), 409)


def _trusted_cloud(value):
    return "azure" if value == "azure" else "aws"


def _campaign_cloud_identity(cloud):
    identity = get_cloud_identity(cloud, refresh=True)
    if identity.get("authenticated"):
        return identity
    return None


def _aws_campaign_library_redirect():
    return redirect("/campaigns?cloud=aws")


def _azure_campaign_library_redirect():
    return redirect("/campaigns?cloud=azure")


def _cloud_services_redirect(cloud, notice=None):
    """Redirect only to a fixed, internal cloud landing route."""
    route = "/cloud/azure" if cloud == "azure" else "/cloud/aws"
    if notice == "campaign-auth-required":
        route += "?notice=campaign-auth-required"
    return redirect(route)


def _current_campaign(cloud=None):
    """Use cloud-scoped state while accepting legacy no-argument test doubles."""
    try:
        return get_current_campaign(cloud) if cloud else get_current_campaign()
    except TypeError:
        return get_current_campaign()


def _selected_experiments(indices, cloud=None):
    try:
        return get_selected_experiments(indices, cloud) if cloud else get_selected_experiments(indices)
    except TypeError:
        return get_selected_experiments(indices)


def _campaign_for_permission_review(cloud, indices=None):
    """Build a provider-scoped campaign without planning or cloud access."""
    from chaosforge.models import Campaign

    cloud = cloud if cloud in CLOUDS else "aws"
    current_campaign = _current_campaign(cloud)
    experiments = (
        _selected_experiments(indices, cloud)
        if indices is not None
        else getattr(current_campaign, "experiments", [])
    )
    campaign = Campaign(
        name=getattr(current_campaign, "name", "Default Campaign"),
        continue_on_failure=getattr(current_campaign, "continue_on_failure", False),
        cloud_provider=cloud,
        campaign_id=getattr(current_campaign, "campaign_id", None),
        created_at=getattr(current_campaign, "created_at", None),
        updated_at=getattr(current_campaign, "updated_at", None),
        chaos_mesh_version_decisions=dict(
            getattr(current_campaign, "chaos_mesh_version_decisions", {})
        ),
    )
    campaign.experiments = [
        experiment for experiment in experiments if service_cloud(experiment.service) == cloud
    ]
    return campaign


def _execution_target(experiment):
    return experiment_target(experiment)


def _execution_label(run):
    """Describe a run by the experiment snapshot, not its campaign name."""
    experiments = run.get("experiments") or run.get("campaign_snapshot", {}).get("experiments", [])
    items = experiments.values() if isinstance(experiments, dict) else experiments
    names = [item.get("name") for item in items if item.get("name")]
    return ", ".join(names) or run.get("campaign_name", "Unnamed campaign")


def _campaign_execution_results(campaign, cloud):
    """Associate persisted run snapshots with the active draft's stable targets."""
    results = {}
    for run in _current_campaign_executions(campaign, cloud):
        for index, experiment in enumerate(getattr(campaign, "experiments", [])):
            target = _execution_target(experiment)
            matched = next(
                (
                    item
                    for item in run.get("experiments", [])
                    if item.get("service") == experiment.service
                    and item.get("id") == experiment.id
                    and _execution_target(type("Snapshot", (), {
                        "service": item.get("service", ""),
                        "variables": item.get("variables", {}),
                    })()) == target
                ),
                None,
            )
            if matched and index not in results:
                results[index] = {
                    "run_id": run["id"],
                    "status": matched.get("status", run.get("status", "")),
                    "log_start": None,
                }
    return results


def _current_campaign_executions(campaign, cloud):
    """Return runs belonging to the campaign configuration since its last clear."""
    runs = campaign_history.list_executions(
        cloud, getattr(campaign, "campaign_id", None)
    )
    return _runs_since_campaign_reset(campaign, runs)


def _runs_since_campaign_reset(campaign, runs):
    """Exclude execution results invalidated by clearing the campaign."""
    reset_at = getattr(campaign, "history_reset_at", None)
    if not reset_at:
        return runs
    return [
        run
        for run in runs
        if (run.get("started_at") or run.get("created_at") or "") >= reset_at
    ]


def _execution_record(cloud, run_id):
    """Load one durable execution only when it belongs to the requested cloud."""
    if not run_id:
        return None
    try:
        record = campaign_history.load_execution(run_id)
    except (FileNotFoundError, ValueError):
        return None
    return record if record.get("cloud") == cloud else None


def _execution_progress(record):
    """Provide a completed progress snapshot for a durable execution record."""
    total = len(record.get("experiments", []))
    return {
        "current": total,
        "total": total,
        "experiment": "",
        "running": False,
        "finished": bool(record.get("completed_at")),
    }


def _approved_report_path(value):
    """Resolve a generated report reference without constructing a user-supplied path."""
    match = re.fullmatch(
        r"(?:.*/)?(campaign-report-\d{8}-\d{6}\.txt)", str(value or "")
    )
    if not match:
        return None
    return next(
        (path for path in _approved_report_paths() if path.name == match.group(1)),
        None,
    )


def _approved_report_paths():
    """List text reports whose resolved paths remain beneath REPORTS_DIR."""
    reports_directory = REPORTS_DIR.resolve()
    reports = []
    for candidate in REPORTS_DIR.glob("*.txt"):
        try:
            report_path = candidate.resolve(strict=True)
            report_path.relative_to(reports_directory)
        except (OSError, ValueError):
            continue
        reports.append(report_path)
    return reports


def _permission_review_token(
    cloud,
    indices,
    *,
    requires_irreversible_acknowledgement=False,
    chaos_mesh_assessments=(),
    chaos_mesh_required_keys=(),
):
    now = time.monotonic()
    expired = [
        value
        for value, review in permission_review_tokens.items()
        if now - review["created_at"] >= PERMISSION_REVIEW_TOKEN_TTL_SECONDS
    ]
    for value in expired:
        permission_review_tokens.pop(value, None)
    token = secrets.token_urlsafe(32)
    permission_review_tokens[token] = {
        "cloud": cloud,
        "indices": tuple(indices) if indices is not None else None,
        "confirmed": False,
        "requires_irreversible_acknowledgement": requires_irreversible_acknowledgement,
        "chaos_mesh_assessments": tuple(chaos_mesh_assessments),
        "chaos_mesh_required_keys": tuple(chaos_mesh_required_keys),
        "chaos_mesh_decisions": {},
        "created_at": now,
    }
    return token


def _confirm_permission_review_token(
    token, *, irreversible_acknowledged=False, chaos_mesh_decisions=None
):
    review = permission_review_tokens.get(token)
    if review is None or time.monotonic() - review["created_at"] >= PERMISSION_REVIEW_TOKEN_TTL_SECONDS:
        permission_review_tokens.pop(token, None)
        return False
    if review["requires_irreversible_acknowledgement"] and not irreversible_acknowledged:
        return False
    supplied = chaos_mesh_decisions or {}
    if not isinstance(supplied, dict):
        return False
    assessments = review.get("chaos_mesh_assessments", ())
    expected_keys = set(review.get("chaos_mesh_required_keys", ()))
    if set(supplied) != expected_keys:
        return False
    normalized = {}
    for assessment in assessments:
        if assessment.key not in expected_keys:
            continue
        action = supplied.get(assessment.key)
        if action not in assessment.choices or action == "cancel":
            return False
        normalized[assessment.key] = saved_decision(action, assessment)
    review["chaos_mesh_decisions"] = normalized
    review["confirmed"] = True
    return True


def _consume_permission_review_token(token, cloud, indices):
    review = permission_review_tokens.pop(token, None)
    valid = bool(
        review
        and time.monotonic() - review["created_at"] < PERMISSION_REVIEW_TOKEN_TTL_SECONDS
        and review["cloud"] == cloud
        and review["indices"] == (tuple(indices) if indices is not None else None)
        and review["confirmed"]
    )
    return review if valid else None


def _apply_reviewed_chaos_mesh_decisions(campaign, review):
    if not isinstance(review, dict):
        return
    assessments = review.get("chaos_mesh_assessments", ())
    decisions = dict(getattr(campaign, "chaos_mesh_version_decisions", {}))
    decisions.update(review.get("chaos_mesh_decisions", {}))
    apply_execution_actions(campaign, assessments, decisions)


def _edit_experiment(index, cloud):
    try:
        return get_experiment(index, cloud)
    except TypeError:
        return get_experiment(index)


def _redis_cache_name(value):
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _campaign_return_target(cloud):
    service = request.args.get("return_service", "")
    experiment_id = request.args.get("return_experiment", "")
    if not service or not experiment_id or service_cloud(service) != cloud:
        return None
    metadata = load_metadata(service)
    if metadata is None or not any(item.get("id") == experiment_id for item in metadata.get("experiments", [])):
        return None
    target = {"return_service": service, "return_experiment": experiment_id}
    edit_index = request.args.get("return_edit_index", type=int)
    if edit_index is not None:
        target["return_edit_index"] = edit_index
    return target


@app.context_processor
def campaign_cart_context():
    cloud = request.view_args.get("cloud") if request.view_args else None
    service = request.view_args.get("service") if request.view_args else None
    if cloud not in CLOUDS and service:
        cloud = service_cloud(service)
    if cloud not in CLOUDS:
        cloud = request.args.get("cloud")
    if cloud not in CLOUDS and request.endpoint in {"campaign", "execution"}:
        cloud = "aws"
    active_campaign = _current_campaign(cloud) if cloud in CLOUDS else _current_campaign()
    experiments = getattr(active_campaign, "experiments", ())
    return {
        "cloud": cloud if cloud in CLOUDS else None,
        "campaign_count": (
            sum(
                1
                for experiment in experiments
                if service_cloud(getattr(experiment, "service", "")) == cloud
            )
            if cloud in CLOUDS
            else len(experiments)
        ),
        "campaign_cloud": cloud if cloud in CLOUDS else None,
        "active_campaign_name": getattr(active_campaign, "name", "Default Campaign"),
        "active_campaign_id": getattr(active_campaign, "campaign_id", None),
        "cloud_identity": (
            get_cached_cloud_identity(cloud)
            if cloud in CLOUDS and request.endpoint != "cloud_identity"
            else None
        ),
        "current_timezone": format_timezone(),
        "current_timezone_offset": format_timezone_offset(),
        "chaosforge_version": chaosforge_version(),
    }


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------


@app.route("/")
def dashboard():
    return render_template("index.html", clouds=cloud_cards())


@app.route("/settings", methods=["GET", "POST"])
def settings():
    timezone_id = get_timezone_id()
    cloud = request.args.get("cloud")
    if cloud not in CLOUDS:
        cloud = None
    message = None
    error = None
    if request.method == "POST":
        selected = request.form.get("timezone", "")
        try:
            set_timezone_id(selected)
        except ValueError as exc:
            error = str(exc)
        else:
            timezone_id = selected
            message = f"Timezone updated to {format_timezone(timezone_id)}."
    return render_template(
        "settings.html",
        timezone_id=timezone_id,
        timezone_options=timezone_options(),
        message=message,
        error=error,
        cloud=cloud,
    ), 400 if error else 200


@app.route("/cloud/<cloud>")
def cloud_services(cloud):
    if cloud not in CLOUDS:
        return "Cloud provider not found", 404
    active_campaign = _current_campaign(cloud)
    return render_template(
        "index.html",
        clouds=cloud_cards(),
        selected_cloud=CLOUDS[cloud],
        services=service_cards(cloud),
        yaml_errors=(),
        campaign_selector_required=not getattr(active_campaign, "campaign_id", None),
        campaign_drafts=list_campaign_drafts(cloud),
        notice=(
            "Log in to " + CLOUDS[cloud]["name"] + " before viewing campaigns."
            if request.args.get("notice") == "campaign-auth-required"
            else None
        ),
    )


@app.route("/api/cloud-identity/<cloud>")
def cloud_identity(cloud):
    if cloud not in CLOUDS:
        return jsonify({"error": "Cloud provider not found"}), 404
    return jsonify(get_cloud_identity(cloud))


@app.route("/cloud/<cloud>/campaign-yaml/review", methods=["POST"])
def review_campaign_yaml(cloud):
    if cloud not in CLOUDS:
        return "Cloud provider not found", 404
    identity = get_cloud_identity(cloud, refresh=True)
    if not identity["authenticated"]:
        return render_template(
            "index.html",
            clouds=cloud_cards(),
            selected_cloud=CLOUDS[cloud],
            services=service_cards(cloud),
            yaml_errors=(f"Log in to {CLOUDS[cloud]['name']} before uploading a campaign.",),
        ), 401
    upload = request.files.get("campaign_yaml")
    if upload is None or not upload.filename:
        return render_template(
            "index.html",
            clouds=cloud_cards(),
            selected_cloud=CLOUDS[cloud],
            services=service_cards(cloud),
            yaml_errors=("Select a .yaml or .yml campaign file.",),
        ), 400
    if not upload.filename.lower().endswith((".yaml", ".yml")):
        return render_template(
            "index.html",
            clouds=cloud_cards(),
            selected_cloud=CLOUDS[cloud],
            services=service_cards(cloud),
            yaml_errors=("Campaign file must use the .yaml or .yml extension.",),
        ), 400

    content = upload.stream.read(MAX_CAMPAIGN_YAML_BYTES + 1)
    review = yaml_service.inspect_bytes(
        content,
        source_name=upload.filename,
        expected_provider=cloud,
    )
    if not review.valid:
        return render_template(
            "index.html",
            clouds=cloud_cards(),
            selected_cloud=CLOUDS[cloud],
            services=service_cards(cloud),
            yaml_errors=review.errors,
        ), 400

    preflight = campaign_preflight.preflight(review.campaign, review.document, identity)
    if not preflight.ready:
        return render_template(
            "index.html",
            clouds=cloud_cards(),
            selected_cloud=CLOUDS[cloud],
            services=service_cards(cloud),
            yaml_errors=preflight.errors,
        ), 400

    campaign_name = getattr(review.campaign, "name", "")
    if not campaign_name:
        return render_template(
            "index.html", clouds=cloud_cards(), selected_cloud=CLOUDS[cloud], services=service_cards(cloud),
            yaml_errors=("Campaign name is required.",),
        ), 400
    try:
        draft = create_campaign_draft(campaign_name, cloud)
    except ValueError as exc:
        return render_template(
            "index.html", clouds=cloud_cards(), selected_cloud=CLOUDS[cloud], services=service_cards(cloud),
            yaml_errors=(str(exc),),
        ), 400
    review.campaign.campaign_id = draft.campaign_id
    review.campaign.created_at = draft.created_at
    review.campaign.updated_at = draft.updated_at
    replace_campaign(review.campaign, cloud)
    return _azure_campaign_redirect() if cloud == "azure" else _aws_campaign_redirect()


@app.route("/campaign/export-yaml")
def export_campaign_yaml():
    cloud = request.args.get("cloud")
    active_campaign = _current_campaign(cloud)
    if not active_campaign.experiments:
        return "Campaign is empty.", 400
    active_campaign.report_timezone = get_timezone_id()
    content = yaml_service.export_bytes(
        active_campaign,
        environment=_campaign_environment(active_campaign),
    )
    safe_name = _safe_download_name(active_campaign.name)
    filename = f"{safe_name or 'chaosforge-campaign'}.yaml"
    return Response(
        content,
        mimetype="application/yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _campaign_environment(campaign):
    identity = get_cloud_identity(campaign.cloud_provider, refresh=True)
    if campaign.cloud_provider == "aws":
        return {
            "account_id": identity.get("account_id", ""),
            "account_alias": identity.get("name", ""),
        }
    return {
        "subscription_id": identity.get("subscription_id", ""),
        "subscription_name": identity.get("name", ""),
    }


# ------------------------------------------------------------------
# Service Page
# ------------------------------------------------------------------


@app.route("/service/<service>")
def service(service):
    metadata = load_metadata(service)

    fis_experiments = FISCatalog().get_experiments(service)

    # ----------------------------------------------------------
    # Service exists, but has no custom ChaosForge experiments
    # ----------------------------------------------------------

    if metadata is None and not fis_experiments:
        return render_template(
            "service.html",
            service={
                "service": service,
                "id": service,
                "display_name": display_name(service),
                "name": display_name(service),
                "experiments": [],
                "has_custom_experiments": False,
            },
            cloud=service_cloud(service),
        )

    if metadata is None:
        metadata = {
            "service": service,
            "display_name": display_name(service),
            "experiments": [],
        }

    metadata = _service_metadata(metadata, fis_experiments)

    # ----------------------------------------------------------
    # Service has custom ChaosForge experiments
    # ----------------------------------------------------------

    metadata["has_custom_experiments"] = True

    return render_template(
        "service.html",
        service=metadata,
        cloud=service_cloud(service),
    )


def _service_metadata(metadata, fis_experiments):
    """Present every service's native and FIS-backed execution options together."""
    merged = dict(metadata)
    service = metadata["service"]
    experiments = [
        present_experiment(service, {**experiment, "service": service})
        for experiment in metadata["experiments"]
        if not (service == "fis" and experiment.get("internal"))
    ]
    if service == "eks":
        chaos_mesh = load_metadata("chaos_mesh") or {"experiments": []}
        experiments.extend(
            present_experiment("chaos_mesh", {**experiment, "service": "chaos_mesh"})
            for experiment in chaos_mesh["experiments"]
        )
    experiments.extend(_fis_experiment_cards(service, fis_experiments))
    merged["experiments"] = experiments
    return merged


def _web_experiment_metadata(metadata, service):
    """Expose the shared AWS region control for legacy component catalogs."""
    if service_cloud(service) != "aws" or service == "fis":
        return metadata
    enriched = dict(metadata)
    enriched.setdefault("service", service)
    enriched["experiments"] = []
    for experiment in metadata["experiments"]:
        item = dict(experiment)
        inputs = [
            field
            for field in experiment.get("inputs", [])
            if not (service == "apigateway" and field.get("name") in {"region", "aws_region"})
        ]
        if service == "apigateway":
            inputs = [
                {
                    **field,
                    "label": "API Gateway" if field.get("name") == "rest_api_id" else field.get("label"),
                }
                for field in inputs
            ]
        if not any(field.get("name") == "aws_region" for field in inputs):
            inputs.append(
                {
                    "name": "aws_region",
                    "label": "AWS Region",
                    "type": "aws_region",
                    "required": True,
                    "default": AWS_REGION,
                }
            )
        item["inputs"] = inputs
        enriched["experiments"].append(item)
    return enriched


def _fis_experiment_cards(service, fis_experiments):
    return [
        present_experiment(
            "fis",
            {
                "id": "fis-create-experiment",
                "name": experiment["name"],
                "service": "fis",
                "fis_service_id": service,
                "fis_experiment_id": experiment["id"],
                "description": (
                    f"Run the AWS FIS {experiment['name'].lower()} action against "
                    f"{display_name(service)}."
                ),
            },
        )
        for experiment in fis_experiments
    ]


def _component_fis_metadata(selected, service_id, experiment_id):
    """Bind the generic FIS wrapper to the component catalog action it runs."""
    return bind_component_fis(selected, service_id, experiment_id) if service_id and experiment_id else selected


def _aws_creator_name(identity):
    """Use the AWS CLI session name instead of exposing a full principal ARN."""
    principal_arn = identity.get("principal_arn", "")
    return principal_arn.rsplit("/", 1)[-1] if principal_arn else ""


# ------------------------------------------------------------------
# Experiment Page
# ------------------------------------------------------------------


@app.route("/experiment/<service>/<experiment_id>", methods=["GET", "POST"])
def experiment(service, experiment_id, *, edit_index=None, fis_service_id=None, fis_experiment_id=None):

    metadata = load_metadata(service)

    if metadata is None:
        return "Service not found", 404

    metadata = _web_experiment_metadata(metadata, service)

    selected = next(
        (exp for exp in metadata["experiments"] if exp["id"] == experiment_id),
        None,
    )
    if service == "fis":
        fis_service_id = fis_service_id or request.args.get("fis_service_id")
        fis_experiment_id = fis_experiment_id or request.args.get("fis_experiment_id")

    # ----------------------------------------------------------
    # Validate experiment
    # ----------------------------------------------------------

    if selected is None:
        return "Experiment not found", 404

    description = get_experiment_description(
        service,
        experiment_id,
    )

    # ----------------------------------------------------------
    # Build IAM Policy JSON
    # ----------------------------------------------------------

    iam_policy = None
    iam_policy_json = None

    if "iam" in selected:
        actions = iam_actions(selected)

        iam_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": f"{service.title()}Permissions",
                    "Effect": "Allow",
                    "Action": actions,
                    "Resource": "*",
                }
            ],
        }

        iam_policy_json = json.dumps(iam_policy, indent=4)

    lambda_execution_policy_json = None

    fis_services = []
    fis_experiments = []
    resources = []

    discovered_resources = []

    selected_service = fis_service_id
    azure_identity = get_cloud_identity("azure") if service_cloud(service) == "azure" else None
    active_campaign = _current_campaign(service_cloud(service))
    campaign_assignment = (
        edit_index is None
        and hasattr(active_campaign, "campaign_id")
        and not active_campaign.campaign_id
        and not getattr(active_campaign, "experiments", [])
    )
    campaign_drafts = list_campaign_drafts(service_cloud(service)) if campaign_assignment else []
    if edit_index is None:
        edit_index = request.args.get("edit_index", type=int)

    # ----------------------------------------------------------
    # Generic AWS Resource Discovery
    # ----------------------------------------------------------

    region = "eu-central-1"

    for item in selected.get("inputs", []):
        if item["name"] == "aws_region":
            region = item.get("default", "eu-central-1")

    discovery = AWSDiscovery(region)

    service_mapping = {
        "lambda": "lambda",
        "dynamodb": "dynamodb",
        "rds": "rds",
        "elasticache": "elasticache",
        "apigateway": "apigateway",
        "ec2": "ec2",
        "sns": "sns",
        "s3": "s3",
    }

    if service in service_mapping:
        discovered_resources = []

        for item in selected.get("inputs", []):
            if item.get("type") != "aws_resource":
                continue

            if item.get("parent"):
                continue

            try:
                discovered_resources = discovery.discover(item["resource_type"])

                break

            except Exception as ex:  # noqa: BLE001
                print(ex)

    if service == "fis":
        catalog = FISCatalog()

        fis_services = catalog.get_services()
        selected_service = selected_service or request.args.get("fis_service_id")
        selected_experiment = fis_experiment_id or request.args.get("fis_experiment_id")
        selected = _component_fis_metadata(
            selected,
            selected_service,
            selected_experiment,
        )
        if selected.get("fis_service_id"):
            try:
                discovered_resources = discovery.discover(
                    selected.get("fis_target_selector", selected["fis_service_id"])
                )
            except Exception as ex:  # noqa: BLE001
                print(ex)
                discovered_resources = []
        if selected.get("fis_service_id"):
            aws_identity = get_cloud_identity("aws", region, refresh=True)
            for input_field in selected["inputs"]:
                if input_field["name"] == "created_by":
                    input_field["default"] = _aws_creator_name(aws_identity) or "AWS CLI identity required"
                    break

    if service == "fis" and selected_service == "lambda":
        bucket_name = request.form.get("fis_config_bucket", "your_s3_bucket")
        iam_policy["Statement"].append(
            {"Sid": "LambdaFISConfigurationWrite", **fis_s3_policy(bucket_name)["Statement"][0]}
        )
        iam_policy_json = json.dumps(iam_policy, indent=4)
        lambda_execution_policy_json = json.dumps(lambda_s3_policy(bucket_name), indent=4)

    form_query = {"edit_index": edit_index} if edit_index is not None else {}
    if service == "fis" and selected_service and selected_experiment:
        form_query.update(
            fis_service_id=selected_service,
            fis_experiment_id=selected_experiment,
        )
    form_action = url_for("experiment", service=service, experiment_id=experiment_id, **form_query)
    cancel_service = service
    if service == "fis" and selected_service and FISCatalog().get_service(selected_service):
        cancel_service = selected_service
    cancel_url = url_for("service", service=cancel_service)
    campaign_library_url = url_for(
        "campaigns",
        cloud=service_cloud(service),
        return_service=service,
        return_experiment=experiment_id,
        **({"return_edit_index": edit_index} if edit_index is not None else {}),
    )

    if request.method == "POST":
        cloud = service_cloud(service)
        #
        # Step 1
        #
        if service == "fis" and "load_service" in request.form:
            selected_service = request.form.get("service_id")

            catalog = FISCatalog()

            fis_experiments = catalog.get_experiments(selected_service)

            selector = ResourceSelector(request.form.get("aws_region", "eu-central-1"))

            resources = selector.get_resources(selected_service)

            return render_template(
                "experiment.html",
                service=metadata,
                experiment=selected,
                fis_services=fis_services,
                fis_experiments=fis_experiments,
                resources=resources,
                selected_service=selected_service,
                discovered_resources=discovered_resources,
                iam_policy=iam_policy,
                iam_policy_json=iam_policy_json,
                description=description,
                regions=RegionSelector.REGIONS,
                cloud=service_cloud(service),
                azure_identity=azure_identity,
            form_action=form_action,
            cancel_url=cancel_url,
            campaign_assignment=campaign_assignment,
            campaign_drafts=campaign_drafts,
            campaign_library_url=campaign_library_url,
        )

        #
        # Step 2
        #

        values, errors = normalize_values(
            selected.get("inputs", []),
            request.form.to_dict(flat=True),
        )
        if errors:
            return render_template(
                "experiment.html",
                service=metadata,
                experiment=selected,
                fis_services=fis_services,
                fis_experiments=fis_experiments,
                resources=resources,
                selected_service=selected_service,
                discovered_resources=discovered_resources,
                iam_policy=iam_policy,
                iam_policy_json=iam_policy_json,
                form=request.form,
                errors=errors,
                description=description,
                regions=RegionSelector.REGIONS,
                cloud=service_cloud(service),
                azure_identity=azure_identity,
                form_action=form_action,
                cancel_url=cancel_url,
            ), 400

        if service == "fis" and selected.get("fis_service_id"):
            values["service_id"] = selected["fis_service_id"]
            values["experiment_id"] = selected["fis_experiment_id"]
            if selected["fis_service_id"]:
                identity = get_cloud_identity("aws", values.get("aws_region", AWS_REGION), refresh=True)
                values["created_by"] = _aws_creator_name(identity)
                if not values["created_by"]:
                    errors = {"created_by": "Log in with the AWS CLI before adding this experiment."}
                    return render_template(
                        "experiment.html",
                        service=metadata,
                        experiment=selected,
                        fis_services=fis_services,
                        fis_experiments=fis_experiments,
                        resources=resources,
                        selected_service=selected_service,
                        discovered_resources=discovered_resources,
                        iam_policy=iam_policy,
                        iam_policy_json=iam_policy_json,
                        form=request.form,
                        errors=errors,
                        description=description,
                        regions=RegionSelector.REGIONS,
                        cloud=service_cloud(service),
                        azure_identity=azure_identity,
                        form_action=form_action,
                        cancel_url=cancel_url,
                    ), 400
            prepare_component_fis_variables(values)

        if service == "chaos_mesh" and is_workload_experiment(selected.get("id")):
            eks_discovery = AWSDiscovery(values["aws_region"])
            if values["target_mode"] == "pod":
                values["mode"] = "one"
                values.update(
                    eks_discovery.get_eks_pod_context(
                        values["eks_cluster"], values["namespace"], values["pod"]
                    )
                )
            else:
                values.update(
                    eks_discovery.get_eks_deployment_context(
                        values["eks_cluster"], values["namespace"], values["deployment"]
                    )
                )
                values["owning_deployment"] = values["deployment"]

        if service in AZURE_SERVICES:
            values["subscription_id"] = (
                azure_identity.get("subscription_id", "")
                if azure_identity and azure_identity.get("authenticated")
                else request.form.get("subscription_id", "")
            )
            values["resource_group"] = request.form.get("resource_group", "")
        if service == "aks":
            values["aks_name"] = values.get("aks_context", "")
            aks_discovery = None

            def get_aks_discovery():
                nonlocal aks_discovery
                if aks_discovery is None:
                    aks_discovery = AzureAKSDiscovery()
                return aks_discovery

            if selected.get("id") == "aks-node-zone-failure":
                zone = values.get("target_zone", "")
                context_name = values.get("aks_context", "")
                zone_nodes = get_aks_discovery().list_nodes_in_zone(context_name, zone)
                if not zone_nodes:
                    errors = {
                        "target_zone": (
                            f"No worker nodes were found in availability zone '{zone}'. "
                            "Select another zone and try again."
                        )
                    }
                    return render_template(
                        "experiment.html",
                        service=metadata,
                        experiment=selected,
                        fis_services=fis_services,
                        fis_experiments=fis_experiments,
                        resources=resources,
                        selected_service=selected_service,
                        discovered_resources=discovered_resources,
                        iam_policy=iam_policy,
                        iam_policy_json=iam_policy_json,
                        form=request.form,
                        errors=errors,
                        description=description,
                        regions=RegionSelector.REGIONS,
                        cloud=service_cloud(service),
                        azure_identity=azure_identity,
                    ), 400
                values["target_node"] = ",".join(zone_nodes)

            if values.get("target_mode") == "pod":
                pod = values["pod"]
                label_key, label_val = get_aks_discovery().get_pod_label(
                    values["aks_context"], values["namespace"], pod
                )
                values["deployment"] = pod
                values["label_key"] = label_key
                values["label_val"] = label_val
                values["owning_deployment"] = (
                    get_aks_discovery().get_deployment_for_pod(
                        values["aks_context"], values["namespace"], pod
                    )
                    or ""
                )
                values["chaos_mode"] = "one"
                values["chaos_value"] = ""

            deployment = values.get("deployment")
            if (
                deployment
                and values.get("target_mode") != "pod"
                and values.get("aks_context")
                and values.get("namespace")
            ):
                label_key, label_val = get_aks_discovery().get_label_selector(
                    values["aks_context"], values["namespace"], deployment
                )
                values["label_key"] = label_key
                values["label_val"] = label_val
                if values.get("chaos_mode") == "fixed":
                    pod_count = get_aks_discovery().get_pod_count(
                        values["aks_context"], values["namespace"], label_key, label_val
                    )
                    requested_count = int(values["chaos_value"])
                    if pod_count and requested_count > pod_count:
                        errors = {
                            "chaos_value": (
                                f"Mode Value cannot exceed the matching pod count ({pod_count})."
                            )
                        }
                        return render_template(
                            "experiment.html",
                            service=metadata,
                            experiment=selected,
                            fis_services=fis_services,
                            fis_experiments=fis_experiments,
                            resources=resources,
                            selected_service=selected_service,
                            discovered_resources=discovered_resources,
                            iam_policy=iam_policy,
                            iam_policy_json=iam_policy_json,
                            form=request.form,
                            errors=errors,
                            description=description,
                            regions=RegionSelector.REGIONS,
                            cloud=service_cloud(service),
                            azure_identity=azure_identity,
                            form_action=form_action,
                            cancel_url=cancel_url,
                            campaign_assignment=campaign_assignment,
                            campaign_drafts=campaign_drafts,
                            campaign_library_url=campaign_library_url,
                        ), 400

        # ----------------------------------------------------------
        # EC2 -> EBS Volume
        # Automatically preserve the attached device name
        # ----------------------------------------------------------

        if service == "ec2" and selected.get("id") == "ec2-ebs-volume-detach":
            instance_id = values.get("instance_id")
            volume_id = values.get("volume_id")
            aws_region = values.get("aws_region") or "eu-central-1"

            if instance_id and volume_id:
                selector = ResourceSelector(aws_region)

                volumes = selector.discovery.list_ec2_ebs_volumes(instance_id)

                selected_volume = next(
                    (volume for volume in volumes if volume.get("id") == volume_id),
                    None,
                )

                if selected_volume:
                    device_name = selected_volume.get("device_name")

                    if device_name:
                        values["device_name"] = device_name

        if edit_index is None:
            if campaign_assignment:
                campaign_id = request.form.get("campaign_id", "").strip()
                campaign_name = request.form.get("new_campaign_name", "").strip()
                try:
                    if campaign_id:
                        open_campaign_draft(campaign_id, cloud)
                    elif campaign_name:
                        create_campaign_draft(campaign_name, cloud)
                    else:
                        raise ValueError("Choose an existing campaign or enter a new campaign name.")
                except (FileNotFoundError, ValueError) as exc:
                    return render_template(
                        "experiment.html",
                        service=metadata,
                        experiment=selected,
                        fis_services=fis_services,
                        fis_experiments=fis_experiments,
                        resources=resources,
                        selected_service=selected_service,
                        discovered_resources=discovered_resources,
                        iam_policy=iam_policy,
                        form=request.form,
                        errors={"campaign": str(exc)},
                        description=description,
                        regions=RegionSelector.REGIONS,
                        cloud=cloud,
                        azure_identity=azure_identity,
                        form_action=form_action,
                        cancel_url=url_for("campaigns", cloud=cloud),
                        campaign_assignment=True,
                        campaign_drafts=campaign_drafts,
                        campaign_library_url=campaign_library_url,
                    ), 400
            try:
                add_experiment(metadata, selected, values)
            except (OSError, RuntimeError, ValueError) as exc:
                return render_template(
                    "experiment.html",
                    service=metadata,
                    experiment=selected,
                    fis_services=fis_services,
                    fis_experiments=fis_experiments,
                    resources=resources,
                    selected_service=selected_service,
                    discovered_resources=discovered_resources,
                    iam_policy=iam_policy,
                    iam_policy_json=iam_policy_json,
                    form=request.form,
                    errors={"campaign": f"Could not add experiment to the campaign: {exc}"},
                    description=description,
                    regions=RegionSelector.REGIONS,
                    cloud=cloud,
                    azure_identity=azure_identity,
                    form_action=form_action,
                    cancel_url=cancel_url,
                    campaign_assignment=campaign_assignment,
                    campaign_drafts=campaign_drafts,
                    campaign_library_url=campaign_library_url,
                ), 400
        else:
            updated_experiment = create_experiment(
                metadata["service"],
                selected,
                values,
                default_region=AWS_REGION,
            )
            if service_cloud(service) == "azure":
                update_experiment(edit_index, updated_experiment, "azure")
            else:
                update_experiment(edit_index, updated_experiment)

        return (
            _azure_campaign_redirect()
            if service_cloud(service) == "azure"
            else _aws_campaign_redirect()
        )

    return render_template(
        "experiment.html",
        service=metadata,
        experiment=selected,
        fis_services=fis_services,
        fis_experiments=fis_experiments,
        resources=resources,
        selected_service=selected_service,
        selected_fis_experiment=selected_experiment if service == "fis" else None,
        discovered_resources=discovered_resources,
        iam_policy=iam_policy,
        iam_policy_json=iam_policy_json,
        lambda_execution_policy_json=lambda_execution_policy_json,
        form=(
            _edit_experiment(edit_index, service_cloud(service)).variables
            if edit_index is not None
            else request.form
        ),
        description=description,
        regions=RegionSelector.REGIONS,
        cloud=service_cloud(service),
        azure_identity=azure_identity,
        form_action=form_action,
        cancel_url=cancel_url,
        campaign_assignment=campaign_assignment,
        campaign_drafts=campaign_drafts,
        campaign_library_url=campaign_library_url,
    )


# ------------------------------------------------------------------
# FIS API - Experiments
# ------------------------------------------------------------------


@app.route("/api/azure/resource-groups/<subscription_id>")
def azure_resource_groups(subscription_id):
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    try:
        return jsonify(AzureResourceDiscovery(subscription_id).list_resource_groups())
    except (ImportError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/azure/redis/caches/<subscription_id>/<resource_group>")
def azure_redis_caches(subscription_id, resource_group):
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    try:
        return jsonify(AzureResourceDiscovery(subscription_id).list_redis_caches(resource_group))
    except (ImportError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/azure/redis/chaos-identities/<subscription_id>")
def azure_redis_chaos_identities(subscription_id):
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    try:
        from azure.identity import DefaultAzureCredential

        return jsonify(
            AzureRedisChaosIdentityService(subscription_id, DefaultAzureCredential()).list_identities()
        )
    except (ImportError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/azure/redis/chaos-identities/<subscription_id>/bootstrap")
def bootstrap_azure_redis_chaos_identity(subscription_id):
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    payload = request.get_json(silent=True) or {}
    resource_group = str(payload.get("resource_group", "")).strip()
    redis_name = str(payload.get("redis_name", "")).strip()
    if not resource_group or not redis_name:
        return jsonify({"error": "resource_group and redis_name are required."}), 400
    try:
        from azure.identity import DefaultAzureCredential

        service = AzureRedisChaosIdentityService(subscription_id, DefaultAzureCredential())
        readiness = service.bootstrap(
            resource_group,
            redis_target_id(subscription_id, resource_group, _redis_cache_name(redis_name)),
        )
        if readiness.get("status") == "ready":
            outcome = {
                "identity_created": readiness.get("identity_created", service.last_bootstrap_outcome["identity_created"]),
                "role_assigned": readiness.get("role_assigned", service.last_bootstrap_outcome["role_assigned"]),
            }
            if outcome["identity_created"]:
                readiness["message"] = "Created chaosforge-managed-identity and confirmed Redis Cache Contributor."
            elif outcome["role_assigned"]:
                readiness["message"] = "Granted Redis Cache Contributor to chaosforge-managed-identity."
            else:
                readiness["message"] = "chaosforge-managed-identity already has Redis Cache Contributor on this cache."
        return jsonify(readiness)
    except Exception as exc:  # noqa: BLE001 - Azure RBAC errors vary by tenant.
        return jsonify(
            {
                "error": (
                    "Could not set up chaosforge-managed-identity. The operator needs Managed "
                    "Identity Contributor on the identity resource group and Owner or User Access "
                    f"Administrator on the selected Redis cache. {exc}"
                )
            }
        ), 400


@app.post("/api/azure/components/<service>/resources/<subscription_id>")
def azure_component_resources(service, subscription_id):
    if service not in AZURE_COMPONENT_PACKAGES:
        return jsonify({"error": "Unsupported Azure component."}), 404
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    resource_group = str((request.get_json(silent=True) or {}).get("resource_group", "")).strip()
    try:
        return jsonify(list_component_resources(AzureResourceDiscovery(subscription_id), service, resource_group))
    except (ImportError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/azure/components/azure_vmss/instances/<subscription_id>")
def azure_vmss_instances(subscription_id):
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    payload = request.get_json(silent=True) or {}
    resource_group = str(payload.get("resource_group", "")).strip()
    resource_id = str(payload.get("resource_id", "")).rstrip("/")
    scale_set_name = resource_id.rsplit("/", 1)[-1]
    try:
        return jsonify(
            AzureResourceDiscovery(subscription_id).list_virtual_machine_scale_set_instances(
                resource_group, scale_set_name
            )
        )
    except (ImportError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/azure/components/<service>/chaos-identities/<subscription_id>", methods=["GET", "POST"])
def azure_component_chaos_identities(service, subscription_id):
    if service not in AZURE_COMPONENT_PACKAGES:
        return jsonify({"error": "Unsupported Azure component."}), 404
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    try:
        from azure.identity import DefaultAzureCredential

        identity_service = AzureChaosIdentityService(subscription_id, DefaultAzureCredential())
        identities = identity_service.list_identities()
        requested_id = str((request.get_json(silent=True) or {}).get("identity_id", "")).strip()
        if requested_id and all(item["id"].casefold() != requested_id.casefold() for item in identities):
            identities.append(identity_service.get_identity(requested_id))
        return jsonify(identities)
    except (ImportError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/azure/components/<service>/chaos-identities/<subscription_id>/bootstrap")
def bootstrap_azure_component_chaos_identity(service, subscription_id):
    identity = get_cloud_identity("azure", refresh=True)
    if not identity.get("authenticated") or identity.get("subscription_id") != subscription_id:
        return jsonify({"error": "Log in to the selected Azure subscription first."}), 401
    payload = request.get_json(silent=True) or {}
    resource_group = str(payload.get("resource_group", "")).strip()
    target_id = str(payload.get("resource_id", "")).strip()
    experiment_id = str(payload.get("experiment_id", "")).strip()
    if not resource_group or not target_id or not experiment_id:
        return jsonify({"error": "resource_group, resource_id, and experiment_id are required."}), 400
    try:
        _urn, _target, role_name = fault_details(service, experiment_id)
        from azure.identity import DefaultAzureCredential

        service_identity = AzureChaosIdentityService(subscription_id, DefaultAzureCredential())
        readiness = service_identity.bootstrap(resource_group, target_id, role_name)
        if readiness.get("status") == "ready":
            outcome = service_identity.last_bootstrap_outcome
            if outcome["identity_created"]:
                readiness["message"] = f"Created chaosforge-managed-identity and confirmed {role_name}."
            elif outcome["role_assigned"]:
                readiness["message"] = f"Granted {role_name} to chaosforge-managed-identity."
            else:
                readiness["message"] = f"chaosforge-managed-identity already has {role_name} on this target."
        return jsonify(readiness)
    except Exception as exc:  # noqa: BLE001 - Azure RBAC errors vary by tenant.
        return jsonify({"error": f"Could not set up chaosforge-managed-identity for this target. {exc}"}), 400


@app.route("/api/fis/experiments/<service_id>")
def fis_experiments(service_id):

    catalog = FISCatalog()

    experiments = catalog.get_experiments(service_id)

    return jsonify(experiments)


# ------------------------------------------------------------------
# FIS API - Resources
# ------------------------------------------------------------------


@app.route("/api/fis/resources/<service_id>/<region>")
def fis_resources(service_id, region):

    selector = ResourceSelector(region)

    resources = selector.get_resources(service_id)

    return jsonify(resources)


@app.route("/api/fis/templates/<region>")
def fis_template_options(region):
    try:
        return jsonify(FISService(region).list_templates())
    except Exception as exc:  # noqa: BLE001 - provider credential errors vary by account.
        return jsonify({"error": str(exc)}), 400


# ------------------------------------------------------------------
# FIS API - Parameters
# ------------------------------------------------------------------


@app.route("/api/fis/parameters/<service_id>/<experiment_id>")
def fis_parameters(service_id, experiment_id):

    catalog = FISCatalog()

    experiment = catalog.get_experiment(service_id, experiment_id)

    print("=" * 80)
    print("CATALOG PARAMETERS")
    for p in experiment.get("parameters", []):
        print(p["name"])
    print("=" * 80)

    return jsonify(experiment.get("parameters", []))


# ------------------------------------------------------------------
# FIS API - Experiment Descriptions
# ------------------------------------------------------------------


@app.route("/api/fis/descriptions/<service_id>/<experiment_id>")
def fis_experiment_description(service_id, experiment_id):
    description = get_experiment_description(
        service_id,
        experiment_id,
    )

    return jsonify(description)


@app.route("/api/resources/<resource_type>/<region>")
def api_resources(resource_type, region):

    selector = ResourceSelector(region)

    resources = selector.get_resources(resource_type)

    return jsonify(resources)


@app.route("/api/resources/<parent_type>/<path:parent_id>/<child_type>/<region>")
def api_child_resources(parent_type, parent_id, child_type, region):

    selector = ResourceSelector(region)

    # ----------------------------------------------------------
    # EKS Namespace -> Deployment / Pod
    #
    # Web UI sends:
    #     cluster::namespace
    #
    # ResourceSelector expects:
    #     (cluster, namespace)
    # ----------------------------------------------------------
    if (
        parent_type == "eks-namespace"
        and child_type
        in (
            "eks-deployment",
            "eks-pod",
            "eks-container",
        )
        and "::" in parent_id
    ):
        cluster_name, namespace = parent_id.split("::", 1)

        if child_type == "eks-container":
            parent_id = (
                cluster_name,
                namespace,
                {
                    "pod": request.args.get("pod", ""),
                    "deployment": request.args.get("deployment", ""),
                },
            )
        else:
            parent_id = (
                cluster_name,
                namespace,
            )

    # ----------------------------------------------------------
    # EKS Pod -> Volume
    #
    # Web UI sends:
    #     cluster::namespace::pod
    #
    # ResourceSelector expects:
    #     (cluster, namespace, pod)
    # ----------------------------------------------------------
    elif (
        parent_type == "eks-pod"
        and child_type == "eks-volume"
        and "::" in parent_id
    ):
        cluster_name, namespace, pod_name = parent_id.split("::", 2)

        parent_id = (
            cluster_name,
            namespace,
            pod_name,
        )

    try:
        resources = selector.select_child_resources(
            parent_type,
            parent_id,
            child_type,
        )
    except (LookupError, RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify(resources)


def _azure_items(values):
    return [{"id": value, "name": value} for value in values]


@app.route("/api/azure/aks/contexts")
def azure_aks_contexts():
    return jsonify(_azure_items(AzureAKSDiscovery().list_contexts()))


@app.route("/api/azure/aks/namespaces/<path:context>")
def azure_aks_namespaces(context):
    return jsonify(_azure_items(AzureAKSDiscovery().list_namespaces(context)))


@app.route("/api/azure/aks/deployments/<path:context>/<namespace>")
def azure_aks_deployments(context, namespace):
    return jsonify(
        _azure_items(AzureAKSDiscovery().list_deployments(context, namespace))
    )


@app.route("/api/azure/aks/nodes/<path:context>")
def azure_aks_nodes(context):
    return jsonify(_azure_items(AzureAKSDiscovery().list_nodes(context)))


@app.route("/api/azure/aks/zones/<path:context>")
def azure_aks_zones(context):
    return jsonify(_azure_items(AzureAKSDiscovery().list_zones(context)))


@app.route("/api/azure/aks/containers/<path:context>/<namespace>/<deployment>")
def azure_aks_containers(context, namespace, deployment):
    return jsonify(
        _azure_items(
            AzureAKSDiscovery().list_containers(context, namespace, deployment)
        )
    )


@app.route("/api/azure/aks/resources/<resource_type>", methods=["GET", "POST"])
def azure_aks_resources(resource_type):
    discovery = AzureAKSDiscovery()
    values = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    context = values.get("context", "")
    namespace = values.get("namespace", "")
    deployment = values.get("deployment", "")
    resource_group = values.get("resource_group", "")
    subscription_id = values.get("subscription_id", "")
    if resource_type == "azure_aks_cluster":
        if not resource_group or not subscription_id:
            return jsonify([])
        cluster_names = AzureResourceDiscovery(subscription_id).list_aks_cluster_names(resource_group)
        return jsonify(_azure_items([
            context_name
            for context_name in discovery.list_contexts()
            if any(name in context_name for name in cluster_names)
        ]))
    loaders = {
        "azure_aks_namespace": lambda: discovery.list_namespaces(context),
        "azure_aks_deployment": lambda: discovery.list_deployments(context, namespace),
        "azure_aks_pod": lambda: discovery.list_pods(context, namespace),
        "azure_aks_container": lambda: discovery.list_containers(
            context, namespace, deployment
        ),
        "azure_aks_node": lambda: discovery.list_nodes(context),
        "azure_aks_zone": lambda: discovery.list_zones(context),
    }
    loader = loaders.get(resource_type)
    if loader is None:
        return jsonify({"error": "Unsupported AKS resource type"}), 400
    values = loader()
    return jsonify(_azure_items(values))


# ------------------------------------------------------------------
# Campaign Page
# ------------------------------------------------------------------


@app.route("/campaigns", methods=["GET", "POST"])
def campaigns():
    cloud = _trusted_cloud(request.args.get("cloud"))
    if not _campaign_cloud_identity(cloud):
        return _cloud_services_redirect(cloud)
    if request.method == "POST":
        try:
            create_campaign_draft(request.form.get("campaign_name", ""), cloud)
        except ValueError as exc:
            return render_template(
                "campaigns.html", cloud=cloud, cloud_identity=get_cloud_identity(cloud, refresh=True),
                campaigns=list_campaign_drafts(cloud), executions=campaign_history.list_executions(cloud), error=str(exc),
                return_target=None, return_url=None, return_cloud=None,
            ), 400
        return (
            _azure_campaign_redirect()
            if cloud == "azure"
            else _aws_campaign_redirect()
        )
    return_target = _campaign_return_target(cloud)
    return_cloud = request.args.get("return_cloud")
    return_cloud = return_cloud if return_cloud == cloud else None
    drafts = list_campaign_drafts(cloud)
    return render_template(
        "campaigns.html", cloud=cloud, cloud_identity=get_cloud_identity(cloud, refresh=True),
        campaigns=drafts, executions=campaign_history.list_executions(cloud), error=None,
        return_target=return_target, return_url=None, return_cloud=return_cloud,
    )


@app.route("/campaigns/<cloud>/<campaign_id>/open")
def open_campaign_draft_route(cloud, campaign_id):
    cloud = _trusted_cloud(cloud)
    try:
        open_campaign_draft(campaign_id, cloud)
    except (FileNotFoundError, ValueError):
        return "Campaign not found", 404
    return _azure_campaign_redirect() if cloud == "azure" else _aws_campaign_redirect()


@app.route("/campaigns/<cloud>/<campaign_id>/delete", methods=["POST"])
def delete_campaign_draft_route(cloud, campaign_id):
    cloud = _trusted_cloud(cloud)
    try:
        delete_campaign_draft(campaign_id, cloud)
    except ValueError:
        return "Campaign not found", 404
    return (
        _azure_campaign_library_redirect()
        if cloud == "azure"
        else _aws_campaign_library_redirect()
    )


@app.route("/campaign")
def campaign():
    requested_cloud = request.args.get("cloud")
    cloud = requested_cloud
    if cloud not in CLOUDS and requested_cloud is None:
        cloud = getattr(_current_campaign(), "cloud_provider", None)
    cloud = _trusted_cloud(cloud)
    cloud_identity = _campaign_cloud_identity(cloud)
    if cloud_identity is None:
        return _cloud_services_redirect(cloud, notice="campaign-auth-required")
    campaign = _current_campaign(cloud)
    if (
        hasattr(campaign, "campaign_id")
        and not campaign.campaign_id
        and not getattr(campaign, "experiments", [])
    ):
        return (
            _azure_campaign_library_redirect()
            if cloud == "azure"
            else _aws_campaign_library_redirect()
        )
    experiments = [
        (index, experiment)
        for index, experiment in enumerate(getattr(campaign, "experiments", []))
        if service_cloud(getattr(experiment, "service", "")) == cloud
    ]
    if getattr(campaign, "campaign_id", None):
        campaign_executions = _current_campaign_executions(campaign, cloud)
        execution_results = _campaign_execution_results(campaign, cloud)
    else:
        campaign_executions = _runs_since_campaign_reset(
            campaign, execution_sessions(cloud)
        )
        execution_results = {}
        for run in campaign_executions:
            for index, experiment in experiments:
                result = next(
                    (
                        item
                        for item in run.get("experiments", {}).values()
                        if item.get("service") == experiment.service
                        and item.get("experiment_id") == getattr(experiment, "id", None)
                        and item.get("target", {}) == _execution_target(experiment)
                    ),
                    None,
                )
                if result and index not in execution_results:
                    execution_results[index] = {"run_id": run["id"], **result}
    latest_execution = (
        {**campaign_executions[0], "label": _execution_label(campaign_executions[0])}
        if campaign_executions
        else None
    )
    return render_template(
        "campaign.html",
        campaign=campaign,
        cloud=cloud,
        experiments=experiments,
        cloud_identity=cloud_identity,
        execution_sessions=campaign_executions,
        latest_execution=latest_execution,
        execution_results=execution_results,
        service_display_name=display_name,
    )


# ------------------------------------------------------------------
# Edit Campaign Experiment
# ------------------------------------------------------------------


@app.route("/campaign/edit/<int:index>", methods=["GET", "POST"])
def edit_campaign(index):
    cloud = request.args.get("cloud")
    exp = get_experiment(index, cloud) if cloud else get_experiment(index)

    if exp is None:
        return "Experiment not found", 404

    metadata = load_metadata(exp.service)
    if metadata is None or not any(
        item.get("id") == exp.id for item in metadata.get("experiments", [])
    ):
        return "Experiment not found", 404

    query = {"edit_index": index}
    if exp.service == "fis":
        fis_service_id = str(exp.variables.get("service_id") or "")
        fis_experiment_id = str(exp.variables.get("experiment_id") or "")
        if not FISCatalog().get_experiment(fis_service_id, fis_experiment_id):
            return "Experiment not found", 404
        query.update(
            fis_service_id=fis_service_id,
            fis_experiment_id=fis_experiment_id,
        )
    return experiment(
        exp.service,
        exp.id,
        edit_index=index,
        fis_service_id=query.get("fis_service_id"),
        fis_experiment_id=query.get("fis_experiment_id"),
    )


# ------------------------------------------------------------------
# Remove Experiment
# ------------------------------------------------------------------


@app.route("/campaign/remove/<int:index>")
def remove(index):
    cloud = request.args.get("cloud")
    if cloud:
        remove_experiment(index, cloud)
    else:
        remove_experiment(index)
    return _azure_campaign_redirect() if cloud == "azure" else _aws_campaign_redirect()


# ------------------------------------------------------------------
# Clear Campaign
# ------------------------------------------------------------------


@app.route("/campaign/clear")
def clear():
    cloud = request.args.get("cloud")
    if cloud:
        clear_current_campaign(cloud)
    else:
        clear_current_campaign()
    return _azure_campaign_redirect() if cloud == "azure" else _aws_campaign_redirect()


@app.route("/campaign/execute-selected")
def execute_selected():
    ids = request.args.get("ids", "")
    if not ids:
        return redirect(url_for("campaign"))
    try:
        selected = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        return _aws_campaign_redirect()
    cloud = request.args.get("cloud")
    campaign_cloud = _trusted_cloud(cloud)
    review = _consume_permission_review_token(
        request.args.get("review", ""), campaign_cloud, selected
    )
    if not review:
        return _azure_campaign_redirect() if campaign_cloud == "azure" else _aws_campaign_redirect()
    campaign = _campaign_for_permission_review(campaign_cloud, selected)
    _apply_reviewed_chaos_mesh_decisions(campaign, review)
    if not campaign.experiments:
        return (
            _azure_campaign_redirect()
            if campaign.cloud_provider == "azure"
            else _aws_campaign_redirect()
        )
    if request.args.get("continue_on_failure") == "true":
        campaign.continue_on_failure = True

    run_id, conflict = _start_web_execution(campaign, _current_campaign(campaign_cloud))
    if conflict:
        return conflict

    return _azure_execution_redirect(run_id) if campaign.cloud_provider == "azure" else _aws_execution_redirect(run_id)


@app.post("/api/campaign/permissions")
def campaign_permissions():
    from chaosforge.application.safety import irreversible_experiments

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON request body is required."}), 400
    cloud = payload.get("cloud")
    if cloud not in CLOUDS:
        return jsonify({"error": "Invalid cloud provider."}), 400
    ids = payload.get("ids")
    if ids is None:
        selected = None
    elif (
        not isinstance(ids, list)
        or not ids
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in ids)
    ):
        return jsonify({"error": "Invalid experiment selection."}), 400
    else:
        selected = ids
    campaign = _campaign_for_permission_review(cloud, selected)
    if not campaign.experiments:
        return jsonify({"error": "Select at least one experiment."}), 400
    irreversible = irreversible_experiments(campaign)
    try:
        assessments = assess_campaign(campaign)
    except (OSError, RuntimeError, ValueError) as exc:
        return jsonify({"error": f"Could not inspect Chaos Mesh: {exc}"}), 409
    if blocked := next((item for item in assessments if item.blocked), None):
        return jsonify({"error": blocked.message}), 409
    saved = getattr(campaign, "chaos_mesh_version_decisions", {})
    unresolved = [
        item for item in assessments
        if item.requires_decision and not decision_is_current(saved.get(item.key), item)
    ]
    return jsonify(
        experiments=[
            {
                "service": experiment.service,
                "id": experiment.id,
                "name": experiment.name,
                "target": experiment_target(experiment),
                "fis_service_id": experiment.variables.get("service_id", "") if experiment.service == "fis" else "",
                "fis_experiment_id": experiment.variables.get("experiment_id", "") if experiment.service == "fis" else "",
            }
            for experiment in campaign.experiments
        ],
        report=permission_reports.generate(campaign),
        irreversible_experiments=[
            {"service": experiment.service, "id": experiment.id, "name": experiment.name}
            for experiment in irreversible
        ],
        chaos_mesh_versions=[
            {**item.as_dict(), "requires_decision": item.key in {entry.key for entry in unresolved}}
            for item in assessments
        ],
        review_token=_permission_review_token(
            cloud,
            selected,
            requires_irreversible_acknowledgement=bool(irreversible),
            chaos_mesh_assessments=assessments,
            chaos_mesh_required_keys=[item.key for item in unresolved],
        ),
    )


@app.route("/api/campaign/permissions/confirm", methods=["POST"])
def confirm_campaign_permissions():
    payload = request.get_json(silent=True) or {}
    token = payload.get("review_token")
    if not isinstance(token, str) or not _confirm_permission_review_token(
        token,
        irreversible_acknowledged=payload.get("irreversible_acknowledged") is True,
        chaos_mesh_decisions=payload.get("chaos_mesh_decisions"),
    ):
        return jsonify({"error": "Permission review has expired."}), 400
    review = permission_review_tokens[token]
    if review.get("chaos_mesh_decisions"):
        current = _current_campaign(review["cloud"])
        decisions = dict(getattr(current, "chaos_mesh_version_decisions", {}))
        decisions.update(review["chaos_mesh_decisions"])
        save_chaos_mesh_version_decisions(decisions, review["cloud"])
    return jsonify({"confirmed": True})


# ------------------------------------------------------------------
# Execute Campaign
# ------------------------------------------------------------------


@app.route("/campaign/execute")
def execute():
    requested_cloud = request.args.get("cloud")
    current_campaign = _current_campaign(requested_cloud)
    current_cloud = getattr(current_campaign, "cloud_provider", "")
    cloud = _trusted_cloud(requested_cloud if requested_cloud in CLOUDS else current_cloud)
    review = _consume_permission_review_token(request.args.get("review", ""), cloud, None)
    if not review:
        return _azure_campaign_redirect() if cloud == "azure" else _aws_campaign_redirect()
    execution_campaign = _campaign_for_permission_review(cloud)
    _apply_reviewed_chaos_mesh_decisions(execution_campaign, review)
    if not execution_campaign.experiments:
        return _azure_campaign_redirect() if cloud == "azure" else _aws_campaign_redirect()
    run_id, conflict = _start_web_execution(execution_campaign, current_campaign)
    if conflict:
        return conflict

    return _azure_execution_redirect(run_id) if cloud == "azure" else _aws_execution_redirect(run_id)


# ------------------------------------------------------------------
# Execution Console
# ------------------------------------------------------------------


@app.route("/execution")
def execution():
    cloud = request.args.get("cloud")
    cloud = cloud if cloud in CLOUDS else "aws"
    cloud_identity = get_cloud_identity(cloud, refresh=True)
    run_id = request.args.get("run")
    if not run_id:
        sessions = execution_sessions(cloud)
        run_id = sessions[0]["id"] if sessions else None
    session = execution_session(cloud, run_id) if run_id else None
    session = session or _execution_record(cloud, run_id)
    return render_template(
        "execution.html", cloud=cloud, cloud_identity=cloud_identity, run_id=run_id, session=session
    )


@app.route("/execution/logs")
def execution_logs():
    cloud = request.args.get("cloud")
    run_id = request.args.get("run")
    session = execution_session(cloud, run_id)
    if session:
        if session.get("completed_at"):
            return jsonify(session["logs"])
        return jsonify(get_log_manager(cloud).get_logs())
    if record := _execution_record(cloud, run_id):
        return jsonify(record.get("logs", []))
    return jsonify(get_log_manager(cloud).get_logs())


@app.route("/progress")
def progress():
    cloud = request.args.get("cloud")
    run_id = request.args.get("run")
    session = execution_session(cloud, run_id)
    if session:
        if session.get("completed_at"):
            return jsonify(session["progress"])
    elif record := _execution_record(cloud, run_id):
        return jsonify(_execution_progress(record))
    log_manager = get_log_manager(cloud)
    return jsonify(
        {
            "current": log_manager.current,
            "total": log_manager.total,
            "experiment": log_manager.current_experiment,
            "running": log_manager.running,
            "finished": log_manager.finished,
        }
    )

@app.route("/api/execution/status")
def execution_status():
    cloud = request.args.get("cloud", "aws")
    run_id = request.args.get("run", "").strip()

    if cloud not in CLOUDS:
        return jsonify({"error": "Invalid cloud provider."}), 400

    if not run_id:
        return jsonify({"error": "Execution run ID is required."}), 400

    session = execution_session(cloud, run_id) or _execution_record(cloud, run_id)
    if session is None:
        return jsonify({"error": "Execution session not found."}), 404

    return jsonify({
        "run_id": session["id"],
        "status": session["status"],
        "completed": bool(session["completed_at"]),
        "completed_at": session["completed_at"],
        "progress": session.get("progress", {}),
        "experiments": session.get("experiments", {}),
    })

@app.route("/download_logs")
def download_logs():
    cloud = request.args.get("cloud")
    run_id = request.args.get("run")
    if session := execution_session(cloud, run_id):
        lines = session.get("logs", []) if session.get("completed_at") else get_log_manager(cloud).get_logs()
    elif record := _execution_record(cloud, run_id):
        lines = record.get("logs", [])
    else:
        lines = get_log_manager(cloud).lines
    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=campaign.log"},
    )


@app.route("/report/download")
def download_report():
    record = _execution_record(request.args.get("cloud"), request.args.get("run"))
    report_path = _approved_report_path(record.get("report_path")) if record else None
    reports = [report_path] if report_path else sorted(
        _approved_report_paths(), key=lambda path: path.stat().st_mtime, reverse=True
    )

    if not reports:
        return "Report not found.", 404

    latest_report = reports[0]

    print("Downloading:", latest_report)

    return send_file(
        latest_report,
        as_attachment=True,
        download_name=latest_report.name,
        mimetype="text/plain",
    )


# ------------------------------------------------------------------
# Start Flask
# ------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
