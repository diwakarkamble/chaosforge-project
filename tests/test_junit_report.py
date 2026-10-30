import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from chaosforge.models import Campaign, Experiment
from chaosforge.reporting.junit import (
    generate_junit_report,
    generate_setup_failure_report,
)


def _experiment(status, *, name="Experiment", warnings=None, error="", output=""):
    experiment = Experiment(
        "experiment-id",
        "azure_event_hub",
        name,
        "definition.json",
        {},
        engine="Azure SDK",
        status=status,
        warnings=warnings or [],
        reversibility="reversible",
    )
    experiment.duration = 12.5
    experiment.error_message = error
    experiment.cli_output = output
    return experiment


def test_junit_report_maps_campaign_outcomes_and_details(tmp_path):
    campaign = Campaign(
        name="Azure <resilience>",
        experiments=[
            _experiment("SUCCESS", name="Passed"),
            _experiment(
                "SUCCESS_WITH_WARNINGS",
                name="Warning",
                warnings=[{"detail": "advisory <finding>"}],
            ),
            _experiment("FAILED", name="Failed", error="provider & recovery failed", output="log\x00line"),
            _experiment("SKIPPED", name="Skipped"),
        ],
    )
    campaign.duration = 50
    path = generate_junit_report(campaign, tmp_path / "nested" / "junit.xml")

    root = ET.parse(path).getroot()
    suite = root.find("testsuite")
    assert root.attrib == {
        "name": "ChaosForge",
        "tests": "4",
        "failures": "1",
        "skipped": "1",
        "time": "50",
    }
    assert suite.attrib["name"] == "ChaosForge: Azure <resilience>"
    cases = {case.attrib["name"]: case for case in suite.findall("testcase")}
    assert cases["Passed"].find("failure") is None
    assert "advisory <finding>" in cases["Warning"].findtext("system-out")
    assert cases["Failed"].find("failure").attrib["message"] == "provider & recovery failed"
    assert "\x00" not in cases["Failed"].findtext("system-out")
    assert cases["Skipped"].find("skipped") is not None
    properties = {
        item.attrib["name"]: item.attrib["value"]
        for item in cases["Passed"].find("properties")
    }
    assert properties["chaosforge.engine"] == "Azure SDK"
    assert properties["chaosforge.reversibility"] == "reversible"


def test_junit_report_handles_missing_and_invalid_optional_values(tmp_path):
    experiment = SimpleNamespace(
        id="id",
        service="service",
        status="FAILED",
        duration="invalid",
        warnings=["warning"],
    )
    campaign = SimpleNamespace(name="Campaign", experiments=[experiment], duration=-1)

    path = generate_junit_report(campaign, tmp_path / "junit.xml")
    case = ET.parse(path).getroot().find("testsuite/testcase")

    assert case.attrib["name"] == "id"
    assert case.attrib["time"] == "0"
    assert case.find("failure").attrib["message"] == "Experiment failed."
    assert "warning" in case.findtext("system-out")


def test_setup_failure_report_is_a_single_failed_testcase(tmp_path):
    path = generate_setup_failure_report(
        "Broken campaign", "validation <failed>", tmp_path / "junit.xml"
    )

    root = ET.parse(path).getroot()
    case = root.find("testsuite/testcase")
    assert root.attrib["tests"] == "1"
    assert root.attrib["failures"] == "1"
    assert case.attrib["name"] == "Campaign setup"
    assert case.findtext("failure") == "validation <failed>"


def test_junit_output_requires_a_filename():
    with pytest.raises(ValueError, match="file name"):
        generate_setup_failure_report("Campaign", "failed", "")
