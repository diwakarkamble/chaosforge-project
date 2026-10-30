from unittest.mock import MagicMock, patch

import pytest

from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.resource_selector import ResourceSelector


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_constructor(mock_discovery):

    ResourceSelector("eu-central-1")

    mock_discovery.assert_called_once_with("eu-central-1")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_lambda_resources(mock_discovery):

    discovery = mock_discovery.return_value

    discovery.list_lambda_functions.return_value = [{"name": "lambda1"}]

    selector = ResourceSelector()

    result = selector.get_resources("lambda")

    assert result == [{"name": "lambda1"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_apigateway_resources(mock_discovery):

    discovery = mock_discovery.return_value

    discovery.list_apigateway_apis.return_value = [{"name": "API1"}]

    selector = ResourceSelector()

    result = selector.get_resources("apigateway")

    assert result == [{"name": "API1"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_unknown_service(mock_discovery):

    selector = ResourceSelector()

    result = selector.get_resources("dummy")

    assert result == []


@patch.object(ResourceSelector, "get_resources")
def test_select_no_resources(mock_get):

    mock_get.return_value = []

    selector = ResourceSelector()

    with pytest.raises(Exception) as exc:
        selector.select("lambda")

    assert "No lambda resources found" in str(exc.value)


@patch("chaosforge.interfaces.cli.interactive.resource_selector.info")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch.object(ResourceSelector, "get_resources")
def test_select_success(mock_get, mock_title, mock_menu, mock_prompt, mock_info):

    mock_get.return_value = [{"name": "Lambda1", "arn": "abc"}]

    mock_prompt.return_value = "1"

    selector = ResourceSelector()

    result = selector.select("lambda")

    assert result["name"] == "Lambda1"


@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch.object(ResourceSelector, "get_resources")
def test_select_back(mock_get, mock_title, mock_menu, mock_prompt):

    mock_get.return_value = [{"name": "Lambda1"}]

    mock_prompt.return_value = "0"

    selector = ResourceSelector()

    result = selector.select("lambda")

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch.object(ResourceSelector, "get_resources")
def test_select_main_menu(mock_get, mock_title, mock_menu, mock_prompt):

    mock_get.return_value = [{"name": "Lambda1"}]

    mock_prompt.return_value = "m"

    selector = ResourceSelector()

    with pytest.raises(BackToMainMenu):
        selector.select("lambda")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.info")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.error")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch.object(ResourceSelector, "get_resources")
def test_select_invalid_then_valid(
    mock_get, mock_title, mock_menu, mock_prompt, mock_error, mock_info
):

    mock_get.return_value = [{"name": "Lambda1"}]

    mock_prompt.side_effect = ["10", "1"]

    selector = ResourceSelector()

    result = selector.select("lambda")

    assert result["name"] == "Lambda1"

    mock_error.assert_called_once_with("Invalid Selection")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.info")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_security_group(
    mock_discovery, mock_title, mock_menu, mock_prompt, mock_info
):

    discovery = mock_discovery.return_value

    discovery.list_security_group_rules.return_value = [{"name": "Rule1"}]

    mock_prompt.return_value = "1"

    selector = ResourceSelector()

    result = selector.select_child("security-group", "sg-123", "security-group-rule")

    assert result["name"] == "Rule1"


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_invalid(mock_discovery):

    selector = ResourceSelector()

    with pytest.raises(Exception) as exc:
        selector.select_child("lambda", "abc", "xyz")

    assert "Unsupported child resource" in str(exc.value)


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_no_resources(mock_discovery):

    discovery = mock_discovery.return_value

    discovery.list_security_group_rules.return_value = []

    selector = ResourceSelector()

    with pytest.raises(Exception) as exc:
        selector.select_child("security-group", "sg-123", "security-group-rule")

    assert "No security-group-rule found" in str(exc.value)


@patch("chaosforge.interfaces.cli.interactive.resource_selector.info")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_route_table(
    mock_discovery, mock_title, mock_menu, mock_prompt, mock_info
):

    discovery = mock_discovery.return_value

    discovery.list_routes.return_value = [{"name": "Route1"}]

    mock_prompt.return_value = "1"

    selector = ResourceSelector()

    result = selector.select_child("route-table", "rtb-1", "route")

    assert result["name"] == "Route1"


@patch("chaosforge.interfaces.cli.interactive.resource_selector.info")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_network_acl(
    mock_discovery, mock_title, mock_menu, mock_prompt, mock_info
):

    discovery = mock_discovery.return_value

    discovery.list_network_acl_rules.return_value = [{"name": "Rule100"}]

    mock_prompt.return_value = "1"

    selector = ResourceSelector()

    result = selector.select_child("network-acl", "acl-1", "network-acl-rule")

    assert result["name"] == "Rule100"


@patch("chaosforge.interfaces.cli.interactive.resource_selector.info")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.error")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_invalid_then_valid(
    mock_discovery, mock_title, mock_menu, mock_prompt, mock_error, mock_info
):

    discovery = mock_discovery.return_value

    discovery.list_security_group_rules.return_value = [{"name": "Rule1"}]

    mock_prompt.side_effect = ["10", "1"]

    selector = ResourceSelector()

    result = selector.select_child("security-group", "sg-123", "security-group-rule")

    assert result["name"] == "Rule1"
    mock_error.assert_called_once_with("Invalid Selection")


@pytest.mark.parametrize(
    ("parent_type", "child_type", "method"),
    [
        ("elb", "elb-target-group", "list_elb_target_groups"),
        ("elb-target-group", "elb-target", "list_elb_targets"),
        ("elb", "elb-listener", "list_elb_listeners"),
    ],
)
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_elb_child_resource_dispatch(mock_discovery, parent_type, child_type, method):
    selector = ResourceSelector()
    expected = [{"id": "resource"}]
    getattr(selector.discovery, method).return_value = expected

    assert selector.select_child_resources(parent_type, "parent", child_type) == expected


# ==========================================================
# Remaining get_resources branches
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_dynamodb_resources(mock_discovery):

    mock_discovery.return_value.list_dynamodb_tables.return_value = [{"name": "tbl"}]

    selector = ResourceSelector()

    assert selector.get_resources("dynamodb") == [{"name": "tbl"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_rds_resources(mock_discovery):

    mock_discovery.return_value.list_rds_instances.return_value = [{"name": "db"}]

    selector = ResourceSelector()

    assert selector.get_resources("rds") == [{"name": "db"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_rds_instance_class_resources(mock_discovery):
    selector = ResourceSelector()
    selector.discovery.list_rds_instance_classes.return_value = [{"name": "db.t4g.large"}]

    assert selector.select_child_resources("rds", "database", "rds-instance-class") == [
        {"name": "db.t4g.large"}
    ]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_elasticache_resources(mock_discovery):

    mock_discovery.return_value.list_elasticache_serverless.return_value = [
        {"name": "cache"}
    ]

    selector = ResourceSelector()

    assert selector.get_resources("elasticache") == [{"name": "cache"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_ec2_resources(mock_discovery):

    mock_discovery.return_value.list_ec2_instances.return_value = [{"name": "ec2"}]

    selector = ResourceSelector()

    assert selector.get_resources("ec2") == [{"name": "ec2"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_sns_resources(mock_discovery):

    mock_discovery.return_value.list_sns_topics.return_value = [{"name": "topic"}]

    selector = ResourceSelector()

    assert selector.get_resources("sns") == [{"name": "topic"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_sns_subscription_resources(mock_discovery):

    mock_discovery.return_value.list_sns_subscriptions.return_value = [
        {"name": "email -> alerts@example.com", "arn": "arn:subscription"}
    ]

    selector = ResourceSelector()

    assert selector.get_resources("sns_subscription") == [
        {"name": "email -> alerts@example.com", "arn": "arn:subscription"}
    ]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_security_groups(mock_discovery):

    mock_discovery.return_value.list_security_groups.return_value = [{"name": "sg"}]

    selector = ResourceSelector()

    assert selector.get_resources("security-group") == [{"name": "sg"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_route_tables(mock_discovery):

    mock_discovery.return_value.list_route_tables.return_value = [{"name": "rt"}]

    selector = ResourceSelector()

    assert selector.get_resources("route-table") == [{"name": "rt"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_network_acls(mock_discovery):

    mock_discovery.return_value.list_network_acls.return_value = [{"name": "acl"}]

    selector = ResourceSelector()

    assert selector.get_resources("network-acl") == [{"name": "acl"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_internet_gateways(mock_discovery):

    mock_discovery.return_value.list_internet_gateways.return_value = [{"name": "igw"}]

    selector = ResourceSelector()

    assert selector.get_resources("internet-gateway") == [{"name": "igw"}]


# ==========================================================
# Remaining select_child branches
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_back(
    mock_discovery,
    mock_title,
    mock_menu,
    mock_prompt,
):

    mock_discovery.return_value.list_security_group_rules.return_value = [
        {"name": "Rule1"}
    ]

    mock_prompt.return_value = "0"

    selector = ResourceSelector()

    assert (
        selector.select_child(
            "security-group",
            "sg-1",
            "security-group-rule",
        )
        is None
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_main_menu(
    mock_discovery,
    mock_title,
    mock_menu,
    mock_prompt,
):

    mock_discovery.return_value.list_security_group_rules.return_value = [
        {"name": "Rule1"}
    ]

    mock_prompt.return_value = "m"

    selector = ResourceSelector()

    with pytest.raises(BackToMainMenu):
        selector.select_child(
            "security-group",
            "sg-1",
            "security-group-rule",
        )


# ==========================================================
# ECS Resource Selector Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_task_success(
    mock_discovery,
    mock_title,
    mock_menu,
):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = [{"name": "service-1"}]

    discovery.list_ecs_tasks.return_value = [
        {
            "name": "task-1",
            "task_arn": "arn:aws:ecs:::task/task-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        side_effect=[
            {"name": "cluster-1"},
            {"name": "service-1"},
            {
                "name": "task-1",
                "task_arn": "arn:aws:ecs:::task/task-1",
            },
        ],
    ):
        result = selector.select_ecs_task()

    assert result == {
        "name": "task-1",
        "arn": "arn:aws:ecs:::task/task-1",
        "cluster": "cluster-1",
        "service": "service-1",
    }


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_task_no_clusters(mock_discovery):
    discovery = mock_discovery.return_value
    discovery.list_ecs_clusters.return_value = []

    selector = ResourceSelector()

    with pytest.raises(LookupError, match="No ECS Clusters found"):
        selector.select_ecs_task()


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_task_cluster_back(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=None,
    ):
        result = selector.select_ecs_task()

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_task_no_services(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = []

    selector = ResourceSelector()

    with (
        patch.object(
            selector,
            "_select_resource",
            return_value={"name": "cluster-1"},
        ),
        pytest.raises(
            LookupError,
            match="No ECS Services found",
        ),
    ):
        selector.select_ecs_task()


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_task_service_back(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = [{"name": "service-1"}]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        side_effect=[
            {"name": "cluster-1"},
            None,
        ],
    ):
        result = selector.select_ecs_task()

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_task_no_running_tasks(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = [{"name": "service-1"}]

    discovery.list_ecs_tasks.return_value = []

    selector = ResourceSelector()

    with (
        patch.object(
            selector,
            "_select_resource",
            side_effect=[
                {"name": "cluster-1"},
                {"name": "service-1"},
            ],
        ),
        pytest.raises(
            LookupError,
            match="No running ECS Tasks found",
        ),
    ):
        selector.select_ecs_task()


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_task_task_back(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = [{"name": "service-1"}]

    discovery.list_ecs_tasks.return_value = [
        {
            "name": "task-1",
            "task_arn": "arn:aws:ecs:::task/task-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        side_effect=[
            {"name": "cluster-1"},
            {"name": "service-1"},
            None,
        ],
    ):
        result = selector.select_ecs_task()

    assert result is None


# ==========================================================
# ECS Service Selector Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_service_success(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = [
        {
            "name": "service-1",
            "arn": "arn:aws:ecs:::service/service-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        side_effect=[
            {"name": "cluster-1"},
            {
                "name": "service-1",
                "arn": "arn:aws:ecs:::service/service-1",
            },
        ],
    ):
        result = selector.select_ecs_service()

    assert result == {
        "name": "service-1",
        "service": "service-1",
        "cluster": "cluster-1",
        "arn": "arn:aws:ecs:::service/service-1",
    }


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_service_no_clusters(mock_discovery):
    discovery = mock_discovery.return_value
    discovery.list_ecs_clusters.return_value = []

    selector = ResourceSelector()

    with pytest.raises(LookupError, match="No ECS Clusters found"):
        selector.select_ecs_service()


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_service_cluster_back(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=None,
    ):
        result = selector.select_ecs_service()

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_service_no_services(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = []

    selector = ResourceSelector()

    with (
        patch.object(
            selector,
            "_select_resource",
            return_value={"name": "cluster-1"},
        ),
        pytest.raises(
            LookupError,
            match="No ECS Services found",
        ),
    ):
        selector.select_ecs_service()


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ecs_service_service_back(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_clusters.return_value = [{"name": "cluster-1"}]

    discovery.list_ecs_services.return_value = [
        {
            "name": "service-1",
            "arn": "arn:aws:ecs:::service/service-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        side_effect=[
            {"name": "cluster-1"},
            None,
        ],
    ):
        result = selector.select_ecs_service()

    assert result is None


# ==========================================================
# select() ECS Branches
# ==========================================================


@patch.object(ResourceSelector, "select_ecs_task")
def test_select_ecs_task_branch(mock_select):
    mock_select.return_value = {"name": "task"}

    selector = ResourceSelector()

    result = selector.select("ecs_task")

    assert result == {"name": "task"}
    mock_select.assert_called_once()


@patch.object(ResourceSelector, "select_ecs_service")
def test_select_ecs_service_branch(mock_select):
    mock_select.return_value = {"name": "service"}

    selector = ResourceSelector()

    result = selector.select("ecs_service")

    assert result == {"name": "service"}
    mock_select.assert_called_once()


# ==========================================================
# API Gateway Child Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_apigateway_stage(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_apigateway_stages.return_value = [
        {
            "name": "stage-1",
            "id": "stage-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value={
            "name": "stage-1",
            "id": "stage-1",
        },
    ):
        result = selector.select_child(
            "apigateway",
            "api-123",
            "apigateway-stage",
        )

    assert result["name"] == "stage-1"

    discovery.list_apigateway_stages.assert_called_once_with("api-123")


# ==========================================================
# ECS Child Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_ecs_service(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_services.return_value = [
        {
            "name": "service-1",
            "arn": "arn:aws:ecs:::service/service-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value={
            "name": "service-1",
            "arn": "arn:aws:ecs:::service/service-1",
        },
    ):
        result = selector.select_child(
            "ecs",
            "cluster-123",
            "ecs-service",
        )

    assert result["name"] == "service-1"

    discovery.list_ecs_services.assert_called_once_with("cluster-123")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_rds_instance_class(mock_discovery):
    discovery = mock_discovery.return_value
    discovery.list_rds_instance_classes.return_value = [{"name": "db.t4g.large"}]
    selector = ResourceSelector()

    with patch.object(selector, "_select_resource", return_value={"name": "db.t4g.large"}):
        result = selector.select_child("rds", "database", "rds-instance-class")

    assert result == {"name": "db.t4g.large"}
    discovery.list_rds_instance_classes.assert_called_once_with("database")


# ==========================================================
# select_child_resources Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_resources_ecs(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ecs_services.return_value = [{"name": "service-1"}]

    selector = ResourceSelector()

    result = selector.select_child_resources(
        "ecs",
        "cluster-1",
        "ecs-service",
    )

    assert result == [{"name": "service-1"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_resources_apigateway(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_apigateway_stages.return_value = [{"name": "stage-1"}]

    selector = ResourceSelector()

    result = selector.select_child_resources(
        "apigateway",
        "api-1",
        "apigateway-stage",
    )

    assert result == [{"name": "stage-1"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_resources_eks_container(mock_discovery):
    discovery = mock_discovery.return_value
    discovery.list_eks_containers.return_value = [{"name": "app"}]
    selector = ResourceSelector()

    result = selector.select_child_resources(
        "eks-namespace",
        ("cluster", "apps", {"pod": "api-1", "deployment": ""}),
        "eks-container",
    )

    assert result == [{"name": "app"}]
    discovery.list_eks_containers.assert_called_once_with(
        "cluster", "apps", pod_name="api-1", deployment=""
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_resources_security_group(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_security_group_rules.return_value = [{"name": "rule-1"}]

    selector = ResourceSelector()

    result = selector.select_child_resources(
        "security-group",
        "sg-1",
        "security-group-rule",
    )

    assert result == [{"name": "rule-1"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_resources_route_table(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_routes.return_value = [{"name": "route-1"}]

    selector = ResourceSelector()

    result = selector.select_child_resources(
        "route-table",
        "rt-1",
        "route",
    )

    assert result == [{"name": "route-1"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_resources_network_acl(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_network_acl_rules.return_value = [{"name": "rule-1"}]

    selector = ResourceSelector()

    result = selector.select_child_resources(
        "network-acl",
        "acl-1",
        "network-acl-rule",
    )

    assert result == [{"name": "rule-1"}]


def test_select_child_resources_unsupported():
    selector = ResourceSelector()

    result = selector.select_child_resources(
        "dummy",
        "resource-1",
        "unknown",
    )

    assert result == []


def test_select_child_resources_ec2_ebs(monkeypatch):

    selector = ResourceSelector("eu-central-1")

    resources = [
        {
            "name": "vol-123",
            "id": "vol-123",
            "arn": "arn:test",
        }
    ]

    def mock_list_ec2_volumes(instance_id):
        assert instance_id == "i-123"
        return resources

    monkeypatch.setattr(
        selector.discovery,
        "list_ec2_ebs_volumes",
        mock_list_ec2_volumes,
    )

    result = selector.select_child_resources(
        "ec2",
        "i-123",
        "ebs-volume",
    )

    assert result == resources


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_target_group(mock_discovery):

    discovery = mock_discovery.return_value

    discovery.list_elb_target_groups.return_value = [
        {
            "name": "test-target-group",
            "arn": "arn:aws:elasticloadbalancing:::targetgroup/test",
            "target_type": "instance",
        }
    ]

    selector = ResourceSelector()

    selected = {
        "name": "test-target-group",
        "arn": "arn:aws:elasticloadbalancing:::targetgroup/test",
        "target_type": "instance",
    }

    with patch.object(
        selector,
        "_select_resource",
        return_value=selected,
    ):
        result = selector.select_elb_target_group(
            "arn:aws:elasticloadbalancing:::loadbalancer/test"
        )

    assert result == selected

    discovery.list_elb_target_groups.assert_called_once_with(
        "arn:aws:elasticloadbalancing:::loadbalancer/test"
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_target_group_no_groups(
    mock_discovery,
):

    discovery = mock_discovery.return_value

    discovery.list_elb_target_groups.return_value = []

    selector = ResourceSelector()

    with pytest.raises(
        LookupError,
        match="No ELB Target Groups found",
    ):
        selector.select_elb_target_group(
            "arn:aws:elasticloadbalancing:::loadbalancer/test"
        )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_target(mock_discovery):

    discovery = mock_discovery.return_value

    discovery.list_elb_targets.return_value = [
        {
            "name": "i-1234567890 (healthy)",
            "id": "i-1234567890",
            "target_id": "i-1234567890",
            "port": 80,
            "health": "healthy",
        }
    ]

    selector = ResourceSelector()

    selected = {
        "name": "i-1234567890 (healthy)",
        "id": "i-1234567890",
        "target_id": "i-1234567890",
        "port": 80,
        "health": "healthy",
    }

    with patch.object(
        selector,
        "_select_resource",
        return_value=selected,
    ):
        result = selector.select_elb_target(
            "arn:aws:elasticloadbalancing:::targetgroup/test"
        )

    assert result == selected

    discovery.list_elb_targets.assert_called_once_with(
        "arn:aws:elasticloadbalancing:::targetgroup/test"
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_target_no_targets(
    mock_discovery,
):

    discovery = mock_discovery.return_value

    discovery.list_elb_targets.return_value = []

    selector = ResourceSelector()

    with pytest.raises(
        LookupError,
        match="No ELB Targets found",
    ):
        selector.select_elb_target("arn:aws:elasticloadbalancing:::targetgroup/test")


# ==========================================================
# ELB Child Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_elb_target_group(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_elb_target_groups.return_value = [
        {
            "name": "target-group-1",
            "arn": "tg-arn-123",
            "target_type": "instance",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value={
            "name": "target-group-1",
            "arn": "tg-arn-123",
            "target_type": "instance",
        },
    ):
        result = selector.select_child(
            "elb",
            "lb-arn-123",
            "elb-target-group",
        )

    assert result["name"] == "target-group-1"

    discovery.list_elb_target_groups.assert_called_once_with("lb-arn-123")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_elb_target(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_elb_targets.return_value = [
        {
            "name": "target-1",
            "id": "target-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value={
            "name": "target-1",
            "id": "target-1",
        },
    ):
        result = selector.select_child(
            "elb-target-group",
            "tg-arn-123",
            "elb-target",
        )

    assert result["name"] == "target-1"

    discovery.list_elb_targets.assert_called_once_with("tg-arn-123")


# ==========================================================
# EKS Resource Selector
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_eks_node(mock_discovery):

    discovery = mock_discovery.return_value

    discovery.list_eks_nodes.return_value = [
        {
            "name": "ip-10-0-1-10.eu-central-1.compute.internal",
            "cluster": "eks-cluster-1",
        },
        {
            "name": "ip-10-0-1-11.eu-central-1.compute.internal",
            "cluster": "eks-cluster-1",
        },
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value={
            "name": "ip-10-0-1-10.eu-central-1.compute.internal",
            "cluster": "eks-cluster-1",
        },
    ):
        result = selector.select_child(
            "eks",
            "eks-cluster-1",
            "eks-node",
        )

    assert result["name"] == ("ip-10-0-1-10.eu-central-1.compute.internal")

    discovery.list_eks_nodes.assert_called_once_with("eks-cluster-1")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_eks_no_nodes(mock_discovery):

    discovery = mock_discovery.return_value

    discovery.list_eks_nodes.return_value = []

    selector = ResourceSelector()

    with pytest.raises(
        LookupError,
        match="No EKS Nodes found",
    ):
        selector.select_child(
            "eks",
            "eks-cluster-1",
            "eks-node",
        )


# ==========================================================
# Incremental coverage tests
# ==========================================================


@patch.object(ResourceSelector, "get_resources")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
def test_select_multiple_success(
    mock_title,
    mock_menu,
    mock_prompt,
    mock_get_resources,
):
    resources = [
        {"name": "resource-1"},
        {"name": "resource-2"},
        {"name": "resource-3"},
    ]

    mock_get_resources.return_value = resources
    mock_prompt.return_value = "1,3"

    selector = ResourceSelector()

    result = selector.select_multiple("lambda")

    assert result == [
        {"name": "resource-1"},
        {"name": "resource-3"},
    ]

    mock_get_resources.assert_called_once_with("lambda")


@patch.object(ResourceSelector, "get_resources")
def test_select_multiple_no_resources(mock_get_resources):
    mock_get_resources.return_value = []

    selector = ResourceSelector()

    with pytest.raises(
        LookupError,
        match="No lambda resources found",
    ):
        selector.select_multiple("lambda")


@patch.object(ResourceSelector, "get_resources")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.error")
def test_select_multiple_invalid_selection(
    mock_error,
    mock_prompt,
    mock_get_resources,
):
    mock_get_resources.return_value = [
        {"name": "resource-1"},
    ]

    mock_prompt.return_value = "abc"

    selector = ResourceSelector()

    result = selector.select_multiple("lambda")

    assert result is None
    mock_error.assert_called_once_with("Invalid selection.")


@patch.object(ResourceSelector, "get_resources")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.error")
def test_select_multiple_out_of_range(
    mock_error,
    mock_prompt,
    mock_get_resources,
):
    mock_get_resources.return_value = [
        {"name": "resource-1"},
    ]

    mock_prompt.return_value = "2"

    selector = ResourceSelector()

    result = selector.select_multiple("lambda")

    assert result is None

    mock_error.assert_called_once_with("Invalid resource selection: 2")


@patch.object(ResourceSelector, "get_resources")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
def test_select_multiple_empty_selection(
    mock_prompt,
    mock_get_resources,
):
    mock_get_resources.return_value = [
        {"name": "resource-1"},
    ]

    mock_prompt.return_value = ""

    selector = ResourceSelector()

    result = selector.select_multiple("lambda")

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
def test_select_ebs_volume_success(
    mock_title,
    mock_menu,
    mock_discovery,
):
    discovery = mock_discovery.return_value

    discovery.list_ec2_ebs_volumes.return_value = [
        {
            "name": "volume-1",
            "id": "vol-123",
            "device_name": "/dev/sda1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value={
            "name": "volume-1",
            "id": "vol-123",
            "device_name": "/dev/sda1",
        },
    ):
        result = selector.select_ebs_volume("i-123")

    assert result["id"] == "vol-123"

    discovery.list_ec2_ebs_volumes.assert_called_once_with("i-123")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ebs_volume_no_volumes(mock_discovery):
    discovery = mock_discovery.return_value
    discovery.list_ec2_ebs_volumes.return_value = []

    selector = ResourceSelector()

    with pytest.raises(
        LookupError,
        match="No EBS volumes found",
    ):
        selector.select_ebs_volume("i-123")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
def test_select_elb_target_group_success(
    mock_title,
    mock_menu,
    mock_discovery,
):
    discovery = mock_discovery.return_value

    target_group = {
        "name": "tg-1",
        "target_type": "instance",
        "arn": "arn:aws:elb:targetgroup/tg-1",
    }

    discovery.list_elb_target_groups.return_value = [target_group]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=target_group,
    ):
        result = selector.select_elb_target_group("arn:aws:elb:loadbalancer/lb-1")

    assert result == target_group

    discovery.list_elb_target_groups.assert_called_once_with(
        "arn:aws:elb:loadbalancer/lb-1"
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.menu")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.title")
def test_select_elb_target_success(
    mock_title,
    mock_menu,
    mock_discovery,
):
    discovery = mock_discovery.return_value

    target = {
        "name": "target-1",
        "id": "i-123",
    }

    discovery.list_elb_targets.return_value = [target]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=target,
    ):
        result = selector.select_elb_target("target-group-arn")

    assert result == target

    discovery.list_elb_targets.assert_called_once_with("target-group-arn")


# ==========================================================
# select_child - remaining branches
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_eks_node(
    mock_discovery,
):
    discovery = mock_discovery.return_value

    node = {"name": "node-1"}

    discovery.list_eks_nodes.return_value = [node]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=node,
    ):
        result = selector.select_child(
            "eks",
            "cluster-1",
            "eks-node",
        )

    assert result == node

    discovery.list_eks_nodes.assert_called_once_with("cluster-1")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_eks_namespace(
    mock_discovery,
):
    discovery = mock_discovery.return_value

    namespace = {"name": "default"}

    discovery.list_eks_namespaces.return_value = [namespace]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=namespace,
    ):
        result = selector.select_child(
            "eks",
            "cluster-1",
            "eks-namespace",
        )

    assert result == namespace

    discovery.list_eks_namespaces.assert_called_once_with("cluster-1")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_eks_deployment(
    mock_discovery,
):
    discovery = mock_discovery.return_value

    deployment = {"name": "deployment-1"}

    discovery.list_eks_deployments.return_value = [deployment]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=deployment,
    ):
        result = selector.select_child(
            "eks-namespace",
            ("cluster-1", "default"),
            "eks-deployment",
        )

    assert result == deployment

    discovery.list_eks_deployments.assert_called_once_with(
        "cluster-1",
        "default",
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_eks_pod(
    mock_discovery,
):
    discovery = mock_discovery.return_value

    pod = {"name": "pod-1"}

    discovery.list_eks_pods.return_value = [pod]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=pod,
    ):
        result = selector.select_child(
            "eks-namespace",
            ("cluster-1", "default"),
            "eks-pod",
        )

    assert result == pod

    discovery.list_eks_pods.assert_called_once_with(
        "cluster-1",
        "default",
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_eks_node_no_resources(
    mock_discovery,
):
    discovery = mock_discovery.return_value
    discovery.list_eks_nodes.return_value = []

    selector = ResourceSelector()

    with pytest.raises(
        LookupError,
        match="No EKS Nodes found",
    ):
        selector.select_child(
            "eks",
            "cluster-1",
            "eks-node",
        )


# ==========================================================
# _select_resource branches
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.info")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.console")
def test_select_resource_invalid_then_valid(
    mock_console,
    mock_prompt,
    mock_info,
):
    mock_prompt.side_effect = [
        "abc",
        "1",
    ]

    selector = ResourceSelector()

    resources = [{"name": "resource-1"}]

    with patch("chaosforge.interfaces.cli.interactive.resource_selector.error") as mock_error:
        result = selector._select_resource(
            resources,
            "Select Resource",
        )

    assert result == {"name": "resource-1"}

    mock_error.assert_called_once_with("Invalid Selection")

    mock_info.assert_called_once_with("Selected : resource-1")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.prompt")
@patch("chaosforge.interfaces.cli.interactive.resource_selector.console")
def test_select_resource_index_out_of_range(
    mock_console,
    mock_prompt,
):
    mock_prompt.side_effect = [
        "99",
        "0",
    ]

    selector = ResourceSelector()

    resources = [{"name": "resource-1"}]

    with patch("chaosforge.interfaces.cli.interactive.resource_selector.error") as mock_error:
        result = selector._select_resource(
            resources,
            "Select Resource",
        )

    assert result is None

    mock_error.assert_called_once_with("Invalid Selection")


# ==========================================================
# select_child_resources - remaining branches
# ==========================================================


def test_select_child_resources_eks_node():
    selector = ResourceSelector()

    selector.discovery.list_eks_nodes = MagicMock(return_value=[{"name": "node-1"}])

    result = selector.select_child_resources(
        "eks",
        "cluster-1",
        "eks-node",
    )

    assert result == [{"name": "node-1"}]

    selector.discovery.list_eks_nodes.assert_called_once_with("cluster-1")


def test_select_child_resources_eks_deployment():
    selector = ResourceSelector()

    selector.discovery.list_eks_deployments = MagicMock(
        return_value=[{"name": "deployment-1"}]
    )

    result = selector.select_child_resources(
        "eks-namespace",
        ("cluster-1", "default"),
        "eks-deployment",
    )

    assert result == [{"name": "deployment-1"}]


def test_select_child_resources_eks_pod():
    selector = ResourceSelector()

    selector.discovery.list_eks_pods = MagicMock(return_value=[{"name": "pod-1"}])

    result = selector.select_child_resources(
        "eks-namespace",
        ("cluster-1", "default"),
        "eks-pod",
    )

    assert result == [{"name": "pod-1"}]


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_kinesis_resources(mock_discovery):

    mock_discovery.return_value.list_kinesis_streams.return_value = [
        {
            "name": "orders-stream",
            "arn": ("arn:aws:kinesis:eu-central-1:111111111111:stream/orders-stream"),
        }
    ]

    selector = ResourceSelector()

    assert selector.get_resources("kinesis") == [
        {
            "name": "orders-stream",
            "arn": ("arn:aws:kinesis:eu-central-1:111111111111:stream/orders-stream"),
        }
    ]


# ==========================================================
# Remaining get_resources mappings
# ==========================================================


@pytest.mark.parametrize(
    ("service", "method_name", "resource"),
    [
        ("ec2-spot", "list_ec2_spot_instances", {"name": "spot-1"}),
        ("availability-zone", "list_availability_zones", {"name": "az-1"}),
        ("elb", "list_elb_load_balancers", {"name": "lb-1"}),
        ("iam-role", "list_iam_roles", {"name": "role-1"}),
        ("autoscaling-group", "list_auto_scaling_groups", {"name": "asg-1"}),
        ("ecs", "list_ecs_clusters", {"name": "cluster-1"}),
        ("eks", "list_eks_clusters", {"name": "eks-1"}),
        ("ecs_task", "list_all_ecs_tasks", {"name": "task-1"}),
        ("s3", "list_s3_buckets", {"name": "bucket-1"}),
        ("dynamodb-global-table", "list_dynamodb_global_tables", {"name": "global-1"}),
        ("rds-cluster", "list_rds_clusters", {"name": "cluster-1"}),
        ("elasticache-replication-group", "list_elasticache_replication_groups", {"name": "cache-1"}),
        ("elasticache-cache-cluster", "list_elasticache_cache_clusters", {"name": "cache-1"}),
        ("ebs-volume", "list_ec2_ebs_volumes_all", {"name": "vol-1"}),
    ],
)
@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_get_remaining_resources(
    mock_discovery,
    service,
    method_name,
    resource,
):
    discovery = mock_discovery.return_value
    getattr(discovery, method_name).return_value = [resource]

    selector = ResourceSelector()

    assert selector.get_resources(service) == [resource]
    getattr(discovery, method_name).assert_called_once_with()

# ==========================================================
# Available EBS / ASG Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_available_ebs_volume_success(mock_discovery):
    discovery = mock_discovery.return_value

    volume = {
        "name": "volume-available",
        "id": "vol-123",
    }

    discovery.list_available_ec2_ebs_volumes.return_value = [volume]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=volume,
    ):
        result = selector.select_available_ebs_volume("i-123")

    assert result == volume

    discovery.list_available_ec2_ebs_volumes.assert_called_once_with("i-123")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_available_ebs_volume_no_volumes(mock_discovery):
    discovery = mock_discovery.return_value
    discovery.list_available_ec2_ebs_volumes.return_value = []

    selector = ResourceSelector()

    with pytest.raises(
        LookupError,
        match="No available EBS volumes found",
    ):
        selector.select_available_ebs_volume("i-123")


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_ebs_volume_back(mock_discovery):
    discovery = mock_discovery.return_value

    discovery.list_ec2_ebs_volumes.return_value = [
        {"name": "volume-1", "id": "vol-1"}
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=None,
    ):
        result = selector.select_ebs_volume("i-123")

    assert result is None


@patch("boto3.client")
def test_list_available_ebs_volumes_for_asg_empty_asg(
    mock_boto3,
):
    selector = ResourceSelector()

    result = selector.list_available_ebs_volumes_for_asg("")

    assert result == []
    mock_boto3.client.assert_not_called()


@patch("boto3.client")
def test_list_available_ebs_volumes_for_asg_no_groups(
    mock_boto3,
):
    asg_client = mock_boto3.client.return_value

    asg_client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": []
    }

    selector = ResourceSelector()

    result = selector.list_available_ebs_volumes_for_asg("asg-1")

    assert result == []


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
@patch("boto3.client")
def test_list_available_ebs_volumes_for_asg_no_healthy_instance(
    mock_boto3,
    mock_discovery,
):
    asg_client = mock_boto3.client.return_value

    asg_client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "Instances": [
                    {
                        "LifecycleState": "InService",
                        "HealthStatus": "Unhealthy",
                        "InstanceId": "i-123",
                    }
                ]
            }
        ]
    }

    selector = ResourceSelector()

    result = selector.list_available_ebs_volumes_for_asg("asg-1")

    assert result == []

    mock_discovery.return_value.list_available_ec2_ebs_volumes.assert_not_called()


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
@patch("boto3.client")
def test_list_available_ebs_volumes_for_asg_success(
    mock_boto3,
    mock_discovery,
):
    discovery = mock_discovery.return_value
    discovery.region = "eu-central-1"

    asg_client = MagicMock()
    mock_boto3.return_value = asg_client

    asg_client.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "Instances": [
                    {
                        "LifecycleState": "InService",
                        "HealthStatus": "Healthy",
                        "InstanceId": "i-123",
                    }
                ]
            }
        ]
    }

    volumes = [
        {
            "name": "available-volume",
            "id": "vol-123",
        }
    ]

    discovery.list_available_ec2_ebs_volumes.return_value = volumes

    selector = ResourceSelector()

    result = selector.list_available_ebs_volumes_for_asg("asg-1")

    assert result == volumes

    mock_boto3.assert_called_once_with(
        "autoscaling",
        region_name="eu-central-1",
    )

    asg_client.describe_auto_scaling_groups.assert_called_once_with(
        AutoScalingGroupNames=["asg-1"],
    )

    discovery.list_available_ec2_ebs_volumes.assert_called_once_with(
        "i-123",
    )

# ==========================================================
# ELB Selector Remaining Coverage
# ==========================================================


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_target_group_back(mock_discovery):
    target_group = {
        "name": "tg-1",
        "arn": "tg-arn-1",
        "target_type": "instance",
    }

    mock_discovery.return_value.list_elb_target_groups.return_value = [
        target_group
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=None,
    ):
        result = selector.select_elb_target_group("lb-arn-1")

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_listener_success(mock_discovery):
    listener = {
        "name": "listener-1",
        "arn": "listener-arn-1",
    }

    mock_discovery.return_value.list_elb_listeners.return_value = [listener]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=listener,
    ):
        result = selector.select_elb_listener("lb-arn-1")

    assert result == listener

    mock_discovery.return_value.list_elb_listeners.assert_called_once_with(
        "lb-arn-1"
    )


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_listener_back(mock_discovery):
    mock_discovery.return_value.list_elb_listeners.return_value = [
        {
            "name": "listener-1",
            "arn": "listener-arn-1",
        }
    ]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=None,
    ):
        result = selector.select_elb_listener("lb-arn-1")

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_elb_target_back(mock_discovery):
    target = {
        "name": "target-1",
        "id": "i-123",
    }

    mock_discovery.return_value.list_elb_targets.return_value = [target]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=None,
    ):
        result = selector.select_elb_target("tg-arn-1")

    assert result is None


@patch("chaosforge.interfaces.cli.interactive.resource_selector.AWSDiscovery")
def test_select_child_elb_listener(mock_discovery):
    listener = {
        "name": "listener-1",
        "arn": "listener-arn-1",
    }

    mock_discovery.return_value.list_elb_listeners.return_value = [listener]

    selector = ResourceSelector()

    with patch.object(
        selector,
        "_select_resource",
        return_value=listener,
    ):
        result = selector.select_child(
            "elb",
            "lb-arn-1",
            "elb-listener",
        )

    assert result == listener

    mock_discovery.return_value.list_elb_listeners.assert_called_once_with(
        "lb-arn-1"
    )


# ==========================================================
# select_child_resources Remaining Coverage
# ==========================================================


def test_select_child_resources_eks_namespace():
    selector = ResourceSelector()

    selector.discovery.list_eks_namespaces = MagicMock(
        return_value=[{"name": "default"}]
    )

    result = selector.select_child_resources(
        "eks",
        "cluster-1",
        "eks-namespace",
    )

    assert result == [{"name": "default"}]

    selector.discovery.list_eks_namespaces.assert_called_once_with(
        "cluster-1"
    )


def test_select_child_resources_ec2_available_ebs():
    selector = ResourceSelector()

    volumes = [{"name": "volume-1", "id": "vol-1"}]

    selector.discovery.list_available_ec2_ebs_volumes = MagicMock(
        return_value=volumes
    )

    result = selector.select_child_resources(
        "ec2",
        "i-123",
        "ebs-volume-available",
    )

    assert result == volumes

    selector.discovery.list_available_ec2_ebs_volumes.assert_called_once_with(
        "i-123"
    )


@patch.object(ResourceSelector, "list_available_ebs_volumes_for_asg")
def test_select_child_resources_asg_available_ebs(mock_list):
    volumes = [{"name": "volume-1", "id": "vol-1"}]

    mock_list.return_value = volumes

    selector = ResourceSelector()

    result = selector.select_child_resources(
        "autoscaling-group",
        "asg-1",
        "ebs-volume-asg-available",
    )

    assert result == volumes

    mock_list.assert_called_once_with("asg-1")
