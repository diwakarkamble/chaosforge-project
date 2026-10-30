from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from chaosforge.providers.aws.fis.delete_actions import delete_fis_template


@patch("chaosforge.providers.aws.fis.delete_actions.success")
@patch("chaosforge.providers.aws.fis.delete_actions.boto3.client")
def test_delete_fis_template_success(mock_client, mock_success):
    client = MagicMock()
    mock_client.return_value = client

    delete_fis_template("template-123", "us-east-1")

    mock_client.assert_called_once_with("fis", region_name="us-east-1")
    client.delete_experiment_template.assert_called_once_with(
        id="template-123"
    )
    mock_success.assert_called_once_with(
        "FIS Experiment Template deleted successfully."
    )


@patch("chaosforge.providers.aws.fis.delete_actions.error")
@patch("chaosforge.providers.aws.fis.delete_actions.boto3.client")
def test_delete_fis_template_client_error(mock_client, mock_error):
    client = MagicMock()
    mock_client.return_value = client

    client.delete_experiment_template.side_effect = ClientError(
        {
            "Error": {
                "Code": "ResourceNotFoundException",
                "Message": "Template not found",
            }
        },
        "DeleteExperimentTemplate",
    )

    delete_fis_template("template-123", "us-east-1")

    mock_client.assert_called_once_with("fis", region_name="us-east-1")
    client.delete_experiment_template.assert_called_once_with(
        id="template-123"
    )
    mock_error.assert_called_once()
    assert "Template not found" in mock_error.call_args.args[0]
