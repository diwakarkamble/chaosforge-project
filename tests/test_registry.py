from unittest.mock import patch

from chaosforge.application.services.registry import execute_experiment


@patch("chaosforge.application.services.registry.add_generic")
def test_lambda_registry(mock_add):

    execute_experiment("lambda-timeout")

    mock_add.assert_called_once_with("lambda", "lambda-timeout", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_dynamodb_registry(mock_add):

    execute_experiment("dynamodb-ttl")

    mock_add.assert_called_once_with("dynamodb", "dynamodb-ttl", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_rds_registry(mock_add):

    execute_experiment("rds-iops")

    mock_add.assert_called_once_with("rds", "rds-iops", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_elasticache_registry(mock_add):

    execute_experiment("elasticache-usage-limit")

    mock_add.assert_called_once_with("elasticache", "elasticache-usage-limit", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_apigateway_registry(mock_add):

    execute_experiment("apigateway-stage-cache")

    mock_add.assert_called_once_with("apigateway", "apigateway-stage-cache", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_sns_registry(mock_add):

    execute_experiment("sns-topic-policy")

    mock_add.assert_called_once_with("sns", "sns-topic-policy", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_vpc_registry(mock_add):

    execute_experiment("vpc-security-group")

    mock_add.assert_called_once_with("vpc", "vpc-security-group", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_fis_registry(mock_add):

    execute_experiment("fis-stop")

    mock_add.assert_called_once_with("fis", "fis-stop", None)


@patch("builtins.input")
@patch("builtins.print")
def test_unknown_registry(mock_print, mock_input):

    execute_experiment("dummy-experiment")

    mock_print.assert_called_once()

    mock_input.assert_called_once()


@patch("chaosforge.application.services.registry.add_generic")
def test_ecs_registry(mock_add):

    execute_experiment("ecs-stop")

    mock_add.assert_called_once_with("ecs", "ecs-stop", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_s3_registry(mock_add):

    execute_experiment("s3-delete")

    mock_add.assert_called_once_with("s3", "s3-delete", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_ec2_registry(mock_add):

    execute_experiment("ec2-stop")

    mock_add.assert_called_once_with("ec2", "ec2-stop", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_elb_registry(mock_add):

    execute_experiment("elb-target-group")

    mock_add.assert_called_once_with("elb", "elb-target-group", None)


@patch("chaosforge.application.services.registry.add_generic")
def test_eks_registry(mock_add):

    execute_experiment("eks-replica-reduction")

    mock_add.assert_called_once_with("eks", "eks-replica-reduction", None)
