from types import SimpleNamespace

from chaosforge.common.console_encoding import configure_windows_output


def test_cli_main_configures_windows_streams_for_unencodable_output(monkeypatch):
    configured = []
    stream = SimpleNamespace(reconfigure=lambda **kwargs: configured.append(kwargs))
    configure_windows_output((stream, stream), windows="nt")

    assert configured == [
        {"encoding": "utf-8", "errors": "replace"},
        {"encoding": "utf-8", "errors": "replace"},
    ]
