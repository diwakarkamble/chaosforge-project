import sys
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli import main as cli
from chaosforge.models import Campaign, Experiment


def test_yaml_run_writes_junit_for_completed_mixed_campaign(tmp_path, monkeypatch):
    campaign = Campaign(
        name="Mixed",
        experiments=[
            Experiment("passed", "lambda", "Passed", "", {}, status="SUCCESS"),
            Experiment("failed", "lambda", "Failed", "", {}, status="FAILED"),
            Experiment("skipped", "lambda", "Skipped", "", {}, status="SKIPPED"),
        ],
    )
    output = tmp_path / "junit.xml"
    monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", lambda _: campaign)
    monkeypatch.setattr(
        cli,
        "PlanService",
        lambda: SimpleNamespace(
            plan_campaign=lambda _: SimpleNamespace(executable=True, blockers=[])
        ),
    )
    monkeypatch.setattr(cli, "display_campaign_plan", MagicMock())
    monkeypatch.setattr(
        cli,
        "execute_lifecycle_campaign",
        lambda _: SimpleNamespace(status="FAILED"),
    )
    monkeypatch.setattr(cli, "generate_report", MagicMock(return_value="report.txt"))
    monkeypatch.setattr(cli.campaign_history, "start_execution", MagicMock(return_value="execution"))
    monkeypatch.setattr(cli.campaign_history, "finish_execution", MagicMock())

    assert cli.execute_yaml_campaign("campaign.yaml", junit_output=output) == 0
    root = ET.parse(output).getroot()
    assert root.attrib["tests"] == "3"
    assert root.attrib["failures"] == "1"
    assert root.attrib["skipped"] == "1"


@pytest.mark.parametrize("failure", ["validation", "irreversible", "planning", "blocked"])
def test_yaml_run_writes_setup_failure_junit(tmp_path, monkeypatch, failure):
    output = tmp_path / f"{failure}.xml"
    campaign = Campaign(name="Campaign")
    if failure == "validation":
        monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", lambda _: None)
    else:
        if failure == "irreversible":
            campaign.experiments = [
                Experiment("azure-redis-flush", "azure_redis", "Flush", "", {})
            ]
        monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", lambda _: campaign)
    if failure == "planning":
        monkeypatch.setattr(
            cli,
            "PlanService",
            lambda: SimpleNamespace(
                plan_campaign=lambda _: (_ for _ in ()).throw(RuntimeError("planner failed"))
            ),
        )
    elif failure == "blocked":
        monkeypatch.setattr(
            cli,
            "PlanService",
            lambda: SimpleNamespace(
                plan_campaign=lambda _: SimpleNamespace(
                    executable=False, blockers=["target unavailable"]
                )
            ),
        )

    assert cli.execute_yaml_campaign("campaign.yaml", junit_output=output) == 1
    failure_node = ET.parse(output).getroot().find("testsuite/testcase/failure")
    assert failure_node is not None


def test_yaml_run_writes_setup_failure_when_execution_raises(tmp_path, monkeypatch):
    output = tmp_path / "exception.xml"
    campaign = Campaign(name="Campaign")
    monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", lambda _: campaign)
    monkeypatch.setattr(
        cli,
        "PlanService",
        lambda: SimpleNamespace(
            plan_campaign=lambda _: SimpleNamespace(executable=True, blockers=[])
        ),
    )
    monkeypatch.setattr(cli, "display_campaign_plan", MagicMock())
    monkeypatch.setattr(cli, "execute_lifecycle_campaign", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(cli.campaign_history, "start_execution", MagicMock(return_value="execution"))
    monkeypatch.setattr(cli.campaign_history, "finish_execution", MagicMock())

    with pytest.raises(RuntimeError, match="boom"):
        cli.execute_yaml_campaign("campaign.yaml", junit_output=output)
    assert "boom" in ET.parse(output).getroot().findtext("testsuite/testcase/failure")


def test_main_forwards_junit_output_only_to_run(monkeypatch):
    run = MagicMock(return_value=0)
    monkeypatch.setattr(cli, "execute_yaml_campaign", run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["chaosforge", "run", "campaign.yaml", "--junit-output", "junit.xml"],
    )

    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    run.assert_called_once_with("campaign.yaml", junit_output="junit.xml")

    monkeypatch.setattr(
        sys,
        "argv",
        ["chaosforge", "validate", "campaign.yaml", "--junit-output", "junit.xml"],
    )
    with pytest.raises(SystemExit) as invalid:
        cli.main()
    assert invalid.value.code == 2
