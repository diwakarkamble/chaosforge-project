from chaosforge.providers.aws.fis.catalog import FISCatalog


def test_get_lambda_target():

    catalog = FISCatalog()

    service = catalog.get_service("lambda")

    assert service is not None

    assert service["id"] == "lambda"

    assert service["name"] == "AWS Lambda"


def test_get_lambda_experiment():

    catalog = FISCatalog()

    experiment = catalog.get_experiment("lambda", "invocation-delay")

    assert experiment is not None

    assert experiment["fis_action"] == "aws:lambda:invocation-add-delay"


def test_unknown_service():

    catalog = FISCatalog()

    service = catalog.get_service("dummy-service")

    assert service is None


def test_get_lambda_experiments():

    catalog = FISCatalog()

    experiments = catalog.get_experiments("lambda")

    assert len(experiments) > 0


def test_unknown_service_experiments():

    catalog = FISCatalog()

    experiments = catalog.get_experiments("dummy-service")

    assert experiments == []


def test_unknown_experiment():

    catalog = FISCatalog()

    experiment = catalog.get_experiment("lambda", "dummy-experiment")

    assert experiment is None


def test_get_menu_items():

    catalog = FISCatalog()

    menu = catalog.get_menu_items("lambda")

    assert len(menu) > 0

    item = menu[0]

    assert "title" in item
    assert "experiment_id" in item
    assert "prefill" in item


def test_empty_menu_items():

    catalog = FISCatalog()

    menu = catalog.get_menu_items("dummy-service")

    assert menu == []


def test_menu_prefill_values():

    catalog = FISCatalog()

    menu = catalog.get_menu_items("lambda")

    item = menu[0]

    assert item["prefill"]["service_id"] == "lambda"

    assert item["prefill"]["experiment_id"] == item["experiment_id"]


def test_get_services():

    catalog = FISCatalog()

    services = catalog.get_services()

    assert len(services) > 0

    assert isinstance(services, list)

    assert services[0]["id"] == "lambda"


def test_rds_failover_uses_the_aws_fis_cluster_target_contract():
    experiment = FISCatalog().get_experiment("rds", "failover-db-cluster")

    assert experiment["resource_type"] == "aws:rds:cluster"
    assert experiment["target_key"] == "Clusters"
    assert experiment["parameters"] == []


def test_eks_custom_resource_uses_the_singular_aws_fis_cluster_target_contract():
    experiment = FISCatalog().get_experiment("eks", "inject-kubernetes-custom-resource")

    assert experiment["resource_type"] == "aws:eks:cluster"
    assert experiment["target_key"] == "Cluster"


def test_rds_reboot_uses_the_optional_aws_fis_force_failover_parameter():
    experiment = FISCatalog().get_experiment("rds", "reboot-instance")

    assert experiment["parameters"] == [
        {
            "name": "force_failover",
            "aws_name": "forceFailover",
            "label": "Force Multi-AZ Failover",
            "type": "boolean",
            "default": False,
            "required": False,
        }
    ]
