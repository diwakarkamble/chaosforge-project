import importlib
from types import SimpleNamespace

import pytest

from e2e.webui.targeted.execution_helpers import validate_campaign_review


def test_review_accepts_exact_expected_experiment():
    validate_campaign_review(
        {"experiments": [{"service": "s3", "id": "s3-versioning"}]},
        "s3",
        "s3-versioning",
    )


@pytest.mark.parametrize(
    "experiments",
    [
        [],
        [
            {"service": "s3", "id": "s3-versioning"},
            {"service": "ec2", "id": "stop-instance"},
        ],
        [{"service": "ec2", "id": "stop-instance"}],
        None,
    ],
)
def test_review_rejects_non_isolated_or_mismatched_campaign(experiments):
    with pytest.raises(AssertionError, match="Refusing execution"):
        validate_campaign_review(
            {"experiments": experiments}, "s3", "s3-versioning"
        )


def test_review_rejects_missing_identity_field():
    with pytest.raises(AssertionError, match="Refusing execution"):
        validate_campaign_review({"report": {}}, "s3", "s3-versioning")


def test_permission_review_returns_selected_experiment_identity(monkeypatch):
    web_app = importlib.import_module("chaosforge.interfaces.web.app")
    safety = importlib.import_module("chaosforge.application.safety")

    campaign = SimpleNamespace(
        cloud_provider="aws",
        experiments=[
            SimpleNamespace(
                service="s3",
                id="s3-versioning",
                name="S3 Versioning",
            )
        ],
    )

    monkeypatch.setattr(
        web_app, "_campaign_for_permission_review",
        lambda cloud, selected: campaign,
    )
    monkeypatch.setattr(
        web_app.permission_reports, "generate", lambda selected_campaign: {}
    )
    monkeypatch.setattr(
        web_app, "_permission_review_token",
        lambda cloud, selected, requires_irreversible_acknowledgement:
            "test-review-token",
    )
    monkeypatch.setattr(
        safety, "irreversible_experiments", lambda selected_campaign: []
    )

    client = web_app.app.test_client()
    response = client.post(
        "/api/campaign/permissions",
        json={"cloud": "aws", "ids": [0]},
    )

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["experiments"] == [
        {
            "service": "s3",
            "id": "s3-versioning",
            "name": "S3 Versioning",
            "target": {},
            "fis_service_id": "",
            "fis_experiment_id": "",
        }
    ]
    assert body["review_token"] == "test-review-token"


def test_execute_selected_starts_only_reviewed_selection(monkeypatch):
    web_app = importlib.import_module("chaosforge.interfaces.web.app")
    campaign = SimpleNamespace(
        cloud_provider="aws",
        experiments=[
            SimpleNamespace(service="s3", id="s3-versioning", name="S3 Versioning")
        ],
    )
    calls = {}
    executor = SimpleNamespace(
        start=lambda submitted: calls.update(started=True, campaign=submitted) or "run-1",
    )

    monkeypatch.setattr(web_app, "_trusted_cloud", lambda cloud: cloud)
    monkeypatch.setattr(
        web_app,
        "_consume_permission_review_token",
        lambda token, cloud, selected: (
            calls.update(token=token, cloud=cloud, selected=selected) or True
        ),
    )
    monkeypatch.setattr(
        web_app,
        "_campaign_for_permission_review",
        lambda cloud, selected: campaign,
    )
    monkeypatch.setattr(web_app, "get_executor", lambda cloud: executor)
    monkeypatch.setattr(
        web_app, "_aws_execution_redirect", lambda run_id=None: "execution-started"
    )

    response = web_app.app.test_client().get(
        "/campaign/execute-selected",
        query_string={"cloud": "aws", "ids": "0", "review": "valid-token"},
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "execution-started"
    assert calls["selected"] == [0]
    assert calls["token"] == "valid-token"
    assert calls["started"] is True
    assert calls["campaign"] is campaign


def test_execute_selected_rejects_invalid_review_token(monkeypatch):
    web_app = importlib.import_module("chaosforge.interfaces.web.app")
    calls = {"started": False}

    monkeypatch.setattr(web_app, "_trusted_cloud", lambda cloud: cloud)
    monkeypatch.setattr(
        web_app, "_consume_permission_review_token",
        lambda token, cloud, selected: False,
    )
    monkeypatch.setattr(
        web_app, "_aws_campaign_redirect", lambda: "blocked"
    )
    monkeypatch.setattr(
        web_app, "get_executor",
        lambda cloud: calls.update(started=True),
    )

    response = web_app.app.test_client().get(
        "/campaign/execute-selected",
        query_string={"cloud": "aws", "ids": "0", "review": "invalid-token"},
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "blocked"
    assert calls["started"] is False
