from unittest.mock import patch

from chaosforge.providers.aws.fis.service import FISService

# ----------------------------------------------------------
# Constructor
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.service.boto3.client")
def test_constructor(mock_client):

    service = FISService("us-east-1")

    mock_client.assert_called_once_with(
        "fis",
        region_name="us-east-1",
    )

    assert service.client == mock_client.return_value


# ----------------------------------------------------------
# List Templates
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.service.boto3.client")
def test_list_templates(mock_client):

    client = mock_client.return_value

    client.list_experiment_templates.return_value = {
        "experimentTemplates": [
            {
                "id": "template-1",
                "description": "Template One",
                "creationTime": "2026-07-30",
            },
            {
                "id": "template-2",
                "description": "Template Two",
                "creationTime": "2026-07-31",
            },
        ]
    }

    client.get_experiment_template.side_effect = [
        {
            "experimentTemplate": {
                "tags": {
                    "CreatedBy": "Divakar",
                }
            }
        },
        {
            "experimentTemplate": {
                "tags": {
                    "CreatedBy": "ChaosForge",
                }
            }
        },
    ]

    service = FISService()

    result = service.list_templates()

    assert result == [
        {
            "id": "template-1",
            "description": "Template One",
            "createdBy": "Divakar",
            "creationTime": "2026-07-30",
        },
        {
            "id": "template-2",
            "description": "Template Two",
            "createdBy": "ChaosForge",
            "creationTime": "2026-07-31",
        },
    ]

    assert client.get_experiment_template.call_count == 2


# ----------------------------------------------------------
# List Templates - Empty
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.service.boto3.client")
def test_list_templates_empty(mock_client):

    client = mock_client.return_value

    client.list_experiment_templates.return_value = {"experimentTemplates": []}

    service = FISService()

    result = service.list_templates()

    assert result == []

    client.get_experiment_template.assert_not_called()


# ----------------------------------------------------------
# Missing Tags
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.service.boto3.client")
def test_list_templates_missing_tags(mock_client):

    client = mock_client.return_value

    client.list_experiment_templates.return_value = {
        "experimentTemplates": [
            {
                "id": "template-1",
                "description": "Test",
                "creationTime": "today",
            }
        ]
    }

    client.get_experiment_template.return_value = {"experimentTemplate": {}}

    service = FISService()

    result = service.list_templates()

    assert result[0]["createdBy"] == "Unknown"


# ----------------------------------------------------------
# Missing Description
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.service.boto3.client")
def test_list_templates_missing_description(mock_client):

    client = mock_client.return_value

    client.list_experiment_templates.return_value = {
        "experimentTemplates": [
            {
                "id": "template-1",
                "creationTime": "today",
            }
        ]
    }

    client.get_experiment_template.return_value = {
        "experimentTemplate": {
            "tags": {
                "CreatedBy": "Admin",
            }
        }
    }

    service = FISService()

    result = service.list_templates()

    assert result[0]["description"] == ""


# ----------------------------------------------------------
# Delete Template
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.service.boto3.client")
def test_delete_template(mock_client):

    client = mock_client.return_value

    service = FISService()

    result = service.delete_template("template-123")

    assert result is True

    client.delete_experiment_template.assert_called_once_with(id="template-123")
