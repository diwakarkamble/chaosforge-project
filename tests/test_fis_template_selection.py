from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.interfaces.cli.interactive import input_engine
from chaosforge.interfaces.web import app as web_app


@pytest.fixture
def client():
    web_app.app.config.update(TESTING=True)
    return web_app.app.test_client()


def test_cli_selects_existing_fis_template(monkeypatch):
    templates = [{"id": "tpl-1", "description": "Restart database"}]
    monkeypatch.setattr(
        "chaosforge.providers.aws.fis.service.FISService",
        MagicMock(return_value=SimpleNamespace(list_templates=lambda: templates)),
    )
    monkeypatch.setattr(input_engine, "menu", MagicMock())
    monkeypatch.setattr(input_engine, "get_input", MagicMock(return_value="1"))

    values = input_engine.collect_inputs(
        {
            "name": "Start FIS Template",
            "inputs": [
                {"name": "aws_region", "label": "AWS Region", "default": "eu-central-1"},
                {"name": "experiment_template_id", "label": "FIS Template", "type": "aws_fis_template", "required": True},
            ],
        }
    )

    assert values["experiment_template_id"] == "tpl-1"


def test_cli_rejects_empty_or_invalid_fis_template_selection(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr("chaosforge.providers.aws.fis.service.FISService", service)
    monkeypatch.setattr(input_engine, "error", MagicMock())
    metadata = {"name": "Start", "inputs": [{"name": "template_id", "label": "Template", "type": "aws_fis_template", "required": True}]}
    service.return_value.list_templates.return_value = []
    assert input_engine.collect_inputs(metadata) is None

    service.return_value.list_templates.return_value = [{"id": "tpl-1", "description": ""}]
    monkeypatch.setattr(input_engine, "menu", MagicMock())
    monkeypatch.setattr(input_engine, "get_input", MagicMock(return_value="bad"))
    assert input_engine.collect_inputs(metadata) is None


def test_web_fis_template_endpoint_returns_account_templates(client, monkeypatch):
    service = MagicMock()
    service.list_templates.return_value = [{"id": "tpl-1", "description": "Restart database"}]
    monkeypatch.setattr(web_app, "FISService", MagicMock(return_value=service))

    response = client.get("/api/fis/templates/eu-central-1")

    assert response.status_code == 200
    assert response.json == [{"id": "tpl-1", "description": "Restart database"}]
    web_app.FISService.assert_called_once_with("eu-central-1")


def test_web_fis_template_endpoint_returns_provider_error(client, monkeypatch):
    monkeypatch.setattr(web_app, "FISService", MagicMock(side_effect=RuntimeError("access denied")))

    response = client.get("/api/fis/templates/eu-central-1")

    assert response.status_code == 400
    assert response.json["error"] == "access denied"
