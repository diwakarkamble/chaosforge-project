from unittest.mock import mock_open, patch

from chaosforge.application.campaigns.yaml_loader import load_yaml


@patch("chaosforge.application.campaigns.yaml_loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open, read_data="name: test")
def test_load_yaml(mock_file, mock_yaml):

    mock_yaml.return_value = {"name": "test"}

    result = load_yaml("sample.yaml")

    assert result == {"name": "test"}

    mock_file.assert_called_once_with("sample.yaml", "r")

    mock_yaml.assert_called_once()
