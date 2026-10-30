"""GitLab-compatible JUnit XML reports for ChaosForge campaigns."""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_INVALID_XML = {character for character in range(32) if character not in {9, 10, 13}}


def generate_junit_report(campaign: Any, output_path: str | Path) -> Path:
    """Write one JUnit test suite containing a testcase per experiment."""
    experiments = list(getattr(campaign, "experiments", []))
    failures = sum(_status(experiment) == "FAILED" for experiment in experiments)
    skipped = sum(_status(experiment) == "SKIPPED" for experiment in experiments)
    duration = _seconds(getattr(campaign, "duration", 0))
    suite_name = f"ChaosForge: {getattr(campaign, 'name', 'Campaign')}"
    root = ET.Element(
        "testsuites",
        {
            "name": "ChaosForge",
            "tests": str(len(experiments)),
            "failures": str(failures),
            "skipped": str(skipped),
            "time": _time(duration),
        },
    )
    suite = ET.SubElement(
        root,
        "testsuite",
        {
            "name": suite_name,
            "tests": str(len(experiments)),
            "failures": str(failures),
            "skipped": str(skipped),
            "time": _time(duration),
        },
    )
    for experiment in experiments:
        _append_testcase(suite, experiment)
    return _write(output_path, root)


def generate_setup_failure_report(
    campaign_name: str,
    message: str,
    output_path: str | Path,
) -> Path:
    """Write a synthetic failed testcase when campaign execution cannot start."""
    root = ET.Element(
        "testsuites",
        {"name": "ChaosForge", "tests": "1", "failures": "1", "skipped": "0", "time": "0"},
    )
    suite = ET.SubElement(
        root,
        "testsuite",
        {
            "name": f"ChaosForge: {campaign_name or 'Campaign'}",
            "tests": "1",
            "failures": "1",
            "skipped": "0",
            "time": "0",
        },
    )
    case = ET.SubElement(
        suite,
        "testcase",
        {"classname": "chaosforge.campaign", "name": "Campaign setup", "time": "0"},
    )
    failure = ET.SubElement(case, "failure", {"message": str(message)})
    failure.text = str(message)
    return _write(output_path, root)


def _append_testcase(suite: ET.Element, experiment: Any) -> None:
    status = _status(experiment)
    duration = _seconds(getattr(experiment, "duration", 0))
    case = ET.SubElement(
        suite,
        "testcase",
        {
            "classname": f"chaosforge.{getattr(experiment, 'service', 'unknown')}",
            "name": str(getattr(experiment, "name", getattr(experiment, "id", "Experiment"))),
            "time": _time(duration),
        },
    )
    properties = ET.SubElement(case, "properties")
    for name, value in (
        ("chaosforge.experiment_id", getattr(experiment, "id", "")),
        ("chaosforge.service", getattr(experiment, "service", "")),
        ("chaosforge.engine", getattr(experiment, "engine", "")),
        ("chaosforge.outcome", status),
        ("chaosforge.reversibility", getattr(experiment, "reversibility", "")),
    ):
        ET.SubElement(properties, "property", {"name": name, "value": str(value)})
    if status == "FAILED":
        message = _xml_text(
            getattr(experiment, "error_message", "") or "Experiment failed."
        )
        failure = ET.SubElement(case, "failure", {"message": message})
        failure.text = message
    elif status == "SKIPPED":
        ET.SubElement(case, "skipped", {"message": "Experiment was skipped."})
    output = _system_output(experiment)
    if output:
        ET.SubElement(case, "system-out").text = _xml_text(output)


def _system_output(experiment: Any) -> str:
    parts = []
    warnings = getattr(experiment, "warnings", []) or []
    if warnings:
        parts.append("Warnings:\n" + "\n".join(_warning_text(warning) for warning in warnings))
    cli_output = getattr(experiment, "cli_output", "")
    if isinstance(cli_output, str) and cli_output:
        parts.append(cli_output)
    return "\n\n".join(parts)


def _warning_text(warning: Any) -> str:
    if isinstance(warning, dict):
        return str(warning.get("detail") or warning.get("message") or warning)
    return str(warning)


def _xml_text(value: Any) -> str:
    return str(value).translate({character: None for character in _INVALID_XML})


def _status(experiment: Any) -> str:
    value = getattr(experiment, "status", "FAILED")
    return str(getattr(value, "value", value)).upper()


def _seconds(value: Any) -> float:
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _time(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _write(output_path: str | Path, root: ET.Element) -> Path:
    path = Path(output_path).expanduser()
    if not path.name:
        raise ValueError("JUnit output path must include a file name.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
