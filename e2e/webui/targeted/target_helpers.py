"""Shared static-E2E target validation and exact UI selection.

Keep cloud API discovery in providers/aws.py and providers/azure.py; keep the
Playwright runner cloud-neutral. Existing dynamic E2E tests should not import
this module unless they explicitly opt into targeted mode.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from e2e.webui.targeted.providers.aws import resolve_aws_targets
from e2e.webui.targeted.providers.azure import resolve_azure_targets

CONFIG_PATH = Path(__file__).with_name("targets.json")
SUPPORTED_TYPES = {"name", "resource_id", "tags"}
SUPPORTED_CLOUDS = {"aws", "azure"}


def expand_env_vars(data: Any) -> Any:
    """Recursively resolves ${VAR_NAME} environment variable placeholders in config strings."""
    if isinstance(data, str):
        # Match complete pattern like ${MY_VAR}
        full_match = re.fullmatch(r"\$\{([^}]+)\}", data.strip())
        if full_match:
            var_name = full_match.group(1)
            return os.getenv(var_name, "").strip()
        # Handle inline occurrences inside string templates
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.getenv(m.group(1), "").strip(), data)
    elif isinstance(data, dict):
        return {k: expand_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [expand_env_vars(item) for item in data]
    return data


def normalize(value: Any) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def load_target(key: str) -> dict[str, Any]:
    try:
        raw_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        pytest.fail(f"Unable to load targeted E2E configuration: {exc}")

    # Dynamically expand any ${ENV_VAR} placeholders across the entire config file
    config = expand_env_vars(raw_config)

    target = config.get(key)
    if not target or not target.get("enabled", False):
        pytest.skip(f"Targeted E2E target '{key}' is disabled.")

    required = ("cloud", "service", "experiment", "target_type", "target", "selector")
    missing = [field for field in required if target.get(field) in (None, "", {})]
    if missing:
        pytest.fail(f"Target '{key}' missing fields: {', '.join(missing)}")

    cloud = str(target["cloud"]).lower()
    if cloud not in SUPPORTED_CLOUDS:
        pytest.fail(f"Unsupported cloud '{cloud}'. Supported: {sorted(SUPPORTED_CLOUDS)}")
    target["cloud"] = cloud

    if target["target_type"] not in SUPPORTED_TYPES:
        pytest.fail(f"Unsupported target_type '{target['target_type']}'.")
    if target["target_type"] == "tags":
        if not isinstance(target["target"], dict) or not target["target"]:
            pytest.fail("Tag targeting requires a non-empty tag key/value dictionary.")
        if not target.get("resource_type"):
            pytest.fail("Tag targeting requires resource_type to scope lookup to one service.")
    if cloud == "aws" and not target.get("region"):
        pytest.fail("AWS targets require an explicit region.")
    return target


def resolve_target_candidates(target: dict[str, Any]) -> list[dict[str, str]]:
    """Return exact provider-verified resources as {id, name} records."""
    if target["cloud"] == "aws":
        return resolve_aws_targets(target)
    if target["cloud"] == "azure":
        return resolve_azure_targets(target)
    pytest.fail(f"No target resolver registered for cloud {target['cloud']!r}.")


def select_exact_target(page, selector: str, target: dict[str, Any]) -> str:
    """Select exactly one UI option corresponding to a provider-verified target."""
    candidates = resolve_target_candidates(target)
    if not candidates:
        pytest.fail(f"No cloud resource matched configured target: {target['target']!r}")

    # Ambiguous tag selectors must fail closed. A targeted test never chooses the
    # first resource when several resources match the configured selector.
    if len(candidates) != 1:
        pytest.fail(
            f"Target must resolve to exactly one cloud resource; got {len(candidates)}. "
            f"Matches={[item['id'] for item in candidates]}"
        )

    resource = candidates[0]
    accepted = {normalize(resource.get("id")), normalize(resource.get("name"))} - {""}
    field = page.locator(selector)
    field.wait_for(state="visible", timeout=20000)

    def matching_options() -> list[str]:
        matches = []
        for option in field.locator("option").all():
            value = (option.get_attribute("value") or "").strip()
            label = option.inner_text().strip()
            if value and ({normalize(value), normalize(label)} & accepted):
                matches.append(value)
        return list(dict.fromkeys(matches))

    try:
        page.wait_for_function(
            """({selector, accepted}) => {
                const field = document.querySelector(selector);
                if (!field) return false;
                const norm = value => (value || '').trim().replace(/\\/$/, '').toLowerCase();
                return Array.from(field.options).some(o =>
                    accepted.includes(norm(o.value)) || accepted.includes(norm(o.textContent)));
            }""",
            arg={"selector": selector, "accepted": sorted(accepted)},
            timeout=30000,
        )
    except Exception as exc:
        pytest.fail(
            f"Cloud resource exists but is not offered by UI selector {selector!r}. "
            f"Expected resource name/ID: {resource}. Details: {exc}"
        )

    matches = matching_options()
    if len(matches) != 1:
        pytest.fail(
            f"Expected exactly one UI option for cloud resource {resource}; "
            f"found {matches!r}. Refusing ambiguous selection."
        )
    field.select_option(matches[0])
    selected = field.input_value()
    if normalize(selected) != normalize(matches[0]):
        pytest.fail(f"UI selection verification failed: expected {matches[0]!r}, got {selected!r}.")
    return selected