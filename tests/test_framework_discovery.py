from unittest.mock import MagicMock, patch

from chaosforge.providers.aws.legacy_discovery import discover_lambda

# ----------------------------------------------------------
# Discover Lambda (Default Session)
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.legacy_discovery.boto3.Session")
def test_discover_lambda_default_session(mock_session):

    session = MagicMock()
    client = MagicMock()
    paginator = MagicMock()

    mock_session.return_value = session
    session.client.return_value = client
    client.get_paginator.return_value = paginator

    paginator.paginate.return_value = [
        {
            "Functions": [
                {
                    "FunctionName": "lambda-b",
                    "MemorySize": 512,
                    "Timeout": 30,
                },
                {
                    "FunctionName": "lambda-a",
                    "MemorySize": 128,
                    "Timeout": 10,
                },
            ]
        }
    ]

    result = discover_lambda("eu-central-1")

    mock_session.assert_called_once_with(region_name="eu-central-1")

    assert result == [
        {
            "name": "lambda-a",
            "memory": 128,
            "timeout": 10,
        },
        {
            "name": "lambda-b",
            "memory": 512,
            "timeout": 30,
        },
    ]


# ----------------------------------------------------------
# Discover Lambda (Named Profile)
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.legacy_discovery.boto3.Session")
def test_discover_lambda_with_profile(mock_session):

    session = MagicMock()
    client = MagicMock()
    paginator = MagicMock()

    mock_session.return_value = session
    session.client.return_value = client
    client.get_paginator.return_value = paginator

    paginator.paginate.return_value = [{"Functions": []}]

    discover_lambda(
        "us-east-1",
        profile="prod",
    )

    mock_session.assert_called_once_with(
        profile_name="prod",
        region_name="us-east-1",
    )


# ----------------------------------------------------------
# No Lambda Functions
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.legacy_discovery.boto3.Session")
def test_discover_lambda_empty(mock_session):

    session = MagicMock()
    client = MagicMock()
    paginator = MagicMock()

    mock_session.return_value = session
    session.client.return_value = client
    client.get_paginator.return_value = paginator

    paginator.paginate.return_value = []

    assert discover_lambda("eu-central-1") == []


# ----------------------------------------------------------
# Multiple Pages
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.legacy_discovery.boto3.Session")
def test_discover_lambda_multiple_pages(mock_session):

    session = MagicMock()
    client = MagicMock()
    paginator = MagicMock()

    mock_session.return_value = session
    session.client.return_value = client
    client.get_paginator.return_value = paginator

    paginator.paginate.return_value = [
        {
            "Functions": [
                {
                    "FunctionName": "lambda2",
                    "MemorySize": 256,
                    "Timeout": 20,
                }
            ]
        },
        {
            "Functions": [
                {
                    "FunctionName": "lambda1",
                    "MemorySize": 128,
                    "Timeout": 10,
                }
            ]
        },
    ]

    result = discover_lambda("eu-central-1")

    assert len(result) == 2

    assert result[0]["name"] == "lambda1"

    assert result[1]["name"] == "lambda2"
