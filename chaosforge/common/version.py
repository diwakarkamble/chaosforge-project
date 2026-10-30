"""Canonical ChaosForge version lookup for source and installed executions."""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path


def chaosforge_version():
    """Return the installed package version or the source-tree version for development."""
    try:
        return distribution_version("chaosforge")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
