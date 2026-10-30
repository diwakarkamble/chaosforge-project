from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli import main as cli


@pytest.fixture(autouse=True)
def restore_cli_context():
    original = vars(cli.context).copy()
    yield
    vars(cli.context).clear()
    vars(cli.context).update(original)


def test_mission_control_shows_no_active_campaign_without_a_draft(monkeypatch):
    monkeypatch.setattr(cli, "_active_campaign", lambda: SimpleNamespace(name="Default Campaign", campaign_id=None))

    assert cli._active_campaign_name() == "No active campaign"


def test_mission_control_shows_the_open_draft_name(monkeypatch):
    monkeypatch.setattr(cli, "_active_campaign", lambda: SimpleNamespace(name="Release validation", campaign_id="campaign-1"))

    assert cli._active_campaign_name() == "Release validation"


def test_create_chaos_campaign_opens_the_named_draft_library_then_service_selection(monkeypatch):
    platform = MagicMock(select=MagicMock(return_value="azure"))
    library = MagicMock(return_value=True)
    add_experiment = MagicMock()
    monkeypatch.setattr(cli, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(cli, "get_cloud_identity", MagicMock(return_value={}))
    monkeypatch.setattr(cli, "render_main_menu", MagicMock())
    monkeypatch.setattr(cli, "clear_screen", MagicMock())
    monkeypatch.setattr(cli, "print_banner", MagicMock())
    monkeypatch.setattr(cli, "dashboard", MagicMock())
    monkeypatch.setattr(cli, "title", MagicMock())
    monkeypatch.setattr(cli, "console", MagicMock())
    monkeypatch.setattr(cli, "campaign_library", library)
    monkeypatch.setattr(cli, "add_experiment", add_experiment)
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["1", "0"]))
    monkeypatch.setattr(cli, "sys", SimpleNamespace(exit=lambda *_: (_ for _ in ()).throw(SystemExit())))

    try:
        cli.interactive_main()
    except SystemExit:
        pass

    library.assert_called_once_with()
    add_experiment.assert_called_once_with()


def test_create_chaos_campaign_does_not_open_service_selection_after_library_back(monkeypatch):
    platform = MagicMock(select=MagicMock(return_value="azure"))
    library = MagicMock(return_value=False)
    add_experiment = MagicMock()
    monkeypatch.setattr(cli, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(cli, "get_cloud_identity", MagicMock(return_value={}))
    monkeypatch.setattr(cli, "render_main_menu", MagicMock())
    monkeypatch.setattr(cli, "clear_screen", MagicMock())
    monkeypatch.setattr(cli, "print_banner", MagicMock())
    monkeypatch.setattr(cli, "dashboard", MagicMock())
    monkeypatch.setattr(cli, "title", MagicMock())
    monkeypatch.setattr(cli, "console", MagicMock())
    monkeypatch.setattr(cli, "campaign_library", library)
    monkeypatch.setattr(cli, "add_experiment", add_experiment)
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["1", "0"]))
    monkeypatch.setattr(cli, "sys", SimpleNamespace(exit=lambda *_: (_ for _ in ()).throw(SystemExit())))

    try:
        cli.interactive_main()
    except SystemExit:
        pass

    library.assert_called_once_with()
    add_experiment.assert_not_called()


@pytest.mark.parametrize(
    ("cloud", "expected_message"),
    [
        ("aws", "Log in to Amazon Web Services before creating or opening campaigns."),
        ("azure", "Log in to Microsoft Azure before creating or opening campaigns."),
    ],
)
def test_campaign_library_requires_cloud_login(monkeypatch, cloud, expected_message):
    cli.context.cloud = cloud
    cli.context.region = "eu-west-1" if cloud == "aws" else "azure"
    error = MagicMock()
    monkeypatch.setattr(cli, "get_cloud_identity", MagicMock(return_value={"authenticated": False}))
    monkeypatch.setattr(cli, "error", error)
    monkeypatch.setattr(cli, "pause", MagicMock())
    monkeypatch.setattr(cli, "list_campaign_drafts", MagicMock())

    assert cli.campaign_library() is False

    error.assert_called_once_with(expected_message)
    cli.list_campaign_drafts.assert_not_called()


def test_change_cloud_returns_to_provider_selection(monkeypatch):
    platform = MagicMock(select=MagicMock(side_effect=["aws", "azure"]))
    region = MagicMock(select=MagicMock(return_value="eu-west-1"))
    monkeypatch.setattr(cli, "PlatformSelector", MagicMock(return_value=platform))
    monkeypatch.setattr(cli, "RegionSelector", MagicMock(return_value=region))
    monkeypatch.setattr(cli, "get_cloud_identity", MagicMock(return_value={}))
    monkeypatch.setattr(cli, "get_timezone_id", MagicMock(return_value="Europe/Berlin"))
    monkeypatch.setattr(cli, "clear_screen", MagicMock())
    monkeypatch.setattr(cli, "print_banner", MagicMock())
    monkeypatch.setattr(cli, "dashboard", MagicMock())
    monkeypatch.setattr(cli, "title", MagicMock())
    monkeypatch.setattr(cli, "render_main_menu", MagicMock())
    monkeypatch.setattr(cli, "console", MagicMock())
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["14", "0"]))
    monkeypatch.setattr(cli, "sys", SimpleNamespace(exit=lambda *_: (_ for _ in ()).throw(SystemExit())))

    try:
        cli.interactive_main()
    except SystemExit:
        pass

    assert platform.select.call_count == 2
    region.select.assert_called_once_with()
    assert cli.context.cloud == "azure"
    assert cli.context.region == "azure"
