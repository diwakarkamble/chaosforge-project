"""Load and validate developer-supplied Web UI functional-test manifests."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_CLOUDS = {"aws", "azure"}
SUPPORTED_MODES = {"tags", "explicit"}


class ManifestError(ValueError):
    """The developer-provided E2E manifest is invalid."""


def expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{([^}]+)\}", lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, list):
        return [expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_environment(item) for key, item in value.items()}
    return value


def load_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"Unable to read E2E manifest {source}: {exc}") from exc
    try:
        raw = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ManifestError(f"Unable to parse E2E manifest {source}: {exc}") from exc
    manifest = expand_environment(raw)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ManifestError("E2E manifest must be an object with version: 1.")
    components = manifest.get("components")
    if not isinstance(components, dict) or not components:
        raise ManifestError("E2E manifest must define non-empty components.")
    for cloud, services in components.items():
        if cloud not in SUPPORTED_CLOUDS:
            raise ManifestError(f"Unsupported E2E cloud {cloud!r}.")
        if not isinstance(services, dict) or not services:
            raise ManifestError(f"E2E cloud {cloud!r} must define components.")
        for service, config in services.items():
            _validate_component(cloud, service, config, manifest.get("defaults") or {})
    return manifest


def load_inputs(path: str | Path) -> dict[str, Any]:
    """Load optional tag-mode values without accepting resource selection data."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"Unable to read E2E inputs file {source}: {exc}") from exc
    try:
        raw = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ManifestError(f"Unable to parse E2E inputs file {source}: {exc}") from exc
    inputs = expand_environment(raw)
    if not isinstance(inputs, dict) or inputs.get("version") != 1:
        raise ManifestError("E2E inputs file must be an object with version: 1.")
    if inputs.get("defaults") is not None and not isinstance(inputs["defaults"], dict):
        raise ManifestError("E2E inputs defaults must be an object.")
    components = inputs.get("components", {})
    if not isinstance(components, dict):
        raise ManifestError("E2E inputs components must be an object.")
    for component, config in components.items():
        experiments = config.get("experiments") if isinstance(config, dict) else None
        if not isinstance(experiments, dict):
            raise ManifestError(f"E2E inputs component {component!r} requires experiments object.")
        if any(not isinstance(values, dict) for values in experiments.values()):
            raise ManifestError(f"E2E inputs component {component!r} experiment values must be objects.")
    return {"defaults": inputs.get("defaults", {}), "components": components}


def _validate_component(cloud: str, service: str, config: Any, defaults: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ManifestError(f"E2E component {cloud}/{service} must be an object.")
    if not config.get("selector"):
        raise ManifestError(f"E2E component {cloud}/{service} requires selector.")
    if not config.get("target_variable"):
        raise ManifestError(f"E2E component {cloud}/{service} requires target_variable.")
    if not isinstance(config.get("experiments"), list) or not config["experiments"]:
        raise ManifestError(f"E2E component {cloud}/{service} requires experiments.")
    if config.get("inputs") is not None and not isinstance(config["inputs"], dict):
        raise ManifestError(f"E2E component {cloud}/{service} inputs must be an object.")
    mode = config.get("mode", defaults.get("mode", "tags"))
    if mode not in SUPPORTED_MODES:
        raise ManifestError(f"E2E component {cloud}/{service} has unsupported mode {mode!r}.")
    if cloud == "aws" and not config.get("region"):
        raise ManifestError(f"E2E AWS component {service} requires region.")
    if cloud == "azure" and not config.get("resource_type"):
        raise ManifestError(f"E2E Azure component {service} requires resource_type.")
    if mode == "explicit" and not config.get("resources"):
        raise ManifestError(f"E2E explicit component {cloud}/{service} requires resources.")
