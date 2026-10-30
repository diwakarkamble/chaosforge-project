"""Azure target resolver using Azure CLI; supports Azure services by resource type."""
from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from chaosforge.common.azure_cli import azure_cli_command


def _run_az(args: list[str]) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            azure_cli_command(*args, "--output", "json"),
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.fail(f"Azure target lookup could not run Azure CLI: {exc}")
    if result.returncode:
        pytest.fail(
            "Azure target lookup failed. Verify `az login`, subscription access, "
            f"and resource permissions. Details: {result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        pytest.fail(f"Azure CLI returned invalid JSON: {exc}")
    if isinstance(payload, dict):
        return [payload]
    return payload


def resolve_azure_targets(target: dict[str, Any]) -> list[dict[str, str]]:
    resource_type = target.get("resource_type")
    if not resource_type:
        pytest.fail("Azure target configuration must specify resource_type.")

    args = ["resource", "list", "--resource-type", resource_type]
    if target.get("subscription_id"):
        args.extend(["--subscription", target["subscription_id"]])
    if target.get("resource_group") and not str(target["resource_group"]).startswith("REPLACE_WITH_"):
        args.extend(["--resource-group", target["resource_group"]])
    resources = _run_az(args)

    expected_type = str(resource_type).casefold()
    target_type = target["target_type"]
    expected = target["target"]
    matches = []
    for item in resources:
        rid = str(item.get("id", ""))
        name = str(item.get("name", ""))
        if str(item.get("type", expected_type)).casefold() != expected_type:
            continue
        if target_type == "name" and name.casefold() != str(expected).casefold():
            continue
        if target_type == "resource_id" and rid.rstrip("/").casefold() != str(expected).rstrip("/").casefold():
            continue
        if target_type == "tags":
            actual_tags = {str(k).casefold(): str(v).casefold() for k, v in (item.get("tags") or {}).items()}
            required_tags = {str(k).casefold(): str(v).casefold() for k, v in expected.items()}
            if not all(actual_tags.get(k) == v for k, v in required_tags.items()):
                continue
        if rid:
            matches.append({"id": rid, "name": name})

    if target_type != "tags" and not matches:
        pytest.fail(f"Azure resource not found for {target_type}={expected!r} ({resource_type}).")
    return matches
