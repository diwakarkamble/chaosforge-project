from unittest.mock import patch

import pytest

from chaosforge.application.metadata_loader import load_metadata


@patch("chaosforge.application.metadata_loader.ExperimentCatalog.load_service")
def test_load_metadata_success(mock_load):
    mock_load.return_value = {"service": "lambda"}

    result = load_metadata("lambda")

    assert result["service"] == "lambda"


@patch("chaosforge.application.metadata_loader.ExperimentCatalog.load_service")
def test_load_metadata_missing(mock_load):
    mock_load.return_value = None
    assert load_metadata("dummy-service") is None


def test_load_metadata_invalid_path():
    #
    # Invalid services are treated as unknown services.
    #
    assert load_metadata("../etc/passwd") is None


@patch("chaosforge.application.metadata_loader.ExperimentCatalog.load_service")
def test_load_metadata_empty(mock_load):
    mock_load.return_value = {}

    assert load_metadata("lambda") == {}

@patch("chaosforge.application.metadata_loader.secure_filename")
def test_load_metadata_rejects_invalid_service_path(mock_secure_filename):

    mock_secure_filename.return_value = "../etc"

    with pytest.raises(
        ValueError,
        match="Invalid service path",
    ):
        load_metadata("../etc")

@patch("chaosforge.application.metadata_loader.secure_filename")
def test_load_metadata_rejects_empty_service(mock_secure_filename):

    mock_secure_filename.return_value = ""

    with pytest.raises(
        ValueError,
        match="Invalid service name",
    ):
        load_metadata("!!!")
