import pytest

from e2e.webui.functional import resolution


def test_resolution_classifies_found_missing_and_ambiguous(monkeypatch):
    target = {"cloud": "aws", "target": {"Chaosforge": "E2E-Test"}}
    monkeypatch.setattr(resolution.aws, "resolve", lambda _: ("missing", [], "none"))
    assert resolution.resolve(target).status == "missing"

    monkeypatch.setattr(resolution.aws, "resolve", lambda _: ("found", [{"id": "one", "name": "one"}], ""))
    assert resolution.resolve(target).status == "found"

    monkeypatch.setattr(
        resolution.aws, "resolve", lambda _: ("ambiguous", [{"id": "one", "name": "one"}, {"id": "two", "name": "two"}], "many"),
    )
    assert resolution.resolve(target).status == "ambiguous"


@pytest.mark.parametrize(
    ("message", "status"),
    [
        ("Azure resource not found", "missing"),
        ("AWS static targeting does not support service", "unsupported"),
        ("AWS resource lookup failed", "environment_error"),
    ],
)
def test_resolution_classifies_existing_provider_errors(monkeypatch, message, status):
    monkeypatch.setattr(resolution.aws, "resolve", lambda _: (status, [], message))
    assert resolution.resolve({"cloud": "aws", "target": "resource"}).status == status
