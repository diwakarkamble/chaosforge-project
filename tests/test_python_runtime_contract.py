import re
import sys
import tomllib
from importlib.metadata import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_package_requires_python_314_and_ruff_targets_it():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    assert project["project"]["requires-python"] == ">=3.14"
    assert "Programming Language :: Python :: 3.14" in project["project"]["classifiers"]
    assert project["tool"]["ruff"]["target-version"] == "py314"


def test_installed_package_metadata_requires_python_314():
    assert metadata("chaosforge")["Requires-Python"] == ">=3.14"


def test_latest_runtime_dependency_contract():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "chaostoolkit==1.21.4" in requirements
    assert "chaostoolkit-lib==1.45.1" in requirements
    boto3 = re.search(r"^boto3==(\S+)$", requirements, re.MULTILINE)
    botocore = re.search(r"^botocore\[crt\]==(\S+)$", requirements, re.MULTILINE)
    assert boto3 and botocore
    assert boto3.group(1) == botocore.group(1)


def test_gitlab_ci_uses_python_314_and_enforces_coverage_floor():
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    assert re.search(
        r"image:\s+(?:\$\{CI_DEPENDENCY_PROXY_DIRECT_GROUP_IMAGE_PREFIX\}/)?python:3\.14",
        pipeline,
    )
    assert "--cov-fail-under=95" in pipeline
    assert "--cov-fail-under=100" not in pipeline
    assert "sys.version_info[:2] == (3, 14)" in pipeline


def test_active_documentation_requires_python_314():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/getting-started/installation.md").read_text(
        encoding="utf-8"
    )
    testing = (ROOT / "docs/validation/testing.md").read_text(encoding="utf-8")

    assert "Python 3.14 or newer" in readme
    assert "Python 3.14 or newer" in installation
    assert "--cov-fail-under=100" in testing
    assert "maintains 100% line coverage" in testing
    assert "python3.14 -m venv .venv && source .venv/bin/activate" in readme
    assert "Configuration Defaults And Validation" in readme
    assert "Configuration Defaults And Validation" in installation


@pytest.mark.skipif(sys.version_info < (3, 14), reason="requires the supported runtime")
def test_running_interpreter_meets_supported_minimum():
    assert sys.version_info >= (3, 14)
