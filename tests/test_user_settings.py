from datetime import datetime, timezone

import pytest

from chaosforge.application.services import user_settings


def _settings_path(monkeypatch, tmp_path):
    path = tmp_path / "runtime" / "settings.json"
    monkeypatch.setattr(user_settings, "_settings_path", lambda: path)
    return path


def test_missing_settings_uses_berlin_default(monkeypatch, tmp_path):
    _settings_path(monkeypatch, tmp_path)

    assert user_settings.get_timezone_id() == "Europe/Berlin"


def test_timezone_setting_persists_and_formats_shanghai(monkeypatch, tmp_path):
    path = _settings_path(monkeypatch, tmp_path)

    user_settings.set_timezone_id("Asia/Shanghai")

    assert path.read_text(encoding="utf-8") == '{"version": 1, "timezone": "Asia/Shanghai"}'
    assert user_settings.get_timezone_id() == "Asia/Shanghai"
    assert user_settings.format_timezone(
        "Asia/Shanghai", datetime(2026, 1, 1, tzinfo=timezone.utc)
    ) == "Asia/Shanghai (CST, UTC+08:00)"


def test_invalid_or_malformed_setting_uses_default(monkeypatch, tmp_path):
    path = _settings_path(monkeypatch, tmp_path)
    path.parent.mkdir()
    path.write_text('{"timezone": "Mars/Olympus"}', encoding="utf-8")

    assert user_settings.get_timezone_id() == user_settings.DEFAULT_TIMEZONE

    path.write_text("not-json", encoding="utf-8")
    assert user_settings.get_timezone_id() == user_settings.DEFAULT_TIMEZONE


def test_setting_rejects_timezone_outside_curated_catalog(monkeypatch, tmp_path):
    _settings_path(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="supported timezone"):
        user_settings.set_timezone_id("Mars/Olympus")


def test_setting_removes_temporary_file_when_atomic_replace_fails(monkeypatch, tmp_path):
    _settings_path(monkeypatch, tmp_path)
    monkeypatch.setattr(user_settings.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        user_settings.set_timezone_id("Asia/Shanghai")

    assert list((tmp_path / "runtime").glob(".settings-*")) == []


def test_timezone_options_reflect_historical_berlin_dst(monkeypatch, tmp_path):
    _settings_path(monkeypatch, tmp_path)

    winter = user_settings.format_timezone("Europe/Berlin", datetime(2026, 1, 1, tzinfo=timezone.utc))
    summer = user_settings.format_timezone("Europe/Berlin", datetime(2026, 7, 1, tzinfo=timezone.utc))

    assert winter == "Europe/Berlin (CET, UTC+01:00)"
    assert summer == "Europe/Berlin (CEST, UTC+02:00)"


def test_timezone_offset_is_compact_for_web_display(monkeypatch, tmp_path):
    _settings_path(monkeypatch, tmp_path)

    assert user_settings.format_timezone_offset(
        "Asia/Shanghai", datetime(2026, 1, 1, tzinfo=timezone.utc)
    ) == "UTC+08:00"
