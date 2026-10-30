"""Pytest options for developer-run live Web UI functional tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from e2e.webui.functional.manifest import ManifestError, load_inputs, load_manifest
from e2e.webui.functional.planner import (
    group_cases_by_cloud,
    parse_components,
    parse_experiments,
    parse_tags,
    plan_cases,
    plan_tag_cases,
)


def pytest_addoption(parser):
    group = parser.getgroup("chaosforge-e2e")
    group.addoption("--e2e-config", help="Path to a JSON or YAML E2E manifest.")
    group.addoption("--e2e-cloud", default="all", choices=("aws", "azure", "all"))
    group.addoption("--e2e-components", default="all", help="all or a comma-separated component list.")
    group.addoption(
        "--e2e-experiment",
        action="append",
        default=[],
        help="Repeatable COMPONENT:EXPERIMENT filter for tag-mode E2E runs.",
    )
    group.addoption("--e2e-mode", choices=("tags", "explicit"))
    group.addoption("--e2e-tag", action="append", default=[], help="Override tag selection with KEY=VALUE.")
    group.addoption("--e2e-aws-region", help="AWS region for manifest-free tag mode.")
    group.addoption(
        "--e2e-azure-subscription",
        default=os.getenv("AZURE_SUBSCRIPTION_ID", ""),
        help="Azure subscription ID for tag-mode SDK discovery.",
    )
    group.addoption("--e2e-inputs", help="Optional JSON/YAML values file for tag-mode experiments.")
    group.addoption("--e2e-aws-fis-role-arn", help="AWS IAM role ARN assumed by AWS FIS experiments.")
    group.addoption("--e2e-azure-chaos-identity", help="Azure Chaos Studio user-assigned identity resource ID.")
    group.addoption("--e2e-vm-shutdown-duration", default="PT1M", help="ISO 8601 VM shutdown duration for tag mode.")
    group.addoption("--e2e-vm-abrupt-shutdown", action="store_true", help="Use abrupt shutdown for Azure VM tag-mode fault.")
    group.addoption("--e2e-execute", action="store_true", help="Opt into live fault execution.")
    group.addoption(
        "--e2e-execution-timeout-seconds",
        type=int,
        default=10800,
        help="Maximum seconds to wait for a live Web UI campaign to finish.",
    )
    group.addoption("--e2e-campaign-mode", default="isolated", choices=("isolated", "combined"))
    group.addoption("--e2e-strict-missing-resource", action="store_true")
    group.addoption("--e2e-strict-inputs", action="store_true")
    group.addoption("--e2e-skip-irreversible", action="store_true", help="Do not plan irreversible metadata experiments.")
    group.addoption("--e2e-base-url", default=os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000"))


def pytest_configure(config):
    config.addinivalue_line("markers", "functional: manifest-driven live Web UI functional tests")


def pytest_generate_tests(metafunc):
    mode = metafunc.config.getoption("e2e_campaign_mode")
    if "functional_case" in metafunc.fixturenames and mode == "isolated":
        metafunc.parametrize("functional_case", _planned_cases(metafunc.config), ids=_case_id)
    if "campaign_group" in metafunc.fixturenames and mode == "combined":
        groups = _planned_groups(metafunc.config)
        metafunc.parametrize("campaign_group", groups, ids=lambda group: group.id if group else "no-manifest")


def pytest_collection_modifyitems(config, items):
    mode = config.getoption("e2e_campaign_mode")
    selected = []
    deselected = []
    for item in items:
        if item.nodeid.startswith("e2e/webui/functional/test_functional_campaigns.py"):
            is_combined = item.name.startswith("test_functional_campaign_group")
            if is_combined != (mode == "combined"):
                deselected.append(item)
                continue
        selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def _case_id(case):
    return case.id if case is not None else "no-manifest"


def _planned_cases(pytestconfig):
    path = pytestconfig.getoption("e2e_config") or os.getenv("CHAOSFORGE_E2E_CONFIG")
    mode = pytestconfig.getoption("e2e_mode")
    tags = parse_tags(pytestconfig.getoption("e2e_tag"))
    if mode == "tags":
        try:
            inputs_path = pytestconfig.getoption("e2e_inputs")
            azure_subscription = pytestconfig.getoption("e2e_azure_subscription")
            if pytestconfig.getoption("e2e_cloud") in {"azure", "all"} and not azure_subscription:
                azure_subscription = _web_azure_subscription(pytestconfig.getoption("e2e_base_url"))
            return plan_tag_cases(
                cloud_filter=pytestconfig.getoption("e2e_cloud"),
                component_filter=parse_components(pytestconfig.getoption("e2e_components")),
                experiment_filter=parse_experiments(pytestconfig.getoption("e2e_experiment")),
                tags=tags,
                aws_region=pytestconfig.getoption("e2e_aws_region"),
                azure_subscription=azure_subscription,
                azure_chaos_identity=pytestconfig.getoption("e2e_azure_chaos_identity"),
                aws_fis_role_arn=pytestconfig.getoption("e2e_aws_fis_role_arn"),
                vm_shutdown_duration=pytestconfig.getoption("e2e_vm_shutdown_duration"),
                vm_abrupt_shutdown=pytestconfig.getoption("e2e_vm_abrupt_shutdown"),
                input_values=load_inputs(Path(inputs_path)) if inputs_path else None,
                strict_inputs=pytestconfig.getoption("e2e_strict_inputs"),
                execute_override=pytestconfig.getoption("e2e_execute"),
                skip_irreversible=pytestconfig.getoption("e2e_skip_irreversible"),
            )
        except ManifestError as exc:
            raise pytest.UsageError(str(exc)) from exc
    if mode == "explicit" and not path:
        raise pytest.UsageError("E2E explicit mode requires --e2e-config or CHAOSFORGE_E2E_CONFIG.")
    if not path:
        return [pytest.param(None, marks=pytest.mark.skip(
            reason="No E2E manifest configured. Tag mode requires --e2e-mode tags; explicit mode requires --e2e-config."
        ))]
    try:
        return plan_cases(
            load_manifest(Path(path)),
            cloud_filter=pytestconfig.getoption("e2e_cloud"),
            component_filter=parse_components(pytestconfig.getoption("e2e_components")),
            mode_override=mode,
            tag_override=tags,
            execute_override=pytestconfig.getoption("e2e_execute"),
            aws_fis_role_arn=pytestconfig.getoption("e2e_aws_fis_role_arn"),
        )
    except ManifestError as exc:
        raise pytest.UsageError(str(exc)) from exc


def _web_azure_subscription(base_url):
    url = f"{base_url.rstrip('/')}/api/cloud-identity/azure"
    try:
        with urlopen(url, timeout=10) as response:  # noqa: S310 - developer-supplied local E2E URL.
            identity = json.loads(response.read())
    except (URLError, ValueError) as exc:
        raise ManifestError(f"Could not read Azure identity from running ChaosForge Web UI: {exc}") from exc
    if not identity.get("authenticated") or not identity.get("subscription_id"):
        raise ManifestError("The running ChaosForge Web UI is not authenticated to an Azure subscription.")
    return str(identity["subscription_id"])


def _planned_groups(pytestconfig):
    mode = pytestconfig.getoption("e2e_mode")
    path = pytestconfig.getoption("e2e_config") or os.getenv("CHAOSFORGE_E2E_CONFIG")
    if mode != "tags" and not path:
        return [pytest.param(None, marks=pytest.mark.skip(
            reason="No E2E manifest configured. Tag mode requires --e2e-mode tags; explicit mode requires --e2e-config."
        ))]
    cases = _planned_cases(pytestconfig)
    return group_cases_by_cloud(cases)


@pytest.fixture(scope="session")
def e2e_base_url(pytestconfig):
    base_url = pytestconfig.getoption("e2e_base_url").rstrip("/")
    try:
        with urlopen(base_url, timeout=5) as response:  # noqa: S310 - developer-supplied local E2E URL.
            if response.status >= 400:
                pytest.fail(f"ChaosForge Web UI is unhealthy at {base_url}: HTTP {response.status}.")
    except URLError as exc:
        pytest.fail(
            f"ChaosForge Web UI is unavailable at {base_url}. Start it with `chaosforge-web` "
            f"or pass --e2e-base-url for the running instance. Details: {exc.reason}"
        )
    return base_url
