"""Structured cloud lookup outcomes used by the functional E2E runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from e2e.webui.functional.providers import aws, azure


@dataclass(frozen=True)
class Resolution:
    status: str
    resources: list[dict[str, str]]
    reason: str = ""
    fields: dict[str, dict[str, str]] | None = None


def resolve(target: dict[str, Any]) -> Resolution:
    resource_fields = target.get("resource_fields") or []
    if resource_fields:
        provider = aws if target["cloud"] == "aws" else azure
        status, fields, reason = provider.resolve_graph(target, resource_fields)
        resources = [fields[resource_fields[0]["name"]]] if fields else []
        return Resolution(status, resources, reason, fields)
    status, resources, reason = (aws.resolve(target) if target["cloud"] == "aws" else azure.resolve(target))
    return Resolution(status, resources, reason)
