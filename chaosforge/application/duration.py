"""ISO-8601 duration validation and conversion for local fault runners."""

import re

_DURATION = re.compile(
    r"^P(?=\d|T\d)(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)

LOCAL_DURATION_FIELDS = {"wait_seconds", "duration_seconds", "fault_duration_seconds"}


def duration_seconds(value):
    """Convert a valid ISO-8601 duration to whole seconds."""
    match = _DURATION.fullmatch(str(value).strip())
    if match is None:
        raise ValueError("Enter an ISO 8601 duration, for example PT5M or PT100S.")
    parts = {name: int(amount or 0) for name, amount in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def is_iso8601_duration(value):
    return _DURATION.fullmatch(str(value).strip()) is not None


def iso8601_duration(value):
    """Return a canonical ISO-8601 duration for a legacy numeric value."""
    if is_iso8601_duration(value):
        return str(value).strip()
    seconds = int(value)
    if seconds < 0:
        raise ValueError("Duration cannot be negative.")
    return f"PT{seconds}S"


def normalize_duration_fields(metadata):
    """Expose legacy local waits as ISO-8601 duration inputs to every interface."""
    for experiment in metadata.get("experiments", []):
        for field in experiment.get("inputs", []):
            if field.get("name") not in LOCAL_DURATION_FIELDS:
                continue
            field["type"] = "iso8601_duration"
            if "default" in field:
                field["default"] = iso8601_duration(field["default"])
    return metadata


def normalize_named_duration_field(metadata):
    """Expose a generic duration field as ISO-8601 for direct cluster engines."""
    for experiment in metadata.get("experiments", []):
        for field in experiment.get("inputs", []):
            if field.get("name") != "duration":
                continue
            field["type"] = "iso8601_duration"
            if "default" in field:
                value = field["default"]
                if isinstance(value, str) and value.endswith("s") and value[:-1].isdigit():
                    value = value[:-1]
                field["default"] = iso8601_duration(value)
    return metadata


def execution_variables(values):
    """Convert ISO duration fields to seconds only for local action definitions."""
    normalized = dict(values)
    for name in LOCAL_DURATION_FIELDS:
        if name in normalized and is_iso8601_duration(normalized[name]):
            normalized[name] = duration_seconds(normalized[name])
    return normalized
