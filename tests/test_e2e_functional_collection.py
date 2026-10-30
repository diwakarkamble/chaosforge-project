from types import SimpleNamespace
from urllib.error import URLError

import pytest

from e2e.webui.functional import conftest


class _Metafunc:
    def __init__(self, fixtures, mode):
        self.fixturenames = fixtures
        self.config = SimpleNamespace(getoption=lambda name: mode if name == "e2e_campaign_mode" else None)
        self.calls = []

    def parametrize(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_isolated_collection_skips_combined_fixture_without_missing_fixture(monkeypatch):
    metafunc = _Metafunc(["campaign_group"], "isolated")

    conftest.pytest_generate_tests(metafunc)

    assert metafunc.calls == []


def test_combined_collection_parametrizes_campaign_groups(monkeypatch):
    group = SimpleNamespace(id="azure-combined")
    monkeypatch.setattr(conftest, "_planned_groups", lambda _: [group])
    metafunc = _Metafunc(["campaign_group"], "combined")

    conftest.pytest_generate_tests(metafunc)

    assert metafunc.calls[0][0][1] == [group]


def test_collection_keeps_only_selected_campaign_mode():
    config = SimpleNamespace(getoption=lambda _: "isolated", hook=SimpleNamespace(pytest_deselected=lambda **_: None))
    isolated = SimpleNamespace(
        nodeid="e2e/webui/functional/test_functional_campaigns.py::test_functional_campaign_case",
        name="test_functional_campaign_case",
    )
    combined = SimpleNamespace(
        nodeid="e2e/webui/functional/test_functional_campaigns.py::test_functional_campaign_group",
        name="test_functional_campaign_group",
    )
    items = [isolated, combined]

    conftest.pytest_collection_modifyitems(config, items)

    assert items == [isolated]


def test_web_azure_subscription_uses_identity_endpoint(monkeypatch):
    class Response:
        def read(self):
            return b'{"authenticated": true, "subscription_id": "sub"}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(conftest, "urlopen", lambda *_args, **_kwargs: Response())

    assert conftest._web_azure_subscription("http://localhost:5000") == "sub"

    monkeypatch.setattr(conftest, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")))
    with pytest.raises(conftest.ManifestError, match="Could not read"):
        conftest._web_azure_subscription("http://localhost:5000")
