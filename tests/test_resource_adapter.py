from typing import Any

import pytest

from chaosforge.lifecycle.checks.adapter import ResourceAdapter


class DummyResourceAdapter(ResourceAdapter):
    name = "dummy-resource"

    def capture(self, target: dict[str, Any]) -> dict[str, Any]:
        return {
            "exists": True,
            "identity": {
                "id": target["id"],
                "name": "demo",
                "type": "dummy",
            },
            "state": {
                "status": "running",
            },
            "configuration": {
                "size": 10,
            },
            "health": {
                "healthy": True,
            },
            "metadata": {
                "region": "us-east-1",
            },
        }


def test_resource_adapter_capture():
    adapter = DummyResourceAdapter()

    result = adapter.capture({"id": "resource-1"})

    assert result["exists"] is True
    assert result["identity"]["id"] == "resource-1"
    assert result["identity"]["name"] == "demo"
    assert result["state"]["status"] == "running"
    assert result["configuration"]["size"] == 10
    assert result["health"]["healthy"] is True
    assert result["metadata"]["region"] == "us-east-1"


def test_resource_adapter_is_abstract():
    with pytest.raises(TypeError):
        ResourceAdapter()
