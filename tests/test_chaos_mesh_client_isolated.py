import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


class ApiException(Exception):
    def __init__(self, status=None, reason=None):
        super().__init__(reason)
        self.status = status


def _install_kubernetes_stub():
    kubernetes = ModuleType("kubernetes")
    client = ModuleType("kubernetes.client")
    rest = ModuleType("kubernetes.client.rest")
    config = ModuleType("kubernetes.config")
    config_exception = ModuleType("kubernetes.config.config_exception")

    class ConfigException(Exception):
        pass

    client.ApiClient = MagicMock
    client.CustomObjectsApi = MagicMock
    client.V1DeleteOptions = MagicMock
    rest.ApiException = ApiException
    config.load_kube_config = MagicMock()
    config.load_incluster_config = MagicMock()
    config_exception.ConfigException = ConfigException
    kubernetes.client = client
    kubernetes.config = config

    return {
        "kubernetes": kubernetes,
        "kubernetes.client": client,
        "kubernetes.client.rest": rest,
        "kubernetes.config": config,
        "kubernetes.config.config_exception": config_exception,
    }, ConfigException


def test_client_loads_incluster_config_and_handles_wait_outcomes(monkeypatch):
    modules, config_exception = _install_kubernetes_stub()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "chaosforge.engines.chaos_mesh.chaos_mesh_client", raising=False)

    from chaosforge.engines.chaos_mesh.chaos_mesh_client import ChaosMeshClient

    api_client = MagicMock()
    custom_api = MagicMock()
    with patch("chaosforge.engines.chaos_mesh.chaos_mesh_client.config.load_kube_config", side_effect=config_exception("missing")), \
         patch("chaosforge.engines.chaos_mesh.chaos_mesh_client.config.load_incluster_config") as load_incluster, \
         patch("chaosforge.engines.chaos_mesh.chaos_mesh_client.client.ApiClient", return_value=api_client), \
         patch("chaosforge.engines.chaos_mesh.chaos_mesh_client.client.CustomObjectsApi", return_value=custom_api):
        assert ChaosMeshClient()._load_client() is custom_api

    load_incluster.assert_called_once_with()

    client = ChaosMeshClient(custom_objects_api=MagicMock())
    client.get = MagicMock(side_effect=ApiException(status=404))
    client.wait_for_deleted("PodChaos", "example", timeout_seconds=1, poll_interval_seconds=0)

    client.get = MagicMock(side_effect=ApiException(status=500, reason="server error"))
    with patch("chaosforge.engines.chaos_mesh.chaos_mesh_client.time.monotonic", side_effect=[0, 0, 2]):
        with pytest.raises(TimeoutError, match="Last API error"):
            client.wait_for("PodChaos", "example", timeout_seconds=1)
