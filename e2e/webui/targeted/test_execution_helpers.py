from unittest.mock import Mock

import pytest

from e2e.webui.targeted.execution_helpers import wait_for_execution


def response(status_code, payload):
    result = Mock()
    result.status = status_code
    result.ok = 200 <= status_code < 400
    result.json.return_value = payload
    result.text.return_value = str(payload)
    return result


def test_wait_for_execution_returns_success(monkeypatch):
    page = Mock()
    page.request.get.return_value = response(
        200,
        {
            "run_id": "execution-123",
            "status": "SUCCESS",
            "completed": True,
            "completed_at": "2026-10-12T10:00:00Z",
            "progress": {"current": 1, "total": 1},
            "experiments": {},
        },
    )

    result = wait_for_execution(
        page, "http://localhost:5000", "aws", "execution-123"
    )

    assert result["status"] == "SUCCESS"
    page.request.get.assert_called_once()


def test_wait_for_execution_rejects_failed_execution():
    page = Mock()
    page.request.get.side_effect = [
        response(
        200,
        {
            "run_id": "execution-456",
            "status": "FAILED",
            "completed": True,
            "completed_at": "2026-10-12T10:00:00Z",
            "progress": {},
            "experiments": {},
        },
        ),
        response(200, ["Chaos Toolkit failure: provider error"]),
    ]

    with pytest.raises(AssertionError, match="provider error"):
        wait_for_execution(
            page, "http://localhost:5000", "aws", "execution-456"
        )


def test_wait_for_execution_rejects_http_error():
    page = Mock()
    page.request.get.return_value = response(500, {"error": "server error"})

    with pytest.raises(AssertionError, match="HTTP 500"):
        wait_for_execution(
            page, "http://localhost:5000", "aws", "execution-789"
        )
