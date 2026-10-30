from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common import (
    delete_state,
    describe_task_definition,
    find_service,
    get_previous_task_definition,
    load_state,
    print_header,
    print_service_summary,
    register_task_definition,
    save_state,
    update_service,
    wait_for_duration,
)

# ----------------------------------------------------------
# find_service
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_client")
def test_find_service_success(mock_get_client):

    client = MagicMock()

    client.list_clusters.return_value = {
        "clusterArns": [
            "arn:aws:ecs:::cluster/test-cluster",
        ]
    }

    client.list_services.return_value = {
        "serviceArns": [
            "arn:aws:ecs:::service/test-service",
        ]
    }

    client.describe_services.return_value = {
        "services": [
            {
                "serviceName": "demo-service",
                "desiredCount": 2,
            }
        ]
    }

    mock_get_client.return_value = client

    cluster, service = find_service(
        "demo-service",
        "eu-west-1",
    )

    assert cluster == "test-cluster"
    assert service["serviceName"] == "demo-service"


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_client")
def test_find_service_not_found(mock_get_client):

    client = MagicMock()

    client.list_clusters.return_value = {
        "clusterArns": [
            "arn:aws:ecs:::cluster/test-cluster",
        ]
    }

    client.list_services.return_value = {"serviceArns": []}

    mock_get_client.return_value = client

    with pytest.raises(RuntimeError):
        find_service(
            "missing-service",
            "eu-west-1",
        )


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_client")
def test_find_service_uses_the_selected_cluster(mock_get_client):
    client = MagicMock()
    client.list_services.return_value = {"serviceArns": ["arn:aws:ecs:::service/test-service"]}
    client.describe_services.return_value = {"services": [{"serviceName": "demo-service"}]}
    mock_get_client.return_value = client

    cluster, _ = find_service("demo-service", "eu-west-1", ecs_cluster="selected-cluster")

    assert cluster == "selected-cluster"
    client.list_clusters.assert_not_called()
    client.list_services.assert_called_once_with(cluster="selected-cluster")


# ----------------------------------------------------------
# describe_task_definition
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_client")
def test_describe_task_definition(mock_get_client):

    client = MagicMock()

    client.describe_task_definition.return_value = {
        "taskDefinition": {"family": "demo"}
    }

    mock_get_client.return_value = client

    response = describe_task_definition(
        "demo:1",
        "eu-west-1",
    )

    assert response["family"] == "demo"


# ----------------------------------------------------------
# register_task_definition
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_client")
def test_register_task_definition(mock_get_client):

    client = MagicMock()

    client.register_task_definition.return_value = {
        "taskDefinition": {"taskDefinitionArn": "arn:new"}
    }

    mock_get_client.return_value = client

    arn = register_task_definition(
        {
            "family": "demo",
            "networkMode": "awsvpc",
            "containerDefinitions": [],
        },
        "eu-west-1",
    )

    assert arn == "arn:new"


# ----------------------------------------------------------
# update_service
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_client")
def test_update_service(mock_get_client):

    client = MagicMock()

    mock_get_client.return_value = client

    update_service(
        "cluster",
        "service",
        "eu-west-1",
        desiredCount=3,
    )

    client.update_service.assert_called_once()


# ----------------------------------------------------------
# wait
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.time.sleep")
def test_wait_for_duration(mock_sleep):

    wait_for_duration(1)

    mock_sleep.assert_called_once_with(1.0)


# ----------------------------------------------------------
# save_state
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_state_file")
@patch("builtins.open", new_callable=mock_open)
def test_save_state(mock_file, mock_state):

    mock_state.return_value = "state.json"

    save_state(
        "demo",
        {"value": 1},
    )

    handle = mock_file()

    handle.write.assert_called()


# ----------------------------------------------------------
# load_state
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_state_file")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data='{"value":1}')
def test_load_state(
    mock_file,
    mock_exists,
    mock_state,
):

    mock_exists.return_value = True
    mock_state.return_value = "state.json"

    result = load_state("demo")

    assert result["value"] == 1


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_state_file")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.os.path.exists")
def test_load_state_not_found(
    mock_exists,
    mock_state,
):

    mock_exists.return_value = False
    mock_state.return_value = "state.json"

    with pytest.raises(FileNotFoundError):
        load_state("demo")


# ----------------------------------------------------------
# delete_state
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_state_file")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.os.path.exists")
@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.os.remove")
def test_delete_state(
    mock_remove,
    mock_exists,
    mock_state,
):

    mock_exists.return_value = True
    mock_state.return_value = "state.json"

    delete_state("demo")

    mock_remove.assert_called_once()


# ----------------------------------------------------------
# print helpers
# ----------------------------------------------------------


def test_print_header(capsys):

    print_header("Demo")

    output = capsys.readouterr().out

    assert "Demo" in output


def test_print_service_summary(capsys):

    print_service_summary(
        {
            "serviceName": "demo",
            "desiredCount": 2,
            "runningCount": 2,
            "taskDefinition": "task:1",
        }
    )

    output = capsys.readouterr().out

    assert "demo" in output


# ----------------------------------------------------------
# previous task definition
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.components.ecs.experiments.toolkit.actions.ecs_common.get_client")
def test_get_previous_task_definition(mock_get_client):

    client = MagicMock()

    client.list_task_definitions.return_value = {
        "taskDefinitionArns": [
            "task:5",
            "task:4",
        ]
    }

    mock_get_client.return_value = client

    previous = get_previous_task_definition(
        "arn:aws:ecs:::task/demo:5",
        "eu-west-1",
    )

    assert previous == "task:4"
