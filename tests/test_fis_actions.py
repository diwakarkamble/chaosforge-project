from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.aws.fis.actions import (
    create_experiment,
    execute_management_action,
    recover_interrupted_experiment,
)

# ----------------------------------------------------------
# Unknown Service
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.actions.delete_template")
@patch("chaosforge.providers.aws.fis.actions.stop_experiment")
@patch("chaosforge.providers.aws.fis.actions.start_experiment")
def test_direct_fis_management_actions_replace_legacy_toolkit_wrappers(
    start,
    stop,
    delete,
):
    execute_management_action(
        "fis-start-template", {"aws_region": "eu-central-1", "experiment_template_id": "template-1"}
    )
    execute_management_action(
        "fis-stop-experiment", {"aws_region": "eu-central-1", "experiment_id": "experiment-1"}
    )
    execute_management_action(
        "fis-delete-template", {"aws_region": "eu-central-1", "template_id": "template-1"}
    )

    start.assert_called_once_with("template-1", "eu-central-1")
    stop.assert_called_once_with("experiment-1", "eu-central-1")
    delete.assert_called_once_with("template-1", "eu-central-1")

    with pytest.raises(ValueError, match="Unsupported direct FIS management action"):
        execute_management_action("unsupported", {"aws_region": "eu-central-1"})


@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_unknown_service(mock_catalog):

    catalog = mock_catalog.return_value

    catalog.get_service.return_value = None

    catalog.get_experiment.return_value = {}

    with pytest.raises(ValueError):
        create_experiment(
            experiment_name="Chaos",
            description="Test",
            created_by="UnitTest",
            service_id="invalid",
            experiment_id="delay",
            target_arn="arn:test",
            role_arn="arn:role",
            region="eu-central-1",
        )


# ----------------------------------------------------------
# Unknown Experiment
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_unknown_experiment(mock_catalog):

    catalog = mock_catalog.return_value

    catalog.get_service.return_value = {"id": "lambda"}

    catalog.get_experiment.return_value = None

    with pytest.raises(ValueError):
        create_experiment(
            experiment_name="Chaos",
            description="Test",
            created_by="UnitTest",
            service_id="lambda",
            experiment_id="invalid",
            target_arn="arn:test",
            role_arn="arn:role",
            region="eu-central-1",
        )


# ----------------------------------------------------------
# Create Experiment
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.actions.time.sleep")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
@patch("chaosforge.providers.aws.fis.actions.FISTemplateBuilder")
@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_success(
    mock_catalog,
    mock_builder,
    mock_boto,
    mock_sleep,
):

    catalog = mock_catalog.return_value

    catalog.get_service.return_value = {"id": "lambda"}

    catalog.get_experiment.return_value = {
        "parameters": [
            {
                "name": "duration",
                "default": "PT5M",
            }
        ]
    }

    builder = mock_builder.return_value

    builder.build.return_value = {"description": "template"}

    client = MagicMock()

    mock_boto.return_value = client

    client.create_experiment_template.return_value = {
        "experimentTemplate": {"id": "tmpl-123"}
    }

    client.start_experiment.return_value = {
        "experiment": {
            "id": "exp-123",
            "state": {"status": "running"},
        }
    }
    client.get_experiment.return_value = {
        "experiment": {"state": {"status": "completed"}}
    }

    create_experiment(
        experiment_name="Chaos",
        description="Test",
        created_by="UnitTest",
        service_id="lambda",
        experiment_id="delay",
        target_arn="arn:test",
        role_arn="arn:role",
        region="eu-central-1",
    )

    client.create_experiment_template.assert_called_once()

    client.start_experiment.assert_called_once()
    assert mock_builder.return_value.build.call_args.kwargs["created_by"] == "UnitTest"


@patch("chaosforge.providers.aws.fis.actions.time.sleep")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
@patch("chaosforge.providers.aws.fis.actions.FISTemplateBuilder")
@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_prefers_serialized_catalog_parameters(
    mock_catalog,
    mock_builder,
    mock_boto,
    mock_sleep,
):
    mock_catalog.return_value.get_service.return_value = {"id": "lambda"}
    mock_catalog.return_value.get_experiment.return_value = {
        "parameters": [
            {"name": "content_type_header", "default": "application/json"},
            {"name": "prevent_execution", "default": True},
        ]
    }
    mock_builder.return_value.build.return_value = {}
    client = mock_boto.return_value
    client.create_experiment_template.return_value = {
        "experimentTemplate": {"id": "template-1"}
    }
    client.start_experiment.return_value = {
        "experiment": {
            "id": "experiment-1",
            "state": {"status": "completed"},
        }
    }

    create_experiment(
        experiment_name="Chaos",
        description="Test",
        created_by="UnitTest",
        service_id="lambda",
        experiment_id="http-response",
        target_arn="arn:test",
        role_arn="arn:role",
        region="eu-central-1",
        fis_action_parameters_json=(
            '{"content_type_header":"text/plain","prevent_execution":false}'
        ),
    )

    assert mock_builder.return_value.build.call_args.kwargs["parameters"] == {
        "content_type_header": "text/plain",
        "prevent_execution": False,
    }


# ----------------------------------------------------------
# Auto Delete Disabled
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.actions.time.sleep")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
@patch("chaosforge.providers.aws.fis.actions.FISTemplateBuilder")
@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_auto_delete_disabled(
    mock_catalog,
    mock_builder,
    mock_boto,
    mock_sleep,
):

    catalog = mock_catalog.return_value

    catalog.get_service.return_value = {}

    catalog.get_experiment.return_value = {"parameters": []}

    mock_builder.return_value.build.return_value = {}

    client = MagicMock()

    mock_boto.return_value = client

    client.create_experiment_template.return_value = {
        "experimentTemplate": {"id": "template-1"}
    }

    client.start_experiment.return_value = {
        "experiment": {
            "id": "experiment-1",
            "state": {"status": "running"},
        }
    }
    client.get_experiment.return_value = {
        "experiment": {"state": {"status": "completed"}}
    }

    create_experiment(
        experiment_name="Chaos",
        description="Test",
        created_by="UnitTest",
        service_id="lambda",
        experiment_id="delay",
        target_arn="arn:test",
        role_arn="arn:role",
        region="eu-central-1",
        auto_delete_template="N",
    )

    client.delete_experiment_template.assert_not_called()


# ----------------------------------------------------------
# Auto Delete Enabled
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.actions.time.sleep")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
@patch("chaosforge.providers.aws.fis.actions.FISTemplateBuilder")
@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_auto_delete_enabled(
    mock_catalog,
    mock_builder,
    mock_boto,
    mock_sleep,
):

    catalog = mock_catalog.return_value

    catalog.get_service.return_value = {}

    catalog.get_experiment.return_value = {"parameters": []}

    mock_builder.return_value.build.return_value = {}

    client = MagicMock()

    mock_boto.return_value = client

    client.create_experiment_template.return_value = {
        "experimentTemplate": {"id": "template-1"}
    }

    client.start_experiment.return_value = {
        "experiment": {
            "id": "experiment-1",
            "state": {"status": "running"},
        }
    }

    client.get_experiment.side_effect = [
        {"experiment": {"state": {"status": "running"}}},
        {"experiment": {"state": {"status": "completed"}}},
    ]

    create_experiment(
        experiment_name="Chaos",
        description="Test",
        created_by="UnitTest",
        service_id="lambda",
        experiment_id="delay",
        target_arn="arn:test",
        role_arn="arn:role",
        region="eu-central-1",
        auto_delete_template="Y",
    )

    assert client.get_experiment.call_count == 2

    client.delete_experiment_template.assert_called_once_with(id="template-1")

    mock_sleep.assert_called_once_with(10)


@patch("chaosforge.providers.aws.fis.actions.boto3.client")
@patch("chaosforge.providers.aws.fis.actions.FISTemplateBuilder")
@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_generic_fis_auto_cleanup_runs_supplied_callback(mock_catalog, mock_builder, mock_boto):
    mock_catalog.return_value.get_service.return_value = {"id": "ec2"}
    mock_catalog.return_value.get_experiment.return_value = {"parameters": []}
    mock_builder.return_value.build.return_value = {}
    client = mock_boto.return_value
    client.create_experiment_template.return_value = {"experimentTemplate": {"id": "template-1"}}
    client.start_experiment.return_value = {
        "experiment": {"id": "experiment-1", "state": {"status": "completed"}}
    }
    cleanup = MagicMock()

    create_experiment(
        experiment_name="Generic FIS",
        description="Test",
        created_by="operator",
        service_id="ec2",
        experiment_id="stop",
        target_arn="arn:aws:ec2:eu-central-1:123:instance/i-123",
        role_arn="arn:aws:iam::123:role/FISRole",
        region="eu-central-1",
        auto_delete_template="Y",
        cleanup=cleanup,
    )

    cleanup.assert_called_once_with()


@patch("chaosforge.providers.aws.fis.actions.time.sleep")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
@patch("chaosforge.providers.aws.fis.actions.FISTemplateBuilder")
@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_raises_when_fis_fails(
    mock_catalog,
    mock_builder,
    mock_boto,
    mock_sleep,
):
    mock_catalog.return_value.get_service.return_value = {"id": "ec2"}
    mock_catalog.return_value.get_experiment.return_value = {"parameters": []}
    mock_builder.return_value.build.return_value = {}
    client = mock_boto.return_value
    client.create_experiment_template.return_value = {
        "experimentTemplate": {"id": "template-1"}
    }
    client.start_experiment.return_value = {
        "experiment": {
            "id": "experiment-1",
            "state": {"status": "initiating"},
        }
    }
    client.get_experiment.return_value = {
        "experiment": {
            "state": {
                "status": "failed",
                "reason": "Target did not pass validation",
            }
        }
    }

    with pytest.raises(RuntimeError, match="Target did not pass validation"):
        create_experiment(
            experiment_name="Chaos",
            description="Test",
            created_by="UnitTest",
            service_id="ec2",
            experiment_id="stop-instances",
            target_arn="i-123",
            role_arn="arn:role",
            region="eu-central-1",
        )


@patch("chaosforge.providers.aws.fis.actions.time.sleep")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
@patch("chaosforge.providers.aws.fis.actions.FISTemplateBuilder")
@patch("chaosforge.providers.aws.fis.actions.FISCatalog")
def test_create_experiment_raises_when_fis_action_did_not_complete(
    mock_catalog,
    mock_builder,
    mock_boto,
    mock_sleep,
):
    mock_catalog.return_value.get_service.return_value = {"id": "ec2"}
    mock_catalog.return_value.get_experiment.return_value = {"parameters": []}
    mock_builder.return_value.build.return_value = {}
    client = mock_boto.return_value
    client.create_experiment_template.return_value = {
        "experimentTemplate": {"id": "template-1"}
    }
    client.start_experiment.return_value = {
        "experiment": {
            "id": "experiment-1",
            "state": {"status": "initiating"},
        }
    }
    client.get_experiment.return_value = {
        "experiment": {
            "state": {"status": "completed"},
            "actions": {
                "Action1": {
                    "state": {
                        "status": "skipped",
                        "reason": "No matching targets",
                    }
                }
            },
        }
    }

    with pytest.raises(RuntimeError, match="No matching targets"):
        create_experiment(
            experiment_name="Chaos",
            description="Test",
            created_by="UnitTest",
            service_id="ec2",
            experiment_id="reboot-instances",
            target_arn="i-123",
            role_arn="arn:role",
            region="eu-central-1",
        )


from unittest.mock import patch

from chaosforge.providers.aws.fis.actions import (
    delete_template,
    start_experiment,
    stop_experiment,
)


def test_create_experiment_requires_target_and_role():
    with pytest.raises(ValueError, match="Target resource is required"):
        create_experiment("name", "description", "owner", "ec2", "stop-instances", "", "role", "eu-central-1")

    with pytest.raises(ValueError, match="execution role ARN is required"):
        create_experiment("name", "description", "owner", "ec2", "stop-instances", "i-123", "", "eu-central-1")


def test_recover_interrupted_fis_stops_experiment_and_deletes_template(tmp_path):
    recovery_file = tmp_path / "fis-recovery.json"
    recovery_file.write_text(
        '{"experiment_id": "exp-1", "template_id": "template-1"}',
        encoding="utf-8",
    )
    client = MagicMock()
    client.get_experiment.return_value = {
        "experiment": {"state": {"status": "running"}}
    }

    with patch("chaosforge.providers.aws.fis.actions.boto3.client", return_value=client):
        result = recover_interrupted_experiment(str(recovery_file), "eu-central-1")

    assert result["success"] is True
    client.stop_experiment.assert_called_once_with(id="exp-1")
    client.delete_experiment_template.assert_called_once_with(id="template-1")
    assert any("Stop requested" in message for message in result["messages"])


def test_recover_interrupted_fis_requires_recovery_state():
    result = recover_interrupted_experiment("", "eu-central-1")

    assert result["success"] is False
    assert "manual verification" in result["messages"][0]

# ----------------------------------------------------------
# Start Existing Experiment
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.actions.boto3.client")
def test_start_experiment(mock_boto):

    client = MagicMock()

    mock_boto.return_value = client

    client.start_experiment.return_value = {
        "experiment": {
            "id": "exp-123",
            "state": {"status": "running"},
        }
    }

    start_experiment(
        "template-1",
        "eu-central-1",
    )

    client.start_experiment.assert_called_once_with(experimentTemplateId="template-1")


# ----------------------------------------------------------
# Stop Experiment
# ----------------------------------------------------------


@patch("chaosforge.providers.aws.fis.actions.boto3.client")
def test_stop_experiment(mock_boto):

    client = MagicMock()

    mock_boto.return_value = client

    client.stop_experiment.return_value = {
        "experiment": {
            "id": "exp-123",
            "state": {"status": "stopped"},
        }
    }

    stop_experiment(
        "exp-123",
        "eu-central-1",
    )

    client.stop_experiment.assert_called_once_with(id="exp-123")


# ----------------------------------------------------------
# Delete Template
# ----------------------------------------------------------


@patch("builtins.input")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
def test_delete_template(
    mock_boto,
    mock_input,
):

    mock_input.return_value = "y"

    client = MagicMock()

    mock_boto.return_value = client

    client.get_experiment_template.return_value = {
        "experimentTemplate": {
            "id": "template-1",
            "description": "Chaos",
        }
    }

    delete_template(
        "template-1",
        "eu-central-1",
    )

    client.delete_experiment_template.assert_called_once_with(id="template-1")


# ----------------------------------------------------------
# Delete Cancelled
# ----------------------------------------------------------


@patch("builtins.input")
@patch("chaosforge.providers.aws.fis.actions.boto3.client")
def test_delete_template_cancel(
    mock_boto,
    mock_input,
):

    mock_input.return_value = "n"

    client = MagicMock()

    mock_boto.return_value = client

    client.get_experiment_template.return_value = {
        "experimentTemplate": {
            "id": "template-1",
            "description": "Chaos",
        }
    }

    delete_template(
        "template-1",
        "eu-central-1",
    )

    client.delete_experiment_template.assert_not_called()
