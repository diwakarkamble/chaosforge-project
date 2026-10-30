import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions import (
    apigateway_access_logging_actions as access_logging,
)
from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions import (
    apigateway_common as api_common,
)
from chaosforge.providers.aws.components.apigateway.experiments.toolkit.actions import (
    apigateway_stage_throttling_actions as throttling,
)
from chaosforge.providers.aws.components.ec2.experiments.toolkit.actions import (
    ec2_common,
    ec2_ebs_actions,
    ec2_incremental_actions,
)
from chaosforge.providers.aws.components.ecs.experiments.toolkit.actions import ecs_common
from chaosforge.providers.aws.components.elasticache.experiments.toolkit.actions import (
    elasticache_common,
)
from chaosforge.providers.aws.components.elb.experiments.toolkit.actions import (
    elb_common,
    elb_load_balancer_actions,
)
from chaosforge.providers.aws.components.sns.experiments.toolkit.actions import (
    sns_topic_policy_actions,
)
from chaosforge.providers.aws.components.vpc.experiments.toolkit.actions import (
    vpc_internet_gateway_actions,
    vpc_network_acl_actions,
    vpc_route_table_actions,
    vpc_security_group_actions,
)
from chaosforge.providers.aws.fis import actions as fis_actions


def _fis_catalog_and_builder(monkeypatch):
    catalog = MagicMock()
    catalog.get_service.return_value = {"id": "ec2"}
    catalog.get_experiment.return_value = {"parameters": []}
    builder = MagicMock()
    builder.build.return_value = {}
    monkeypatch.setattr(fis_actions, "FISCatalog", MagicMock(return_value=catalog))
    monkeypatch.setattr(fis_actions, "FISTemplateBuilder", MagicMock(return_value=builder))
    return builder


@pytest.mark.parametrize("parameters", ["[1]", "true", "1"])
def test_fis_rejects_non_object_serialized_parameters(monkeypatch, parameters):
    _fis_catalog_and_builder(monkeypatch)

    with pytest.raises(TypeError, match="must be a JSON object"):
        fis_actions.create_experiment(
            "name", "description", "owner", "ec2", "stop", "i-1", "role", "region",
            fis_action_parameters_json=parameters,
        )


def test_fis_rejects_malformed_serialized_parameters(monkeypatch):
    _fis_catalog_and_builder(monkeypatch)

    with pytest.raises(ValueError, match="Invalid serialized"):
        fis_actions.create_experiment(
            "name", "description", "owner", "ec2", "stop", "i-1", "role", "region",
            fis_action_parameters_json="{broken",
        )


def test_fis_records_both_recovery_states(monkeypatch, tmp_path):
    _fis_catalog_and_builder(monkeypatch)
    client = MagicMock()
    client.create_experiment_template.return_value = {"experimentTemplate": {"id": "tpl-1"}}
    client.start_experiment.return_value = {
        "experiment": {"id": "exp-1", "state": {"status": "completed"}}
    }
    monkeypatch.setattr(fis_actions.boto3, "client", MagicMock(return_value=client))
    recovery_file = tmp_path / "fis.json"

    fis_actions.create_experiment(
        "name", "description", "owner", "ec2", "stop", "i-1", "role", "region",
        recovery_file=str(recovery_file),
    )

    assert json.loads(recovery_file.read_text(encoding="utf-8")) == {
        "template_id": "tpl-1",
        "experiment_id": "exp-1",
    }
    client.get_experiment.assert_not_called()


def test_fis_times_out_without_polling_aws(monkeypatch):
    _fis_catalog_and_builder(monkeypatch)
    client = MagicMock()
    client.create_experiment_template.return_value = {"experimentTemplate": {"id": "tpl-1"}}
    client.start_experiment.return_value = {
        "experiment": {"id": "exp-1", "state": {"status": "running"}}
    }
    monkeypatch.setattr(fis_actions.boto3, "client", MagicMock(return_value=client))
    monkeypatch.setattr(fis_actions.time, "monotonic", MagicMock(side_effect=[10, 15]))

    with pytest.raises(TimeoutError, match="did not finish within 5 seconds"):
        fis_actions.create_experiment(
            "name", "description", "owner", "ec2", "stop", "i-1", "role", "region",
            execution_timeout=5,
        )

    client.get_experiment.assert_not_called()


def test_fis_recovery_reports_terminal_experiment(monkeypatch, tmp_path):
    recovery_file = tmp_path / "fis.json"
    recovery_file.write_text('{"experiment_id":"exp-1"}', encoding="utf-8")
    client = MagicMock()
    client.get_experiment.return_value = {
        "experiment": {"state": {"status": "completed"}}
    }
    monkeypatch.setattr(fis_actions.boto3, "client", MagicMock(return_value=client))

    result = fis_actions.recover_interrupted_experiment(str(recovery_file), "region")

    assert result == {
        "success": True,
        "messages": ["FIS experiment exp-1 is already completed."],
    }
    client.stop_experiment.assert_not_called()


def test_fis_recovery_aggregates_stop_and_delete_errors(monkeypatch, tmp_path):
    recovery_file = tmp_path / "fis.json"
    recovery_file.write_text(
        '{"experiment_id":"exp-1","template_id":"tpl-1"}', encoding="utf-8"
    )
    client = MagicMock()
    client.get_experiment.side_effect = RuntimeError("get failed")
    client.delete_experiment_template.side_effect = RuntimeError("delete failed")
    monkeypatch.setattr(fis_actions.boto3, "client", MagicMock(return_value=client))

    result = fis_actions.recover_interrupted_experiment(str(recovery_file), "region")

    assert result["success"] is False
    assert result["messages"] == [
        "Failed to stop FIS experiment exp-1: get failed",
        "Failed to delete FIS template tpl-1: delete failed",
    ]


def test_http_api_common_uses_v2_shapes(monkeypatch):
    client = MagicMock()
    boto_client = MagicMock(return_value=client)
    monkeypatch.setattr(api_common, "context", SimpleNamespace(apigateway_protocol="http"))
    monkeypatch.setattr(api_common.boto3, "client", boto_client)
    client.get_stage.return_value = {"StageName": "dev"}

    assert api_common.get_client("region") is client
    assert api_common.get_stage("api-1", "dev", "region") == {"StageName": "dev"}
    api_common.update_stage(
        "api-1",
        "dev",
        {
            "AccessLogSettings": {"DestinationArn": "arn:logs"},
            "DefaultRouteSettings": {"ThrottlingRateLimit": 1},
            "Ignored": True,
        },
        "region",
    )

    boto_client.assert_called_with("apigatewayv2", region_name="region")
    client.get_stage.assert_called_once_with(ApiId="api-1", StageName="dev")
    client.update_stage.assert_called_once_with(
        ApiId="api-1",
        StageName="dev",
        AccessLogSettings={"DestinationArn": "arn:logs"},
        DefaultRouteSettings={"ThrottlingRateLimit": 1},
    )


def test_http_access_logging_disable_and_restore(monkeypatch, tmp_path):
    state_file = tmp_path / "access.json"
    client = MagicMock()
    monkeypatch.setattr(access_logging, "STATE_FILE", str(state_file))
    monkeypatch.setattr(access_logging, "context", SimpleNamespace(apigateway_protocol="HTTP"))
    monkeypatch.setattr(access_logging, "get_client", MagicMock(return_value=client))
    monkeypatch.setattr(
        access_logging,
        "get_stage",
        MagicMock(
            return_value={
                "AccessLogSettings": {"DestinationArn": "arn:logs", "Format": "$context.requestId"}
            }
        ),
    )

    access_logging.capture_and_disable_access_logging("api-1", "dev", "region")
    access_logging.restore_access_logging()

    assert client.update_stage.call_args_list == [
        call(ApiId="api-1", StageName="dev", AccessLogSettings={}),
        call(
            ApiId="api-1",
            StageName="dev",
            AccessLogSettings={
                "DestinationArn": "arn:logs",
                "Format": "$context.requestId",
            },
        ),
    ]
    assert not state_file.exists()


def test_http_throttling_is_rejected_and_rollback_is_noop(monkeypatch):
    monkeypatch.setattr(throttling, "context", SimpleNamespace(apigateway_protocol="HTTP"))
    client_factory = MagicMock()
    monkeypatch.setattr(throttling, "get_client", client_factory)

    with pytest.raises(RuntimeError, match="supported only for REST APIs"):
        throttling.capture_and_update_throttling("api", "dev", "region", 1, 1)
    assert throttling.rollback_throttling() is None
    client_factory.assert_not_called()


def test_ec2_common_empty_instance_page(monkeypatch):
    client = MagicMock()
    client.describe_instances.return_value = {"Reservations": [{"Instances": []}]}
    monkeypatch.setattr(ec2_common, "get_client", MagicMock(return_value=client))

    with pytest.raises(RuntimeError, match="i-empty.*not found"):
        ec2_common.describe_instance("i-empty", "region")


def test_ec2_volume_helpers_and_wait(monkeypatch):
    client = MagicMock()
    client.describe_volumes.side_effect = [
        {"Volumes": [{"VolumeId": "vol-1", "State": "available"}]},
        {"Volumes": []},
    ]
    monkeypatch.setattr(ec2_common, "get_client", MagicMock(return_value=client))
    monkeypatch.setattr(
        ec2_common,
        "describe_instance",
        MagicMock(return_value={"RootDeviceName": "/dev/xvda"}),
    )
    sleep = MagicMock()
    monkeypatch.setattr(ec2_common.time, "sleep", sleep)

    assert ec2_common.describe_volume("vol-1", "region")["State"] == "available"
    with pytest.raises(RuntimeError, match="vol-missing.*not found"):
        ec2_common.describe_volume("vol-missing", "region")
    assert ec2_common.get_root_device("i-1", "region") == "/dev/xvda"
    ec2_common.wait_for_seconds("2.5")

    sleep.assert_called_once_with(2.5)


@pytest.mark.parametrize(
    ("instance_ids", "expected"),
    [
        ('[" i-1 ", "", "i-2"]', ["i-1", "i-2"]),
        ("i-3", ["i-3"]),
        (("i-4", " i-5 "), ["i-4", "i-5"]),
    ],
)
def test_incremental_normalizes_supported_inputs(monkeypatch, instance_ids, expected):
    client = MagicMock()
    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {"InstanceId": value, "State": {"Name": "running"}}
                    for value in expected
                ]
            }
        ]
    }
    monkeypatch.setattr(ec2_incremental_actions, "get_client", MagicMock(return_value=client))

    ec2_incremental_actions.stop_instances_incrementally(
        instance_ids, 10, 0, "region"
    )

    client.stop_instances.assert_called_once_with(InstanceIds=expected)


@pytest.mark.parametrize("instance_ids", [123, '{"instance":"i-1"}'])
def test_incremental_rejects_unsupported_inputs(instance_ids):
    with pytest.raises(TypeError, match="instance_ids must be"):
        ec2_incremental_actions.stop_instances_incrementally(
            instance_ids, 1, 0, "region"
        )


def test_incremental_rejects_values_normalized_to_empty():
    with pytest.raises(ValueError, match="At least one"):
        ec2_incremental_actions.stop_instances_incrementally(
            ["", "  "], 1, 0, "region"
        )


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("", "vol-1", "/dev/sdf", "region"), "Auto Scaling Group"),
        (("asg", "", "/dev/sdf", "region"), "volume ID"),
        (("asg", "vol-1", "", "region"), "device name"),
    ],
)
def test_asg_attachment_validates_required_inputs(args, message):
    with pytest.raises(ValueError, match=message):
        ec2_ebs_actions.attach_ebs_volume_to_asg_instance(*args)


def test_asg_attachment_selects_non_conflicting_instance(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ec2_ebs_actions, "_get_asg_instances", MagicMock(return_value=["i-1", "i-2"]))
    monkeypatch.setattr(ec2_ebs_actions, "get_client", MagicMock(return_value=client))
    monkeypatch.setattr(
        ec2_ebs_actions,
        "describe_volume",
        MagicMock(return_value={"State": "available"}),
    )
    monkeypatch.setattr(
        ec2_ebs_actions,
        "get_root_device",
        MagicMock(side_effect=["/dev/sdf", "/dev/xvda"]),
    )
    save_state = MagicMock()
    monkeypatch.setattr(ec2_ebs_actions, "save_state", save_state)

    ec2_ebs_actions.attach_ebs_volume_to_asg_instance(
        "asg", "vol-1", "/dev/sdf", "region"
    )

    save_state.assert_called_once_with(
        ec2_ebs_actions.STATE_NAME,
        {
            "autoscaling_group": "asg",
            "instance_id": "i-2",
            "volume_id": "vol-1",
            "device_name": "/dev/sdf",
        },
    )
    client.attach_volume.assert_called_once_with(
        VolumeId="vol-1", InstanceId="i-2", Device="/dev/sdf"
    )


def test_asg_attachment_rejects_unavailable_volume(monkeypatch):
    monkeypatch.setattr(ec2_ebs_actions, "_get_asg_instances", MagicMock(return_value=["i-1"]))
    monkeypatch.setattr(ec2_ebs_actions, "get_client", MagicMock())
    monkeypatch.setattr(
        ec2_ebs_actions,
        "describe_volume",
        MagicMock(return_value={"State": "in-use"}),
    )

    with pytest.raises(ValueError, match="Current state: in-use"):
        ec2_ebs_actions.attach_ebs_volume_to_asg_instance(
            "asg", "vol-1", "/dev/sdf", "region"
        )


def test_random_asg_detach_skips_incomplete_mappings_and_parses_false(monkeypatch):
    client = MagicMock()
    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "RootDeviceName": "/dev/xvda",
                        "BlockDeviceMappings": [
                            {"DeviceName": "/dev/no-ebs"},
                            {"DeviceName": "/dev/no-volume", "Ebs": {}},
                            {"DeviceName": "/dev/sdf", "Ebs": {"VolumeId": "vol-1"}},
                        ],
                    }
                ]
            }
        ]
    }
    monkeypatch.setattr(ec2_ebs_actions, "_get_asg_instances", MagicMock(return_value=["i-1"]))
    monkeypatch.setattr(ec2_ebs_actions, "get_client", MagicMock(return_value=client))
    save_state = MagicMock()
    monkeypatch.setattr(ec2_ebs_actions, "save_state", save_state)

    ec2_ebs_actions.detach_random_asg_ebs_volume("asg", "region", force="no")

    client.detach_volume.assert_called_once_with(
        VolumeId="vol-1", InstanceId="i-1", Force=False
    )
    assert save_state.call_args.args[1]["device_name"] == "/dev/sdf"


def test_random_asg_detach_rejects_mapping_without_volume_id(monkeypatch):
    client = MagicMock()
    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "RootDeviceName": "/dev/xvda",
                        "BlockDeviceMappings": [
                            {
                                "DeviceName": "/dev/sdf",
                                "Ebs": {"DeleteOnTermination": True},
                            }
                        ],
                    }
                ]
            }
        ]
    }
    monkeypatch.setattr(ec2_ebs_actions, "_get_asg_instances", MagicMock(return_value=["i-1"]))
    monkeypatch.setattr(ec2_ebs_actions, "get_client", MagicMock(return_value=client))

    with pytest.raises(RuntimeError, match="No non-root EBS volume found"):
        ec2_ebs_actions.detach_random_asg_ebs_volume("asg", "region")

    client.detach_volume.assert_not_called()


def test_ecs_client_state_path_and_previous_revision_error(monkeypatch, tmp_path):
    boto_client = MagicMock()
    monkeypatch.setattr(ecs_common.boto3, "client", boto_client)
    monkeypatch.setattr(ecs_common.tempfile, "gettempdir", MagicMock(return_value=str(tmp_path)))

    assert ecs_common.get_client("region") is boto_client.return_value
    assert ecs_common.get_state_file("experiment") == str(tmp_path / "experiment.json")
    boto_client.assert_called_once_with("ecs", region_name="region")

    client = MagicMock()
    client.list_task_definitions.return_value = {"taskDefinitionArns": ["task:1"]}
    monkeypatch.setattr(ecs_common, "get_client", MagicMock(return_value=client))
    with pytest.raises(RuntimeError, match="Previous task definition"):
        ecs_common.get_previous_task_definition("arn/task/demo:1", "region")


def test_elasticache_wait_for_duration(monkeypatch):
    sleep = MagicMock()
    monkeypatch.setattr(elasticache_common.time, "sleep", sleep)

    elasticache_common.wait_for_duration("1.5")

    sleep.assert_called_once_with(1.5)


def test_elb_target_without_registration_id_is_rejected(monkeypatch):
    client = MagicMock()
    client.describe_target_health.return_value = {
        "TargetHealthDescriptions": [{"Target": {"Port": 80}}]
    }
    monkeypatch.setattr(elb_common, "get_client", MagicMock(return_value=client))

    with pytest.raises(RuntimeError, match="has no target registration"):
        elb_common.get_target_registration("tg", "target", "region")


@pytest.mark.parametrize(
    "load_balancer_arn,region,message",
    [("", "region", "ARN is required"), ("lb", "", "region is required")],
)
def test_get_load_balancer_attributes_validates_inputs(
    load_balancer_arn, region, message
):
    with pytest.raises(ValueError, match=message):
        elb_load_balancer_actions.get_load_balancer_attributes(
            load_balancer_arn, region
        )


def test_elb_missing_attribute_returns_none_and_blocks_modification(monkeypatch):
    attributes = [{"Key": "other", "Value": "x"}]
    assert elb_load_balancer_actions.get_attribute_value(attributes, "missing") is None
    monkeypatch.setattr(
        elb_load_balancer_actions,
        "get_load_balancer_attributes",
        MagicMock(return_value=attributes),
    )

    with pytest.raises(RuntimeError, match="attribute 'missing' was not found"):
        elb_load_balancer_actions.modify_load_balancer_attribute(
            "lb", "missing", "value", "region"
        )


def test_sns_state_file_sanitizes_topic_name(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sns_topic_policy_actions,
        "repository_paths",
        MagicMock(return_value=SimpleNamespace(rollback=tmp_path)),
    )

    path = sns_topic_policy_actions._state_file("arn:aws:sns:region:account:topic.name/test")

    assert path == tmp_path / "sns-topic-policy-topic_name_test.json"


def test_sns_restore_rejects_state_for_another_topic(monkeypatch, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"topic_arn":"arn:other","policy":"policy"}', encoding="utf-8"
    )
    monkeypatch.setattr(
        sns_topic_policy_actions, "_state_file", MagicMock(return_value=state_file)
    )
    client = MagicMock()
    monkeypatch.setattr(sns_topic_policy_actions.boto3, "client", client)

    with pytest.raises(ValueError, match="does not match"):
        sns_topic_policy_actions.restore_topic_policy("arn:target", "region")

    client.assert_not_called()
    assert state_file.exists()


@pytest.mark.parametrize(
    "module",
    [
        vpc_internet_gateway_actions,
        vpc_network_acl_actions,
        vpc_route_table_actions,
        vpc_security_group_actions,
    ],
)
def test_vpc_client_constructors_use_ec2_and_requested_region(monkeypatch, module):
    client = MagicMock()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(module.boto3, "client", constructor)

    assert module.get_client("eu-west-2") is client
    constructor.assert_called_once_with("ec2", region_name="eu-west-2")
