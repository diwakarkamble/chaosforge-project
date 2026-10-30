from unittest.mock import MagicMock

from chaosforge.application.component_fis import (
    bind_component_fis,
    fis_target_selector,
    prepare_component_fis_variables,
)
from chaosforge.providers.aws.fis import component_actions


def test_component_fis_binds_target_selector_and_hides_generic_selectors(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.return_value = {
        "id": "stop-instances",
        "name": "Stop EC2 Instances",
        "resource_type": "aws:ec2:instance",
        "parameters": [{"name": "duration", "label": "Duration", "default": "PT5M"}],
    }
    monkeypatch.setattr("chaosforge.application.component_fis.FISCatalog", MagicMock(return_value=catalog))
    metadata = {
        "name": "Create FIS",
        "inputs": [
            {"name": "service_id"},
            {"name": "experiment_id"},
            {"name": "created_by"},
            {"name": "target_arn", "label": "Target"},
        ],
    }

    bound = bind_component_fis(metadata, "ec2", "stop-instances")

    assert bound["fis_target_selector"] == "ec2"
    assert [field["name"] for field in bound["inputs"]] == ["target_arn", "duration", "created_by"]
    assert bound["inputs"][0]["label"] == "EC2 Target"


def test_component_fis_selector_mapping_includes_supported_fis_resource_types():
    assert fis_target_selector("rds", {"resource_type": "aws:rds:cluster"}) == "rds-cluster"
    assert fis_target_selector("ecs", {"resource_type": "aws:ecs:task"}) == "ecs_task"
    assert fis_target_selector("ec2", {"resource_type": "aws:ec2:ebs-volume"}) == "ebs-volume"
    assert fis_target_selector("ec2", {"resource_type": "unsupported"}) is None


def test_component_fis_selector_maps_elasticache_replication_groups():
    assert fis_target_selector(
        "elasticache", {"resource_type": "aws:elasticache:replicationgroup"}
    ) == "elasticache-replication-group"


def test_component_fis_dispatches_lambda_and_generic_actions(monkeypatch):
    generic = MagicMock()
    component = MagicMock()
    monkeypatch.setattr(component_actions, "create_experiment", generic, raising=False)
    lambda_module = MagicMock(execute=component)
    monkeypatch.setattr(component_actions, "import_module", MagicMock(return_value=lambda_module))

    component_actions.execute({"service_id": "lambda"}, generic)
    component.assert_called_once()

    variables = {
        "service_id": "ec2",
        "experiment_name": "Stop",
        "description": "Test",
        "experiment_id": "stop-instances",
        "target_arn": "arn:aws:ec2:region:account:instance/i-1",
        "role_arn": "arn:aws:iam::account:role/FIS",
        "aws_region": "eu-central-1",
    }
    component_actions.execute(variables, generic)
    assert generic.call_args.kwargs["service_id"] == "ec2"


def test_component_fis_variable_preparation_ignores_non_eks_actions(monkeypatch):
    load = MagicMock()
    monkeypatch.setattr("chaosforge.application.component_fis.import_module", load)
    variables = {"service_id": "rds", "experiment_id": "reboot-instance"}

    assert prepare_component_fis_variables(variables) is variables
    load.assert_not_called()


def test_component_fis_variable_preparation_routes_eks_actions(monkeypatch):
    prepare = MagicMock()
    module = MagicMock(prepare=prepare)
    monkeypatch.setattr("chaosforge.application.component_fis.import_module", MagicMock(return_value=module))
    variables = {"service_id": "eks", "experiment_id": "pod-delete"}

    assert prepare_component_fis_variables(variables) is variables
    prepare.assert_called_once_with(variables)
