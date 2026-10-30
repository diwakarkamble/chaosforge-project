from unittest.mock import patch

from chaosforge.application.discovery import discover_services, display_name

# ==========================================================
# discover_services
# ==========================================================


@patch("chaosforge.application.discovery.ExperimentCatalog.list_services")
def test_discover_services(mock_services):
    mock_services.return_value = ["lambda", "rds", "fis", "__pycache__"]

    assert discover_services() == ["kinesis", "lambda", "rds"]


# ==========================================================
# display_name
# ==========================================================


def test_display_name_known_services():

    assert display_name("lambda") == "Amazon Lambda"
    assert display_name("dynamodb") == "Amazon DynamoDB"
    assert display_name("rds") == "Amazon RDS"
    assert display_name("sns") == "Amazon SNS"
    assert display_name("fis") == "AWS FIS"
    assert display_name("eventbridge") == "Amazon EventBridge"
    assert display_name("elasticache") == "Amazon ElastiCache"
    assert display_name("ec2") == "Amazon EC2"
    assert display_name("vpc") == "Amazon VPC"
    assert display_name("apigateway") == "Amazon API Gateway"
    assert display_name("kinesis") == "Amazon Kinesis"


def test_display_name_unknown_service():

    assert display_name("myservice") == "Myservice"


from unittest.mock import patch


@patch("chaosforge.application.discovery.ExperimentCatalog.list_services")
def test_discover_services_directory_not_exists(mock_services):
    mock_services.return_value = []

    assert discover_services() == ["kinesis"]
