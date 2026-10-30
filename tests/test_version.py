from importlib.metadata import PackageNotFoundError

from chaosforge.common import version


def test_chaosforge_version_reads_installed_distribution(monkeypatch):
    monkeypatch.setattr(version, "distribution_version", lambda _: "2.3.4")

    assert version.chaosforge_version() == "2.3.4"


def test_chaosforge_version_falls_back_to_source_metadata(monkeypatch):
    def missing_distribution(_):
        raise PackageNotFoundError

    monkeypatch.setattr(version, "distribution_version", missing_distribution)

    assert version.chaosforge_version() == "1.0.0"
