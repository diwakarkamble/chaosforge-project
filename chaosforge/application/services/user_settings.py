"""Local presentation preferences shared by the CLI and Web interface."""

import json
import os
import tempfile
from datetime import datetime, timezone
from threading import Lock
from zoneinfo import ZoneInfo

from chaosforge.common.paths import repository_paths

DEFAULT_TIMEZONE = "Europe/Berlin"
TIMEZONES = (
    ("UTC", "Coordinated Universal Time"),
    ("Europe/Berlin", "Central European Time, Berlin"),
    ("Europe/London", "United Kingdom Time, London"),
    ("America/New_York", "Eastern Time, New York"),
    ("America/Los_Angeles", "Pacific Time, Los Angeles"),
    ("Africa/Johannesburg", "South Africa Standard Time, Johannesburg"),
    ("Asia/Dubai", "Gulf Standard Time, Dubai"),
    ("Asia/Kolkata", "India Standard Time, Kolkata"),
    ("Asia/Shanghai", "China Standard Time, Shanghai/Beijing"),
    ("Asia/Singapore", "Singapore Standard Time"),
    ("Asia/Tokyo", "Japan Standard Time, Tokyo"),
    ("Australia/Sydney", "Australian Eastern Time, Sydney"),
)
_TIMEZONE_IDS = frozenset(item[0] for item in TIMEZONES)
_SETTINGS_LOCK = Lock()


def _settings_path():
    return repository_paths().settings


def get_timezone_id():
    """Return the configured timezone or the safe geographic default."""
    with _SETTINGS_LOCK:
        try:
            with open(_settings_path(), encoding="utf-8") as handle:
                timezone_id = json.load(handle).get("timezone")
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return DEFAULT_TIMEZONE
    return timezone_id if timezone_id in _TIMEZONE_IDS else DEFAULT_TIMEZONE


def set_timezone_id(timezone_id):
    """Persist a curated IANA timezone atomically."""
    if timezone_id not in _TIMEZONE_IDS:
        raise ValueError("Select a supported timezone.")

    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _SETTINGS_LOCK:
        descriptor, temporary_path = tempfile.mkstemp(dir=path.parent, prefix=".settings-", text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "timezone": timezone_id}, handle)
            os.replace(temporary_path, path)
        except Exception:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
            raise


def get_timezone(timezone_id=None):
    return ZoneInfo(timezone_id or get_timezone_id())


def format_timezone(timezone_id=None, when=None):
    timezone_id = timezone_id or get_timezone_id()
    current = (when or datetime.now(timezone.utc)).astimezone(get_timezone(timezone_id))
    offset = current.strftime("%z")
    return f"{timezone_id} ({current.tzname()}, UTC{offset[:3]}:{offset[3:]})"


def format_timezone_offset(timezone_id=None, when=None):
    current = (when or datetime.now(timezone.utc)).astimezone(
        get_timezone(timezone_id)
    )
    offset = current.strftime("%z")
    return f"UTC{offset[:3]}:{offset[3:]}"


def is_supported_timezone(timezone_id):
    return timezone_id in _TIMEZONE_IDS


def timezone_options(when=None):
    return tuple(
        {
            "id": timezone_id,
            "label": label,
            "display": f"{label} ({format_timezone(timezone_id, when)})",
        }
        for timezone_id, label in TIMEZONES
    )
