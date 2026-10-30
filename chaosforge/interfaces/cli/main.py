import argparse
import os
import re
import sys
from copy import deepcopy
from pathlib import Path

from rich.table import Table

from chaosforge.application.campaigns.factory import create_experiment
from chaosforge.application.campaigns.manager import (
    campaign,
    clear,
    get_campaign,
    list_all,
    remove,
    replace_campaign,
    update,
)
from chaosforge.application.campaigns.yaml_builder import build_campaign
from chaosforge.application.campaigns.yaml_loader import load_yaml
from chaosforge.application.discovery import discover_services, display_name
from chaosforge.application.safety import irreversible_experiments
from chaosforge.application.services.campaign_preflight import CampaignPreflightService
from chaosforge.application.services.campaign_service import (
    create_campaign_draft,
    delete_campaign_draft,
    list_campaign_drafts,
    list_saved_campaigns,
    load_saved_campaign,
    open_campaign_draft,
    save_chaos_mesh_version_decisions,
)
from chaosforge.application.services.campaign_yaml import CampaignYAMLService
from chaosforge.application.services.cloud_identity import get_cloud_identity
from chaosforge.application.services.experiment_validation import (
    ExperimentValidationService,
)
from chaosforge.application.services.permissions import PermissionReportService
from chaosforge.application.services.planning import PlanService
from chaosforge.application.services.user_settings import (
    format_timezone,
    get_timezone_id,
    set_timezone_id,
    timezone_options,
)
from chaosforge.application.validation.yaml import YAMLValidator
from chaosforge.common.console_encoding import configure_windows_output
from chaosforge.common.version import chaosforge_version
from chaosforge.engines.chaos_mesh.version_policy import (
    apply_execution_actions,
    assess_campaign,
    decision_is_current,
    saved_decision,
)
from chaosforge.engines.chaos_toolkit.runner import ExperimentRunner
from chaosforge.interfaces.cli.interactive.azure_aks_menu import aks_experiment_menu
from chaosforge.interfaces.cli.interactive.azure_component_menu import (
    azure_component_experiment_menu,
)
from chaosforge.interfaces.cli.interactive.azure_redis_menu import redis_experiment_menu
from chaosforge.interfaces.cli.interactive.menu_flat import experiment_menu
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.platform_selector import PlatformSelector
from chaosforge.interfaces.cli.interactive.region_selector import RegionSelector
from chaosforge.interfaces.cli.interactive.ui.banner import print_banner
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.dashboard import dashboard
from chaosforge.interfaces.cli.interactive.ui.menu_renderer import render_main_menu
from chaosforge.interfaces.cli.interactive.ui.panels import title
from chaosforge.interfaces.cli.interactive.ui.prompts import pause, prompt
from chaosforge.interfaces.cli.interactive.ui.status import (
    error,
    info,
    success,
    warning,
)
from chaosforge.interfaces.cli.interactive.ui.tables import menu
from chaosforge.interfaces.cli.session import context

configure_windows_output()
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.models import Campaign
from chaosforge.providers.aws.discovery import AWSDiscovery
from chaosforge.reporting.junit import (
    generate_junit_report,
    generate_setup_failure_report,
)
from chaosforge.reporting.report_generator import generate_report
from chaosforge.storage.campaign_history import CampaignHistoryStore

runner = ExperimentRunner()

check_resolver = CheckResolver()

from chaosforge.application.services.lifecycle_execution import LifecycleExecutionService

lifecycle_service = LifecycleExecutionService(runner, check_resolver)
campaign_yaml_service = CampaignYAMLService()
campaign_preflight = CampaignPreflightService()
campaign_history = CampaignHistoryStore()
permission_reports = PermissionReportService()


def _active_campaign():
    """Return the campaign for the cloud selected in the interactive session."""
    return get_campaign("azure") if context.cloud == "azure" else campaign


def _active_experiments():
    return list_all("azure") if context.cloud == "azure" else list_all()


def _active_campaign_name():
    campaign = _active_campaign()
    return campaign.name if getattr(campaign, "campaign_id", None) else "No active campaign"


def create_lifecycle_runner(experiment):
    return lifecycle_service.create_runner(experiment)


def execute_lifecycle_experiment(experiment):
    lifecycle_execution_runner = create_lifecycle_runner(experiment)

    return lifecycle_execution_runner.execute(experiment)


def execute_lifecycle_campaign(campaign):
    return lifecycle_service.execute_campaign(campaign)

def load_and_validate_yaml_campaign(file_path):
    """
    Load and validate a YAML campaign.

    Validation order:
        1. YAML schema validation
        2. Campaign/experiment validation
        3. Cloud credential verification

    No chaos experiment or resource mutation is performed.

    Returns:
        Campaign object when validation succeeds.
        None when validation fails.
    """

    print()
    print("=" * 70)
    print("YAML Validation Mode")
    print("=" * 70)

    try:
        # ------------------------------------------------------
        # 1. YAML schema validation
        # ------------------------------------------------------

        data = load_yaml(file_path)

        yaml_result = YAMLValidator().validate(data)

        if not yaml_result["valid"]:
            print()
            error("YAML SCHEMA VALIDATION FAILED")

            for validation_error in yaml_result["errors"]:
                print(f"  - {validation_error}")

            return None

        # ------------------------------------------------------
        # 2. Campaign / experiment validation
        # ------------------------------------------------------

        yaml_campaign = build_campaign(data)

        validation_service = ExperimentValidationService()

        validation_result = validation_service.validate_campaign(
            yaml_campaign
        )

        if not validation_result["valid"]:
            print()
            error("CAMPAIGN VALIDATION FAILED")

            for experiment in validation_result["experiments"]:
                print()
                print(
                    f"Experiment : {experiment['experiment_id']}"
                )
                print(
                    f"Service    : {experiment['service']}"
                )
                print(
                    f"Name       : {experiment['name']}"
                )

                if experiment["errors"]:
                    print()
                    print("Errors:")

                    for validation_error in experiment["errors"]:
                        print(
                            f"  - {validation_error}"
                        )

                if experiment["warnings"]:
                    print()
                    print("Warnings:")

                    for warning in experiment["warnings"]:
                        print(
                            f"  - {warning}"
                        )

            return None

        print()
        success("CAMPAIGN VALIDATION PASSED")

        for experiment in validation_result["experiments"]:
            print()
            print(
                f"Experiment : {experiment['experiment_id']}"
            )
            print(
                f"Service    : {experiment['service']}"
            )
            print(
                f"Name       : {experiment['name']}"
            )
            print("Status     : VALID")

        # ------------------------------------------------------
        # 3. Cloud credential verification
        # ------------------------------------------------------

        cloud_provider = data.get("cloud", {}).get(
            "provider",
            "aws",
        ).lower()
        yaml_campaign.cloud_provider = cloud_provider

        if cloud_provider == "aws":
            aws_regions = {
                experiment.variables.get("aws_region")
                for experiment in yaml_campaign.experiments
                if experiment.variables.get("aws_region")
            }

            if not aws_regions:
                print()
                error("AWS CREDENTIAL VERIFICATION FAILED")
                print("  - No aws_region found in the campaign.")
                return None

            for aws_region in sorted(aws_regions):
                print()
                print(
                    f"Verifying AWS credentials "
                    f"(region: {aws_region})..."
                )

                discovery = AWSDiscovery(aws_region)

                try:
                    identity = discovery.verify_aws_credentials()

                except RuntimeError as exc:
                    print()
                    error("AWS CREDENTIAL VERIFICATION FAILED")
                    print(f"  - {exc}")
                    return None

                print()
                success("AWS CREDENTIAL VERIFICATION PASSED")
                print(
                    f"  Account : {identity['account_id']}"
                )
                print(
                    f"  Region  : {identity['region']}"
                )

            if "environment" in data or data.get("template"):
                preflight = campaign_preflight.preflight(
                    yaml_campaign,
                    data,
                    identity,
                )
                if not preflight.ready:
                    print()
                    error("CAMPAIGN TARGET PREFLIGHT FAILED")
                    for message in preflight.errors:
                        print(f"  - {message}")
                    return None

        elif cloud_provider == "azure":
            print()
            identity = get_cloud_identity("azure", refresh=True)
            if not identity.get("authenticated"):
                error("AZURE CREDENTIAL VERIFICATION FAILED")
                print("  - Azure authentication failed. Run 'az login'.")
                return None
            print("Azure credential verification passed")
            print(f"  Subscription : {identity['name']}")
            preflight = campaign_preflight.preflight(yaml_campaign, data, identity)
            if not preflight.ready:
                print()
                error("CAMPAIGN TARGET PREFLIGHT FAILED")
                for message in preflight.errors:
                    print(f"  - {message}")
                return None

        else:
            print()
            error(
                f"Unsupported cloud provider: {cloud_provider}"
            )
            return None

        print()
        success("VALIDATION PASSED")

        return yaml_campaign

    except Exception as exc:  # noqa: BLE001
        error(f"Validation error: {exc}")
        return None

def confirm_campaign_execution():
    """
    Ask the user whether to execute the planned campaign.

    Returns:
        bool: True when the user confirms execution.
    """

    while True:
        response = input("\nProceed with execution? (Y/N): ").strip().lower()

        if response in {"y", "yes"}:
            return True

        if response in {"n", "no"}:
            return False

        print("Please enter Y or N.")


def display_permission_report(source_campaign):
    """Display the cloud-neutral permission report for a campaign."""
    console.print(permission_reports.render_terminal(source_campaign))


def confirm_permission_review(source_campaign):
    """Require an explicit review of provider-specific required permissions."""
    while True:
        console.print()
        console.print("[bold yellow]Review the required permissions before executing this campaign.[/bold yellow]")
        console.print("[green]Y[/green]  Permissions reviewed, continue")
        console.print("[yellow]V[/yellow]  View permission report")
        console.print("[red]N[/red]  Cancel execution")
        choice = prompt("Choice").strip().lower()
        if choice == "y":
            return True
        if choice == "n":
            return False
        if choice == "v":
            display_permission_report(source_campaign)
            pause()
            continue
        warning("Invalid Selection")
        pause()


def confirm_irreversible_execution(source_campaign):
    """Require an explicit acknowledgement for selected irreversible experiments."""
    experiments = irreversible_experiments(source_campaign)
    if not experiments:
        return True
    console.print()
    console.print("[bold red]Irreversible experiments selected:[/bold red]")
    for experiment in experiments:
        console.print(f"  - {experiment.service}: {experiment.name}")
    console.print(
        "[yellow]These experiments cannot reliably restore the original state or data.[/yellow]"
    )
    return prompt("Type IRREVERSIBLE to continue").strip() == "IRREVERSIBLE"


def confirm_chaos_mesh_versions(source_campaign, *, policy=None, persist=False):
    """Resolve Chaos Mesh install/upgrade choices before campaign execution."""
    try:
        assessments = assess_campaign(source_campaign)
    except (OSError, RuntimeError, ValueError) as exc:
        error(f"Could not inspect the Chaos Mesh Helm release: {exc}")
        return False
    if not assessments:
        return True

    decisions = dict(getattr(source_campaign, "chaos_mesh_version_decisions", {}))
    if persist:
        decisions.update(getattr(_active_campaign(), "chaos_mesh_version_decisions", {}))
    changed = False
    for assessment in assessments:
        console.print(f"\n[bold cyan]Chaos Mesh - {assessment.cluster}[/bold cyan]")
        console.print(assessment.message)
        if assessment.blocked:
            error("Campaign execution is blocked because the installed version is incompatible or unknown.")
            return False
        if assessment.state == "newer":
            warning(assessment.message)
            continue
        if not assessment.requires_decision:
            continue
        existing = decisions.get(assessment.key)
        if decision_is_current(existing, assessment):
            continue

        if policy:
            action = {
                "require-current": None,
                "allow-older": "continue" if assessment.state == "older" else None,
                "upgrade": "upgrade" if assessment.state == "older" else "install",
                "use-installed": "continue" if assessment.state == "older" else None,
            }[policy]
            if action is None:
                error(
                    f"Chaos Mesh policy '{policy}' does not permit the {assessment.state} state "
                    f"for cluster '{assessment.cluster}'."
                )
                return False
        elif assessment.state == "absent":
            console.print(
                f"[bold cyan]1[/bold cyan]. Install Chaos Mesh {assessment.target_version}"
            )
            console.print("[bold cyan]0[/bold cyan]. Cancel")
            choice = prompt("Select Option").strip()
            action = "install" if choice == "1" else "cancel"
        else:
            console.print(
                f"[bold cyan]1[/bold cyan]. Upgrade to Chaos Mesh {assessment.target_version}"
            )
            console.print(f"[bold cyan]2[/bold cyan]. Continue with {assessment.installed_version}")
            console.print("[bold cyan]0[/bold cyan]. Cancel")
            action = {"1": "upgrade", "2": "continue"}.get(
                prompt("Select Option").strip(), "cancel"
            )
        if action == "cancel":
            warning("Campaign execution cancelled.")
            return False
        decisions[assessment.key] = saved_decision(action, assessment)
        changed = True

    apply_execution_actions(source_campaign, assessments, decisions)
    if persist and changed:
        save_chaos_mesh_version_decisions(decisions, context.cloud)
    return True


def permission_report_yaml(file_path, output_format="terminal", output_file=None):
    """Generate a read-only permission report from safely validated YAML."""
    try:
        content = Path(file_path).read_bytes()
    except OSError as exc:
        error(f"Failed to read YAML campaign: {exc}")
        return 1
    review = campaign_yaml_service.inspect_bytes(content, source_name=str(file_path))
    if not review.valid or review.campaign is None:
        error("Campaign YAML validation failed.")
        for message in review.errors:
            print(f"  - {message}")
        return 1
    renderers = {
        "terminal": permission_reports.render_terminal,
        "json": permission_reports.render_json,
        "markdown": permission_reports.render_markdown,
    }
    rendered = renderers[output_format](review.campaign)
    if output_file:
        try:
            Path(output_file).write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            error(f"Failed to write permission report: {exc}")
            return 1
    else:
        print(rendered)
    return 0

def import_yaml_campaign():
    """Validate a YAML campaign and load it into the active campaign."""

    print()
    print("=" * 70)
    print("Import YAML Campaign")
    print("=" * 70)

    if context.cloud not in {"aws", "azure"}:
        error("Select a cloud provider before importing a campaign YAML.")
        pause()
        return

    identity = get_cloud_identity(
        context.cloud,
        context.region or "us-east-1",
        refresh=True,
    )
    if not identity["authenticated"]:
        error(f"Log in to {context.cloud.upper()} before importing a campaign YAML.")
        pause()
        return

    file_path = prompt("Enter YAML file path").strip()

    if not file_path:
        error("YAML file path cannot be empty.")
        pause()
        return

    if not os.path.isfile(file_path):
        error(f"YAML file not found: {file_path}")
        pause()
        return

    try:
        review = campaign_yaml_service.inspect_bytes(
            Path(file_path).read_bytes(),
            source_name=file_path,
            expected_provider=context.cloud,
        )
    except OSError as exc:
        error(f"Failed to read YAML campaign: {exc}")
        pause()
        return

    if not review.valid:
        error("Campaign YAML validation failed.")
        for message in review.errors:
            console.print(f"  - {message}")
        pause()
        return

    preflight = campaign_preflight.preflight(
        review.campaign,
        getattr(review, "document", {}),
        identity,
    )
    if not preflight.ready:
        error("Campaign target preflight failed.")
        for message in preflight.errors:
            console.print(f"  - {message}")
        pause()
        return

    try:
        draft = create_campaign_draft(review.campaign.name, context.cloud)
    except ValueError as exc:
        error(str(exc))
        pause()
        return
    review.campaign.campaign_id = draft.campaign_id
    review.campaign.created_at = draft.created_at
    review.campaign.updated_at = draft.updated_at
    replace_campaign(review.campaign)
    context.cloud = campaign.cloud_provider
    context.region = (
        "azure"
        if context.cloud == "azure"
        else next(
            (
                item.variables.get("aws_region")
                for item in campaign.experiments
                if item.variables.get("aws_region")
            ),
            context.region,
        )
    )
    success(
        f"Campaign '{campaign.name}' loaded with "
        f"{len(campaign.experiments)} experiment(s)."
    )
    pause()


def export_campaign_yaml(file_path=None):
    campaign = _active_campaign()
    if not campaign.experiments:
        warning("Campaign is empty.")
        return None

    if file_path is None:
        default_name = re.sub(r"[^A-Za-z0-9._-]+", "-", campaign.name).strip("-.")
        file_path = prompt(
            f"YAML output path [{default_name or 'chaosforge-campaign'}.yaml]"
        ).strip() or f"{default_name or 'chaosforge-campaign'}.yaml"

    path = Path(file_path).expanduser()
    if path.suffix.lower() not in {".yaml", ".yml"}:
        path = path.with_suffix(".yaml")
    try:
        path.write_bytes(
            campaign_yaml_service.export_bytes(
                campaign,
                environment=_campaign_environment(campaign),
            )
        )
    except (OSError, TypeError, ValueError) as exc:
        error(f"Failed to export campaign YAML: {exc}")
        return None
    success(f"Campaign YAML exported to {path}")
    return path


def _campaign_environment(source_campaign):
    identity = get_cloud_identity(
        source_campaign.cloud_provider,
        context.region or "us-east-1",
        refresh=True,
    )
    if source_campaign.cloud_provider == "aws":
        return {
            "account_id": identity.get("account_id", ""),
            "account_alias": identity.get("name", ""),
        }
    return {
        "subscription_id": identity.get("subscription_id", ""),
        "subscription_name": identity.get("name", ""),
    }

def execute_yaml_campaign(file_path, junit_output=None, chaos_mesh_version_policy="require-current"):
    """
    Validate, plan, and execute a YAML campaign without reading stdin.
    """

    print()
    print("=" * 70)
    print("YAML Execution Mode")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Validate YAML campaign
    # ----------------------------------------------------------

    yaml_campaign = load_and_validate_yaml_campaign(file_path)

    if yaml_campaign is None:
        if junit_output:
            generate_setup_failure_report(
                Path(file_path).stem,
                "Campaign validation or target preflight failed.",
                junit_output,
            )
        return 1

    if not confirm_chaos_mesh_versions(
        yaml_campaign, policy=chaos_mesh_version_policy
    ):
        if junit_output:
            generate_setup_failure_report(
                yaml_campaign.name,
                "Chaos Mesh version policy rejected the target cluster.",
                junit_output,
            )
        return 1

    irreversible = irreversible_experiments(yaml_campaign)
    if irreversible and not yaml_campaign.irreversible_operations_acknowledged:
        error("Campaign contains irreversible experiments that have not been acknowledged.")
        for experiment in irreversible:
            print(f"  - {experiment.service}: {experiment.name}")
        print("Set campaign.irreversible_operations_acknowledged: true after review.")
        if junit_output:
            generate_setup_failure_report(
                yaml_campaign.name,
                "Campaign contains unacknowledged irreversible experiments.",
                junit_output,
            )
        return 1

    # ----------------------------------------------------------
    # 2. Build execution plan
    # ----------------------------------------------------------

    print()
    print("=" * 70)
    print("Execution Plan")
    print("=" * 70)

    try:
        planner = PlanService()
        plan_result = (
            planner.plan_campaign(yaml_campaign, allow_chaos_mesh_setup=True)
            if chaos_mesh_version_policy == "upgrade"
            else planner.plan_campaign(yaml_campaign)
        )

    except (ValueError, LookupError, RuntimeError) as exc:
        error(f"Failed to generate execution plan: {exc}")
        if junit_output:
            generate_setup_failure_report(
                yaml_campaign.name,
                f"Failed to generate execution plan: {exc}",
                junit_output,
            )
        return 1

    if not plan_result.executable:
        error("Campaign is not executable.")
        if junit_output:
            details = "; ".join(getattr(plan_result, "blockers", []) or [])
            generate_setup_failure_report(
                yaml_campaign.name,
                details or "Campaign is not executable.",
                junit_output,
            )
        return 1

    # ----------------------------------------------------------
    # 3. Display execution plan
    # ----------------------------------------------------------

    display_campaign_plan(yaml_campaign, plan_result)

    # ----------------------------------------------------------
    # 4. Execute
    # ----------------------------------------------------------

    print()
    print("=" * 70)
    print("Starting campaign execution...")
    print("=" * 70)

    execution_id = campaign_history.start_execution(yaml_campaign, "yaml-cli")
    try:
        result = execute_lifecycle_campaign(yaml_campaign)
        report_file = generate_report(yaml_campaign) if hasattr(yaml_campaign, "duration") else None
        status = getattr(result, "status", "SUCCESS")
        campaign_history.finish_execution(
            execution_id,
            yaml_campaign,
            status if isinstance(status, str) else "SUCCESS",
            report_path=report_file,
        )
        if junit_output:
            generate_junit_report(yaml_campaign, junit_output)
    except Exception as exc:
        campaign_history.finish_execution(execution_id, yaml_campaign, "FAILED")
        if junit_output:
            generate_setup_failure_report(yaml_campaign.name, str(exc), junit_output)
        raise

    return 0


def clear_screen():

    os.system("cls" if os.name == "nt" else "clear")


def _confirm_azure_details():
    """Ask whether to reuse the current cloud context or re-enter Azure details.
    Returns False if the user cancels while (re)entering details."""
    if not (context.azure_subscription and context.azure_resource_group and context.aks_cluster_name):
        # Nothing cached yet — go straight to collecting details.
        return PlatformSelector()._prompt_azure_details()

    console.print()
    console.print("[bold cyan]Azure Configuration[/bold cyan]")
    console.print(f"[bright_black]Subscription:[/bright_black] {context.azure_account_name or context.azure_subscription}")
    console.print(f"[bright_black]Resource Group:[/bright_black] {context.azure_resource_group}")
    console.print(f"[bright_black]AKS Cluster:[/bright_black] {context.aks_cluster_name}")
    if context.aks_kube_context:
        console.print(f"[bright_black]Kube Context:[/bright_black] {context.aks_kube_context}")
    console.print()

    reuse = prompt("Use the same cloud context as before? (Y/N)").strip().lower()

    if reuse == "y":
        return PlatformSelector().ensure_azure_kube_context()

    return PlatformSelector()._prompt_azure_details()


def add_experiment():

    cloud       = context.cloud
    cloud_label = "Azure" if cloud == "azure" else "AWS"

    while True:
        clear_screen()

        print_banner()

        dashboard(
            region=context.region,
            campaign_name=_active_campaign_name(),
            experiment_count=len(_active_experiments()),
            cloud=context.cloud,
        )

        title("Add Experiment")

        services = discover_services(cloud)

        menu(
            f"Select {cloud_label} Service",
            [
                (index, display_name(service))
                for index, service in enumerate(services, start=1)
            ],
        )

        console.print()

        console.print("[bold bright_cyan]0[/bold bright_cyan]. Back")

        console.print()

        choice = prompt("Enter Choice").strip()

        if choice == "0":
            return

        try:
            service = services[int(choice) - 1]

        except (ValueError, IndexError):
            error("Invalid Choice")

            pause()

            continue

        # Route to the correct experiment menu for this service
        if cloud == "azure":
            if service == "aks":
                if not _confirm_azure_details():
                    continue
                aks_experiment_menu()
            elif service == "azure_redis":
                redis_experiment_menu()
            else:
                azure_component_experiment_menu(service)
        else:
            experiment_menu(service)


def view_campaign():

    campaign = _active_campaign()

    clear_screen()

    print_banner()

    dashboard(
        region=context.region,
        campaign_name=campaign.name,
        experiment_count=len(_active_experiments()),
        cloud=context.cloud,
    )

    title("Campaign")

    experiments = _active_experiments()

    SERVICE_NAMES = {
        "lambda": "AWS Lambda",
        "dynamodb": "Amazon DynamoDB",
        "rds": "Amazon RDS",
        "elasticache": "Amazon ElastiCache",
        "sns": "Amazon SNS",
        "fis": "AWS FIS",
        "ecs": "Amazon ECS",
    }

    VARIABLE_LABELS = {
        "lambda_name": "Lambda Name",
        "aws_region": "AWS Region",
        "target_timeout": "Target Timeout (sec)",
        "wait_seconds": "Wait Time (sec)",
        "target_memory_size": "Target Memory (MB)",
        "target_concurrency": "Target Concurrency",
        "target_provisioned_concurrency": "Target Provisioned Concurrency",
        "target_retry_attempts": "Target Retry Attempts",
        "startup_delay_milliseconds": "Startup Delay (ms)",
        "percentage": "Traffic Percentage",
        "duration": "Duration",
        "target_arn": "Target Resource ARN",
        "role_arn": "FIS Role ARN",
        "experiment_name": "Experiment Name",
        "description": "Description",
        "created_by": "Created By",
        "service_id": "Target Service",
        "experiment_id": "FIS Experiment",
        "fis_config_bucket": "FIS Configuration S3 Bucket",
    }

    if not experiments:
        info("No experiments added yet.")

        pause()

        return

    console.print(f"[bold cyan]Campaign[/bold cyan] : {campaign.name}")

    console.print(f"[bold cyan]Experiments[/bold cyan] : {len(experiments)}\n")

    for index, experiment in enumerate(experiments, start=1):
        service_name = SERVICE_NAMES.get(experiment.service.lower(), experiment.service)

        console.print(f"[bold yellow]Experiment #{index}[/bold yellow]")

        console.print(f"   Service      : {service_name}")

        console.print(f"   Engine       : {experiment.engine}")

        console.print(f"   Experiment   : {experiment.name}")

        console.print(f"   Status       : {experiment.status}")

        console.print("   Configuration")

        for key, value in experiment.variables.items():
            if key in ["service_id", "experiment_id"]:
                continue

            label = VARIABLE_LABELS.get(key, key.replace("_", " ").title())

            console.print(f"      {label:<22}: {value}")

        console.print("[dim]" + "-" * 80 + "[/dim]")

    while True:
        console.print()
        console.print(
            "[black on bright_red] 1 [/black on bright_red] "
            "[bold bright_red]View Required Permissions[/bold bright_red]"
        )
        console.print("[bold cyan]2[/bold cyan] Export Campaign as YAML")
        console.print("[bold cyan]0[/bold cyan] Back")
        console.print()

        choice = prompt("Enter Choice").strip()

        if choice == "1":
            console.print()

            display_permission_report(campaign)

            pause()

            return

        elif choice == "2":
            export_campaign_yaml()
            pause()
            return

        elif choice == "0":
            return

        else:
            error("Invalid Choice")

            pause()


def remove_experiment():

    campaign = _active_campaign()

    clear_screen()

    print_banner()

    dashboard(
        region=context.region,
        campaign_name=campaign.name,
        experiment_count=len(_active_experiments()),
        cloud=context.cloud,
    )

    title("Remove Experiment")

    experiments = _active_experiments()

    if not experiments:
        warning("Campaign is empty.")

        pause()

        return

    menu_items = []

    for index, experiment in enumerate(experiments, start=1):
        menu_items.append((index, f"{experiment.service} - {experiment.name}"))

    menu("Current Campaign", menu_items)

    console.print()

    console.print("[bold bright_cyan]0[/bold bright_cyan]. Back")

    console.print()

    choice = prompt("Experiment Number").strip()

    if choice == "0":
        return

    try:
        if context.cloud == "azure":
            remove(int(choice) - 1, "azure")
        else:
            remove(int(choice) - 1)

        success("Experiment removed successfully.")

    except (ValueError, IndexError):
        error("Invalid Selection.")

    pause()


def edit_campaign_experiment():
    """Edit one campaign experiment in place using its catalog input contract."""

    clear_screen()
    print_banner()
    dashboard(
        region=context.region,
        campaign_name=_active_campaign().name,
        experiment_count=len(_active_experiments()),
        cloud=context.cloud,
    )
    title("Edit Campaign Experiment")

    experiments = _active_experiments()
    if not experiments:
        warning("Campaign is empty.")
        pause()
        return

    menu(
        "Current Campaign",
        [
            (index, f"{experiment.service} - {experiment.name}")
            for index, experiment in enumerate(experiments, start=1)
        ],
    )
    console.print()
    console.print("[bold bright_cyan]0[/bold bright_cyan]. Back")
    console.print()

    choice = prompt("Experiment Number").strip()
    if choice == "0":
        return

    try:
        index = int(choice) - 1
        existing = experiments[index]
    except (ValueError, IndexError):
        error("Invalid Selection.")
        pause()
        return

    from chaosforge.application.metadata import get_experiment

    metadata = get_experiment(existing.service, existing.id)
    if metadata is None:
        error(f"Metadata not found for {existing.name}.")
        pause()
        return

    metadata = deepcopy(metadata)
    if existing.service == "fis":
        from chaosforge.providers.aws.fis.catalog import FISCatalog

        fis_experiment = FISCatalog().get_experiment(
            existing.variables.get("service_id"),
            existing.variables.get("experiment_id"),
        )
        if fis_experiment:
            metadata["name"] = f"{fis_experiment['name']} (AWS FIS)"

    try:
        if existing.service == "aks":
            from chaosforge.interfaces.cli.interactive.azure_aks_service import (
                _collect_aks_inputs,
            )

            variables = _collect_aks_inputs(metadata)
        elif existing.service == "azure_redis":
            from chaosforge.interfaces.cli.interactive.azure_redis_menu import (
                collect_redis_inputs,
            )

            variables = collect_redis_inputs(metadata)
        else:
            from chaosforge.interfaces.cli.interactive.input_engine import collect_inputs

            variables = collect_inputs(
                metadata,
                prefill=existing.variables,
                edit_mode=True,
            )
    except BackToMainMenu:
        return

    if variables is None:
        info("Experiment edit cancelled.")
        pause()
        return

    updated_experiment = create_experiment(
        existing.service,
        metadata,
        variables,
        default_region=context.region,
    )
    validation = ExperimentValidationService().validate_experiment(updated_experiment)
    if not validation["valid"]:
        error("Updated experiment validation failed.")
        for message in validation["errors"]:
            console.print(f"  - {message}")
        pause()
        return

    if context.cloud == "azure":
        update(index, updated_experiment, "azure")
    else:
        update(index, updated_experiment)
    success(f"{updated_experiment.name} updated successfully.")
    pause()


def clear_campaign():

    campaign = _active_campaign()

    clear_screen()

    print_banner()

    dashboard(
        region=context.region,
        campaign_name=campaign.name,
        experiment_count=len(_active_experiments()),
        cloud=context.cloud,
    )

    title("Clear Campaign")

    experiments = _active_experiments()

    if not experiments:
        warning("Campaign is already empty.")

        pause()

        return

    console.print(
        f"[bold yellow]Experiments in Campaign :[/bold yellow] {len(experiments)}"
    )

    console.print()

    confirm = prompt("Clear entire campaign? (Y/N)").strip().lower()

    if confirm == "y":
        if context.cloud == "azure":
            clear("azure")
        else:
            clear()

        success("Campaign cleared successfully.")

    else:
        info("Operation cancelled.")

    pause()


def build_selected_campaign(experiments):

    clear_screen()

    print_banner()

    dashboard(
        region=context.region,
        campaign_name=campaign.name,
        experiment_count=len(experiments),
        cloud=context.cloud,
    )

    title("Execute Selected Experiments")

    console.print()

    for index, experiment in enumerate(experiments, start=1):
        console.print(
            f"[bold yellow]{index}.[/bold yellow] "
            f"{experiment.service}  →  {experiment.name}"
        )

    console.print()

    selection = prompt("Select experiments to execute (Example: 1,3)").strip()

    try:
        indexes = sorted({int(x.strip()) - 1 for x in selection.split(",")})

    except ValueError:
        error("Invalid selection.")

        pause()

        return None

    selected = Campaign()

    selected.name = campaign.name
    selected.continue_on_failure = campaign.continue_on_failure
    selected.irreversible_operations_acknowledged = campaign.irreversible_operations_acknowledged
    selected.cloud_provider = campaign.cloud_provider
    selected.chaos_mesh_version_decisions = dict(
        getattr(campaign, "chaos_mesh_version_decisions", {})
    )

    for index in indexes:
        if index < 0 or index >= len(experiments):
            error(f"Experiment {index + 1} does not exist.")

            pause()

            return None

        selected.experiments.append(experiments[index])

    return selected


def build_failed_campaign(campaign):

    failed = Campaign()

    failed.name = f"{campaign.name} - Retry"
    failed.continue_on_failure = campaign.continue_on_failure
    failed.irreversible_operations_acknowledged = campaign.irreversible_operations_acknowledged
    failed.cloud_provider = campaign.cloud_provider

    failed.experiments = [
        experiment
        for experiment in campaign.experiments
        if experiment.status == "FAILED"
    ]

    return failed


def refresh_failed_aks_pod_targets(campaign):
    """Replace stale pod-mode targets before retrying failed AKS experiments."""
    from chaosforge.providers.azure.components.aks.discovery import AzureAKSDiscovery

    for experiment in campaign.experiments:
        if experiment.service != "aks" or experiment.variables.get("target_mode") != "pod":
            continue
        variables = experiment.variables
        context_name = variables.get("aks_context", "")
        namespace = variables.get("namespace", "")
        current_pod = variables.get("pod") or variables.get("deployment", "")
        if not (context_name and namespace and current_pod):
            continue
        discovery = AzureAKSDiscovery()
        pods = discovery.list_pods(context_name, namespace)
        if current_pod in pods:
            continue
        if not pods:
            warning(
                f"Pod target '{current_pod}' no longer exists and no running replacement was found "
                f"in namespace '{namespace}'. Edit the failed experiment before retrying."
            )
            experiment.status = "SKIPPED"
            continue
        console.print()
        warning(f"Pod target '{current_pod}' no longer exists in namespace '{namespace}'.")
        menu("Select Replacement Pod", [(index, pod) for index, pod in enumerate(pods, start=1)])
        try:
            replacement = pods[int(prompt("Select Replacement Pod").strip()) - 1]
        except (ValueError, IndexError):
            warning("Pod target was not refreshed; retry was skipped for this experiment.")
            experiment.status = "SKIPPED"
            continue
        label_key, label_val = discovery.get_pod_label(context_name, namespace, replacement)
        variables["pod"] = replacement
        variables["deployment"] = replacement
        variables["label_key"] = label_key
        variables["label_val"] = label_val
        variables["owning_deployment"] = (
            discovery.get_deployment_for_pod(context_name, namespace, replacement) or ""
        )
        success(f"Pod target updated to '{replacement}'.")


def edit_failed_campaign(campaign):

    from chaosforge.application.metadata import get_experiment
    from chaosforge.interfaces.cli.interactive.input_engine import collect_inputs

    failed = [
        experiment
        for experiment in campaign.experiments
        if experiment.status == "FAILED"
    ]

    if not failed:
        return

    for experiment in failed:
        metadata = get_experiment(experiment.service, experiment.id)

        if metadata is None:
            warning(f"Metadata not found for {experiment.name}")

            continue

        experiment.variables = collect_inputs(
            metadata, prefill=experiment.variables, edit_mode=True
        )

        experiment.status = "Pending"


def execute_campaign():

    campaign = _active_campaign()

    clear_screen()

    print_banner()

    dashboard(
        region=context.region,
        campaign_name=campaign.name,
        experiment_count=len(_active_experiments()),
        cloud=context.cloud,
    )

    title("Execute Campaign")

    experiments = _active_experiments()

    if not experiments:
        warning("Campaign is empty.")

        pause()

        return

    if not confirm_permission_review(campaign):
        warning("Campaign execution cancelled.")

        pause()

        return

    #
    # Draw Execute Screen
    #

    clear_screen()

    print_banner()

    dashboard(
        region=context.region,
        campaign_name=campaign.name,
        experiment_count=len(_active_experiments()),
        cloud=context.cloud,
    )

    title("Execute Campaign")

    console.print(f"[bold cyan]Campaign[/bold cyan] : {campaign.name}")

    console.print(f"[bold cyan]Experiments[/bold cyan] : {len(experiments)}")

    console.print()

    from chaosforge.application.metadata import load_service_metadata

    console.print()

    table = Table(show_header=True, header_style="bold cyan", expand=False)

    table.add_column("#", justify="right", width=3)
    table.add_column("Service", width=22)
    table.add_column("Engine", width=18)
    table.add_column("Experiment")
    table.add_column("Safety", width=14)
    table.add_column("Namespace", width=20)

    for index, experiment in enumerate(experiments, start=1):
        #
        # Chaos Toolkit / Chaos Mesh
        #

        if experiment.service not in ("fis", "aks"):
            service_id = experiment.target_service or experiment.service

            service = load_service_metadata(service_id)

            service_name = (
                service.get("display_name", service_id)
                if service
                else service_id
            )

            engine = experiment.engine or "Chaos Toolkit"

        elif experiment.service == "aks":
            service      = load_service_metadata("aks")
            service_name = service.get("display_name", "Azure AKS") if service else "Azure AKS"
            engine       = "Azure Chaos Studio"

        #
        # AWS FIS
        #

        else:
            service_id = experiment.variables.get("service_id", "fis")

            service = load_service_metadata(service_id)

            service_name = (
                service.get("display_name", service_id)
                if service
                else service_id
            )

            engine = "AWS FIS"

        exp_name = experiment.name.replace(" (AWS FIS)", "")
        dry_run_val = experiment.variables.get("dry_run", "")
        if str(dry_run_val).strip().lower() in ("true", "1", "yes", "y"):
            exp_name += "  [dim yellow][DRY RUN][/dim yellow]"
        namespace = experiment.variables.get("namespace", "")
        safety = (
            "[green]REVERSIBLE[/green]"
            if getattr(experiment, "reversibility", "reversible") == "reversible"
            else "[red]IRREVERSIBLE[/red]"
        )
        table.add_row(str(index), service_name, engine, exp_name, safety, namespace)

    console.print(table)

    console.print()

    console.print("[bold cyan]1[/bold cyan]  Execute All Experiments")

    console.print("[bold cyan]2[/bold cyan]  Execute Selected Experiments")

    console.print("[bold cyan]0[/bold cyan]  Back")

    console.print()

    choice = prompt("Enter Choice").strip()

    if choice == "0":
        return

    elif choice == "1":
        execution_campaign = campaign

    elif choice == "2":
        execution_campaign = build_selected_campaign(experiments)

        if execution_campaign is None:
            return

    else:
        error("Invalid Choice")

        pause()

        return

    if not confirm_irreversible_execution(execution_campaign):
        warning("Campaign execution cancelled.")
        pause()
        return

    if not confirm_chaos_mesh_versions(execution_campaign, persist=True):
        pause()
        return

    execute_lifecycle_campaign(execution_campaign)

    generate_report(execution_campaign)

    from chaosforge.interfaces.cli.interactive.campaign_result import (
        show_campaign_result_menu,
    )

    while True:
        action = show_campaign_result_menu(execution_campaign)

        if action is None:
            break

        elif action == "retry":
            failed_campaign = build_failed_campaign(execution_campaign)

            if not failed_campaign.experiments:
                warning("No failed experiments found.")

                pause()

                continue

            refresh_failed_aks_pod_targets(failed_campaign)
            failed_campaign.experiments = [
                experiment
                for experiment in failed_campaign.experiments
                if experiment.status != "SKIPPED"
            ]
            if not failed_campaign.experiments:
                warning("No failed experiments remain eligible for retry.")
                pause()
                continue

            refresh_failed_aks_pod_targets(failed_campaign)
            failed_campaign.experiments = [
                experiment
                for experiment in failed_campaign.experiments
                if experiment.status != "SKIPPED"
            ]
            if not failed_campaign.experiments:
                warning("No failed experiments remain eligible for retry.")
                pause()
                continue

            execute_lifecycle_campaign(failed_campaign)

            generate_report(execution_campaign)

        elif action == "edit":
            edit_failed_campaign(execution_campaign)

            success("Failed experiments updated.")

            pause()


def save_campaign():

    campaign = _active_campaign()

    clear_screen()

    print_banner()

    dashboard(
        region=context.region,
        campaign_name=campaign.name,
        experiment_count=len(_active_experiments()),
    )

    title("Save Campaign")

    experiments = _active_experiments()

    if not experiments:
        warning("Campaign is empty.")
        pause()
        return

    console.print()

    console.print(f"[bold cyan]Campaign[/bold cyan] : {campaign.name}")

    console.print(f"[bold cyan]Experiments[/bold cyan] : {len(experiments)}")

    console.print()

    export_campaign_yaml()
    pause()


def load_campaign():

    clear_screen()

    print_banner()

    title("Load Campaign")

    console.print("[bold bright_cyan]Y[/bold bright_cyan]. Load Campaign YAML")
    console.print()

    campaigns = list_saved_campaigns()

    if campaigns:
        menu(
            "Saved Campaigns",
            [
                (
                    index,
                    (f"{item['name']} ({item['experiments']} experiments)"),
                )
                for index, item in enumerate(
                    campaigns,
                    start=1,
                )
            ],
        )
    else:
        info("No saved JSON campaigns found. You can still load a YAML campaign.")

    console.print()

    console.print("[bold bright_cyan]0[/bold bright_cyan]. Back")

    console.print()

    choice = prompt("Select Campaign").strip()

    if choice.lower() == "y":
        import_yaml_campaign()
        return

    if choice == "0":
        return

    try:
        index = int(choice) - 1
        selected = campaigns[index]

    except (ValueError, IndexError):
        error("Invalid Choice")
        pause()
        return

    try:
        loaded_campaign = load_saved_campaign(selected["name"])

        campaign.name = selected["name"]
        campaign.continue_on_failure = loaded_campaign.continue_on_failure
        campaign.cloud_provider = loaded_campaign.cloud_provider
        campaign.experiments = loaded_campaign.experiments

        success(f"Campaign '{selected['name']}' loaded successfully.")

        console.print()

        console.print(
            f"[bold cyan]Experiments[/bold cyan] : {len(campaign.experiments)}"
        )

    except FileNotFoundError:
        error(f"Campaign '{selected['name']}' was not found.")

    except (KeyError, TypeError, ValueError) as exc:
        error(f"Failed to load campaign: {exc}")

    pause()


def campaign_history_view():
    clear_screen()
    print_banner()
    title("Campaign History")
    records = campaign_history.list_executions(context.cloud)
    if not records:
        info(f"No {context.cloud.upper()} campaign executions have been recorded.")
        pause()
        return
    menu(
        "Execution History",
        [
            (
                index,
                f"{record['campaign_name']} | {record['status']} | {record['source']} | "
                f"Created {record['created_at']}",
            )
            for index, record in enumerate(records, start=1)
        ] + [(0, "Back")],
    )
    choice = prompt("Select Execution").strip()
    if choice == "0":
        return
    try:
        record = records[int(choice) - 1]
    except (ValueError, IndexError):
        error("Invalid Choice")
        pause()
        return
    console.print()
    console.print(f"[bold cyan]Campaign:[/bold cyan] {record['campaign_name']}")
    console.print(f"[bold cyan]Source:[/bold cyan] {record['source']}")
    console.print(f"[bold cyan]Status:[/bold cyan] {record['status']}")
    console.print(f"[bold cyan]Created:[/bold cyan] {record['created_at']}")
    console.print(f"[bold cyan]Started:[/bold cyan] {record['started_at']}")
    if record.get("completed_at"):
        console.print(f"[bold cyan]Completed:[/bold cyan] {record['completed_at']}")
    if record.get("report_path"):
        console.print(f"[bold cyan]Report:[/bold cyan] {record['report_path']}")
    if record.get("logs"):
        console.print("\n[bold cyan]Output[/bold cyan]")
        console.print("\n".join(record["logs"]))
    pause()


def campaign_library():
    cloud_name = "Amazon Web Services" if context.cloud == "aws" else "Microsoft Azure"
    identity = get_cloud_identity(
        context.cloud,
        context.region or "us-east-1",
        refresh=True,
    )
    context.cloud_identity = identity
    if not identity.get("authenticated"):
        error(f"Log in to {cloud_name} before creating or opening campaigns.")
        pause()
        return False

    while True:
        clear_screen()
        print_banner()
        title(f"{context.cloud.upper()} Campaign Library")
        drafts = list_campaign_drafts(context.cloud)
        menu(
            "Draft Campaigns",
            [(1, "Create New Campaign")]
            + [
                (index + 1, f"Open {item['name']} ({item['experiments']} experiments, created {item['created_at']})")
                for index, item in enumerate(drafts, start=1)
            ]
            + [("D", "Delete Campaign"), (0, "Back")],
        )
        choice = prompt("Select Option").strip()
        if choice == "0":
            return False
        if choice.lower() == "d":
            if not drafts:
                info("No draft campaigns to delete.")
                pause()
                continue
            menu(
                "Delete Draft Campaign",
                [
                    (index, f"{item['name']} ({item['experiments']} experiments)")
                    for index, item in enumerate(drafts, start=1)
                ] + [(0, "Cancel")],
            )
            delete_choice = prompt("Select Campaign").strip()
            if delete_choice == "0":
                continue
            try:
                selected = drafts[int(delete_choice) - 1]
            except (ValueError, IndexError):
                error("Invalid Choice")
                pause()
                continue
            confirmation = prompt(
                f"Delete campaign '{selected['name']}'? (Y/N)"
            ).strip().lower()
            if confirmation == "y":
                try:
                    delete_campaign_draft(selected["id"], context.cloud)
                except (FileNotFoundError, ValueError):
                    error("Campaign was not found.")
                else:
                    success(f"Campaign '{selected['name']}' deleted.")
                pause()
            continue
        if choice == "1":
            name = prompt("Campaign Name").strip()
            try:
                create_campaign_draft(name, context.cloud)
            except ValueError as exc:
                error(str(exc))
                pause()
                continue
            success(f"Campaign '{name}' created.")
            pause()
            return True
        try:
            selected = drafts[int(choice) - 2]
            open_campaign_draft(selected["id"], context.cloud)
        except (ValueError, IndexError, FileNotFoundError):
            error("Invalid Choice")
            pause()
            continue
        success(f"Campaign '{selected['name']}' opened.")
        pause()
        return True


def settings():

    while True:
        clear_screen()

        print_banner()

        dashboard(
            region=context.region,
            campaign_name=campaign.name,
            experiment_count=len(list_all()),
            cloud=context.cloud,
        )
        title("Settings")

        is_azure = context.cloud == "azure"

        if is_azure:
            console.print("[bold cyan]☁  Cloud[/bold cyan] : Microsoft Azure\n")
            console.print(
                f"[bold cyan]🕒 Current Timezone[/bold cyan] : "
                f"{format_timezone(context.timezone_id)}\n"
            )
            menu("Settings", [(1, "Change Timezone")])
        else:
            console.print(f"[bold cyan]🌐 Current Region[/bold cyan] : {context.region}\n")
            console.print(
                f"[bold cyan]🕒 Current Timezone[/bold cyan] : "
                f"{format_timezone(context.timezone_id)}\n"
            )
            menu(
                "Settings",
                [
                    (1, "Change AWS Region"),
                    (2, "Change Timezone"),
                ],
            )

        console.print()

        console.print("[bold bright_cyan]0[/bold bright_cyan]. Back")

        console.print()

        choice = prompt("Enter Choice").strip()

        if not is_azure and choice == "1":
            region = RegionSelector().select(navigation=True)
            if region == "__main_menu__":
                return
            if region is None:
                continue
            context.region = region

            success("Region Updated")

            pause()

        elif choice == ("1" if is_azure else "2"):
            options = timezone_options()
            menu("Select Timezone", [
                (index, item["display"])
                for index, item in enumerate(options, start=1)
            ] + [(0, "Back"), ("M", "Main Menu")])
            timezone_choice = prompt("Enter Choice").strip()
            if timezone_choice == "0":
                continue
            if timezone_choice.lower() == "m":
                return
            try:
                timezone_id = options[int(timezone_choice) - 1]["id"]
            except (ValueError, IndexError):
                error("Invalid Choice")
            else:
                set_timezone_id(timezone_id)
                context.timezone_id = timezone_id
                success(f"Timezone Updated: {format_timezone(timezone_id)}")
            pause()

        elif choice == "0":
            return

        else:
            error("Invalid Choice")

            pause()


def validate_yaml_campaign(file_path):
    """
    Validate a YAML campaign including cloud credential verification.

    No chaos experiment or resource mutation is performed.
    """

    yaml_campaign = load_and_validate_yaml_campaign(file_path)

    if yaml_campaign is None:
        return 1

    return 0

def display_campaign_plan(campaign, result):
    """Display a normalized campaign execution plan."""

    print()
    print(f"Campaign    : {campaign.name}")
    print(
        f"Executable  : {'YES' if result.executable else 'NO'}"
    )

    print()
    print("Experiments:")
    for experiment in result.experiments:
        print(
            f"  - {experiment.get('id', 'unknown')}"
            f" | {experiment.get('service', 'unknown')}"
            f" | {experiment.get('status', 'UNKNOWN')}"
        )

    print()
    print("Targets:")
    if result.targets:
        for target in result.targets:
            print(
                f"  - {target.get('resource_type', 'unknown')}"
                f" | {target.get('resource_id', 'unknown')}"
            )
    else:
        print("  - None")

    print()
    print("Impact:")
    capacity = result.impact.get("capacity", {})
    print(
        f"  Capacity status : "
        f"{capacity.get('status', 'UNKNOWN')}"
    )
    print(
        f"  Affected %      : "
        f"{capacity.get('affected_percent', 'UNKNOWN')}"
    )

    print()
    print("Availability Zones:")
    zones = result.impact.get(
        "availability_zones",
        [],
    )
    if zones:
        for zone in zones:
            print(f"  - {zone}")
    else:
        print("  - UNKNOWN")

    print()
    print("Traffic Impact:")
    traffic = result.impact.get(
        "traffic",
        {},
    )
    print(
        f"  {traffic.get('status', 'UNKNOWN')}"
        f" - {traffic.get('reason', '')}"
    )

    print()
    print("Customer Impact:")
    customer = result.impact.get(
        "customer_impact",
        {},
    )
    print(
        f"  {customer.get('status', 'UNKNOWN')}"
        f" - {customer.get('reason', '')}"
    )

    print()
    print("Required Permissions:")
    if result.permissions:
        for permission in result.permissions:
            print(
                f"  - {permission.get('action')}"
                f" [{permission.get('access', 'UNKNOWN')}]"
            )
    else:
        print("  - None")

    print()
    print("Capabilities:")
    if result.capabilities:
        for capability in result.capabilities:
            print(f"  - {capability}")
    else:
        print("  - None")

    print()
    print("Duration:")
    print(
        f"  {result.duration.get('status', 'UNKNOWN')}"
        f" | "
        f"{result.duration.get('estimated_seconds')}"
        f" seconds"
    )

    print()
    print("Recovery:")
    print(
        f"  {result.recovery.get('behavior', 'UNKNOWN')}"
    )

    if result.warnings:
        print()
        print("Warnings:")
        for item in result.warnings:
            print(f"  - {item}")

    if result.blockers:
        print()
        print("Blockers:")
        for item in result.blockers:
            print(f"  - {item}")

def plan_yaml_campaign(file_path):
    """
    Generate a read-only execution plan for a YAML campaign.

    No fault injection or resource mutation is performed.
    """

    print()
    print("=" * 70)
    print("YAML Planning Mode")
    print("=" * 70)

    try:
        campaign = load_and_validate_yaml_campaign(file_path)

        if campaign is None:
            return 1

        planner = PlanService()
        result = planner.plan_campaign(campaign)

        display_campaign_plan(campaign, result)

        return 0 if result.executable else 1

    except Exception as exc:  # noqa: BLE001
        error(
            f"Planning error: {exc}"
        )
        return 1

def _select_cloud_context():
    clear_screen()
    print_banner()
    context.cloud = PlatformSelector().select()
    context.cloud_identity = get_cloud_identity(context.cloud)
    context.timezone_id = get_timezone_id()

    # Azure uses kubectl contexts — no AWS region needed. Only re-render the
    # banner here when something (RegionSelector) actually renders next; the
    # main menu loop below always clears and re-prints its own banner
    # immediately after, so an unconditional print_banner() here would just
    # show the banner twice in a row with nothing in between for Azure.
    if context.cloud == "azure":
        context.region = "azure"
    else:
        clear_screen()

        print_banner()

        context.region = RegionSelector().select()


def interactive_main():
    _select_cloud_context()

    while True:
        try:
            clear_screen()

            print_banner()

            dashboard(
                region=context.region,
                campaign_name=_active_campaign_name(),
                experiment_count=len(_active_experiments()),
                cloud=context.cloud,
            )

            title("Main Menu")

            rows = [
                (1, "🚀  [bold white]Create Chaos Campaign[/bold white]"),
                (2, "📋  [bold white]Campaign Summary[/bold white]"),
                (3, "🗑  [bold white]Remove Experiment[/bold white]"),
                (4, "▶  [bold white]Execute Campaign[/bold white]"),
                (5, "📥  [bold white]Import YAML Campaign[/bold white]"),
                (6, "🧹  [bold white]Clear Campaign[/bold white]"),
                (7, "💾  [bold white]Save Campaign[/bold white]"),
                (8, "📂  [bold white]Load Campaign[/bold white]"),
                (9, "⚙  [bold white]Settings[/bold white]"),
                (10, "✏️  [bold white]Edit Campaign Experiment[/bold white]"),
                (11, "🕘  [bold white]Campaign History[/bold white]"),
                (12, "🗂  [bold white]Campaign Library[/bold white]"),
                (13, "🛡  [bold white]View Required Permissions[/bold white]"),
                (14, "☁️  [bold white]Change Cloud[/bold white]"),
                (0, "🚪  [bold white]Exit[/bold white]"),
            ]

            render_main_menu(rows)

            console.print()

            choice = prompt("Enter Choice").strip()

            if choice == "1":
                if campaign_library():
                    add_experiment()

            elif choice == "2":
                view_campaign()

            elif choice == "3":
                remove_experiment()

            elif choice == "4":
                execute_campaign()

            elif choice == "5":
                import_yaml_campaign()

            elif choice == "6":
                clear_campaign()

            elif choice == "7":
                save_campaign()

            elif choice == "8":
                load_campaign()

            elif choice == "9":
                settings()

            elif choice == "10":
                edit_campaign_experiment()

            elif choice == "11":
                campaign_history_view()

            elif choice == "12":
                campaign_library()

            elif choice == "13":
                if not _active_experiments():
                    warning("Campaign is empty.")
                    pause()
                    continue
                display_permission_report(campaign)
                pause()

            elif choice == "14":
                _select_cloud_context()

            elif choice == "0":
                clear_screen()

                print_banner()

                success("Thank you for using ChaosForge!")

                console.print()

                console.print("[bold]Chaos Engineering Platform[/bold]")

                console.print("Version : 1.0")

                console.print()

                sys.exit(0)

            else:
                error("Invalid Choice")

                pause()

        except BackToMainMenu:
            continue


def main():
    """Parse CLI arguments and start the requested ChaosForge interface."""
    parser = argparse.ArgumentParser(prog="chaosforge")
    parser.add_argument("--version", action="version", version=f"%(prog)s {chaosforge_version()}")

    parser.add_argument(
        "--yaml",
        help="Execute a campaign from a YAML file",
    )
    parser.add_argument(
        "--format",
        choices=["terminal", "json", "markdown"],
        default="terminal",
        help="Permission report output format",
    )
    parser.add_argument("--output", help="Write a permission report to this file")
    parser.add_argument(
        "--junit-output",
        help="Write GitLab-compatible JUnit XML for the run command",
    )
    parser.add_argument(
        "--chaos-mesh-version-policy",
        choices=["require-current", "allow-older", "upgrade", "use-installed"],
        default="require-current",
        help="Non-interactive policy for installed Chaos Mesh versions",
    )

    parser.add_argument(
        "command",
        nargs="?",
        choices=["validate", "plan", "run", "permissions"],
        help="Run a ChaosForge command",
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="YAML campaign file",
    )

    args = parser.parse_args()

    if args.junit_output and args.command != "run":
        parser.error("--junit-output is only supported with the run command")

    try:
        if args.command == "permissions":
            if not args.file:
                parser.error("the permissions command requires a YAML file")
            sys.exit(permission_report_yaml(args.file, args.format, args.output))

        elif args.command == "validate":
            if not args.file:
                parser.error(
                    "the validate command requires a YAML file"
                )

            exit_code = validate_yaml_campaign(
                args.file
            )

            sys.exit(exit_code)

        elif args.command == "plan":
            if not args.file:
                parser.error(
                    "the plan command requires a YAML file"
                )

            exit_code = plan_yaml_campaign(
                args.file
            )

            sys.exit(exit_code)

        elif args.command == "run":
            if not args.file:
                parser.error(
                    "the run command requires a YAML file"
                )

            kwargs = {}
            if args.junit_output:
                kwargs["junit_output"] = args.junit_output
            if args.chaos_mesh_version_policy != "require-current":
                kwargs["chaos_mesh_version_policy"] = args.chaos_mesh_version_policy
            exit_code = execute_yaml_campaign(args.file, **kwargs)

            sys.exit(exit_code)

        elif args.yaml:
            kwargs = {}
            if args.chaos_mesh_version_policy != "require-current":
                kwargs["chaos_mesh_version_policy"] = args.chaos_mesh_version_policy
            execute_yaml_campaign(args.yaml, **kwargs)

        else:
            interactive_main()
    except KeyboardInterrupt:
        print("\nShutdown requested. Waiting for the active experiment rollback to finish.")
        # Experiment runners handle provider rollback before returning. This
        # outer boundary prevents a second Ctrl-C from producing a traceback.
        return


if __name__ == "__main__":
    main()
