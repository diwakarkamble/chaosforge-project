import pytest

from chaosforge.providers.aws.fis.template_builder import FISTemplateBuilder


def test_template_builder():

    builder = FISTemplateBuilder()

    service = {"id": "lambda"}

    experiment = {
        "fis_action": "aws:lambda:invocation-add-delay",
        "target_key": "Functions",
    }

    template = builder.build(
        service=service,
        experiment=experiment,
        experiment_name="Demo",
        description="Test",
        target_arn="arn:test",
        role_arn="arn:role",
        parameters={"duration": "PT5M"},
    )

    assert template["roleArn"] == "arn:role"

    assert "targets" in template

    assert "actions" in template

    assert (
        template["actions"]["Action1"]["actionId"] == "aws:lambda:invocation-add-delay"
    )


def test_elasticache_fis_template_uses_aws_replicationgroup_target_type():
    target_arn = "arn:aws:elasticache:eu-central-1:123:replicationgroup:redis"
    experiment = {
        "fis_action": "aws:elasticache:replicationgroup-interrupt-az-power",
        "target_key": "ReplicationGroups",
        "resource_type": "aws:elasticache:replicationgroup",
        "parameters": [
            {"name": "availability_zone_identifier", "aws_name": "availabilityZoneIdentifier", "target_parameter": True},
            {"name": "duration"},
        ],
    }
    client = MagicMock()
    client.list_tags_for_resource.return_value = {
        "TagList": [{"Key": "Chaosforge", "Value": "E2E-Test"}]
    }

    with patch("chaosforge.providers.aws.fis.template_builder.boto3.client", return_value=client) as make_client:
        template = FISTemplateBuilder().build(
            service={"id": "elasticache"},
            experiment=experiment,
            experiment_name="Interrupt AZ Power",
            description="Test",
            target_arn=target_arn,
            role_arn="arn:aws:iam::123:role/FIS",
            parameters={
                "duration": "PT5M",
                "availability_zone_identifier": "eu-central-1a",
            },
            region="eu-central-1",
        )

    make_client.assert_called_once_with("elasticache", region_name="eu-central-1")
    client.list_tags_for_resource.assert_called_once_with(ResourceName=target_arn)
    target = template["targets"]["Target1"]
    assert target["resourceType"] == "aws:elasticache:replicationgroup"
    assert target["resourceTags"] == {"Chaosforge": "E2E-Test"}
    assert target["parameters"] == {"availabilityZoneIdentifier": "eu-central-1a"}
    assert "resourceArns" not in target
    assert template["actions"]["Action1"]["parameters"] == {"duration": "PT5M"}


def test_elasticache_fis_template_requires_tags_and_required_target_parameters():
    experiment = {
        "id": "interrupt-az-power",
        "fis_action": "aws:elasticache:replicationgroup-interrupt-az-power",
        "target_key": "ReplicationGroups",
        "resource_type": "aws:elasticache:replicationgroup",
        "parameters": [
            {
                "name": "availability_zone_identifier",
                "target_parameter": True,
            }
        ],
    }
    client = MagicMock()

    with patch("chaosforge.providers.aws.fis.template_builder.boto3.client", return_value=client):
        client.list_tags_for_resource.return_value = {"TagList": []}
        with pytest.raises(ValueError, match="must have at least one resource tag"):
            FISTemplateBuilder().build(
                service={"id": "elasticache"},
                experiment=experiment,
                experiment_name="Interrupt AZ Power",
                description="Test",
                target_arn="arn:aws:elasticache:eu-central-1:123:replicationgroup:redis",
                role_arn="arn:aws:iam::123:role/FIS",
                parameters={},
                region="eu-central-1",
            )

        client.list_tags_for_resource.return_value = {"TagList": [{"Key": "Name", "Value": "redis"}]}
        with pytest.raises(ValueError, match="availability_zone_identifier.*required"):
            FISTemplateBuilder().build(
                service={"id": "elasticache"},
                experiment=experiment,
                experiment_name="Interrupt AZ Power",
                description="Test",
                target_arn="arn:aws:elasticache:eu-central-1:123:replicationgroup:redis",
                role_arn="arn:aws:iam::123:role/FIS",
                parameters={"availability_zone_identifier": ""},
                region="eu-central-1",
            )

        experiment["parameters"][0]["required"] = False
        template = FISTemplateBuilder().build(
            service={"id": "elasticache"},
            experiment=experiment,
            experiment_name="Interrupt AZ Power",
            description="Test",
            target_arn="arn:aws:elasticache:eu-central-1:123:replicationgroup:redis",
            role_arn="arn:aws:iam::123:role/FIS",
            parameters={"availability_zone_identifier": ""},
            region="eu-central-1",
        )
    assert "parameters" not in template["targets"]["Target1"]


def test_rds_cluster_failover_template_uses_aws_fis_cluster_target_contract():
    template = FISTemplateBuilder().build(
        service={"id": "rds"},
        experiment={
            "id": "failover-db-cluster",
            "fis_action": "aws:rds:failover-db-cluster",
            "target_key": "Clusters",
            "resource_type": "aws:rds:cluster",
        },
        experiment_name="Failover DB Cluster",
        description="Test",
        target_arn="arn:aws:rds:eu-central-1:123:cluster:database-cluster",
        role_arn="arn:aws:iam::123:role/FIS",
        parameters={},
    )

    assert template["targets"]["Target1"] == {
        "resourceType": "aws:rds:cluster",
        "resourceArns": ["arn:aws:rds:eu-central-1:123:cluster:database-cluster"],
        "selectionMode": "ALL",
    }
    assert template["actions"]["Action1"]["targets"] == {"Clusters": "Target1"}
    assert template["actions"]["Action1"]["parameters"] == {}


def test_eks_custom_resource_template_uses_the_singular_cluster_target_key():
    template = FISTemplateBuilder().build(
        service={"id": "eks"},
        experiment={
            "id": "inject-kubernetes-custom-resource",
            "fis_action": "aws:eks:inject-kubernetes-custom-resource",
            "target_key": "Cluster",
            "resource_type": "aws:eks:cluster",
            "parameters": [
                {"name": "kubernetes_api_version", "aws_name": "kubernetesApiVersion"},
                {"name": "kubernetes_kind", "aws_name": "kubernetesKind"},
                {"name": "kubernetes_namespace", "aws_name": "kubernetesNamespace"},
                {"name": "kubernetes_spec", "aws_name": "kubernetesSpec"},
                {"name": "max_duration", "aws_name": "maxDuration"},
            ],
        },
        experiment_name="Inject Kubernetes Custom Resource",
        description="Test",
        target_arn="arn:aws:eks:eu-central-1:123:cluster/example",
        role_arn="arn:aws:iam::123:role/FIS",
        parameters={
            "kubernetes_api_version": "chaos-mesh.org/v1alpha1",
            "kubernetes_kind": "StressChaos",
            "kubernetes_namespace": "sample-app",
            "kubernetes_spec": "{}",
            "max_duration": "PT2M",
        },
    )

    assert template["actions"]["Action1"]["targets"] == {"Cluster": "Target1"}
    assert template["targets"]["Target1"] == {
        "resourceType": "aws:eks:cluster",
        "resourceArns": ["arn:aws:eks:eu-central-1:123:cluster/example"],
        "selectionMode": "ALL",
    }


@pytest.mark.parametrize(
    "experiment",
    [
        {
            "id": "stop-instances",
            "fis_action": "aws:ec2:stop-instances",
            "target_key": "Instances",
            "resource_type": "aws:ec2:instance",
            "parameters": [
                {
                    "name": "start_instances_after_duration",
                    "aws_name": "startInstancesAfterDuration",
                }
            ],
        },
        {
            "id": "reboot-instances",
            "fis_action": "aws:ec2:reboot-instances",
            "target_key": "Instances",
            "resource_type": "aws:ec2:instance",
            "parameters": [],
        },
        {
            "id": "terminate-instances",
            "fis_action": "aws:ec2:terminate-instances",
            "target_key": "Instances",
            "resource_type": "aws:ec2:instance",
            "parameters": [],
        },
        {
            "id": "spot-instance-interruption",
            "fis_action": "aws:ec2:send-spot-instance-interruptions",
            "target_key": "SpotInstances",
            "resource_type": "aws:ec2:spot-instance",
            "parameters": [
                {
                    "name": "duration_before_interruption",
                    "aws_name": "durationBeforeInterruption",
                }
            ],
        },
        {
            "id": "insufficient-instance-capacity-error",
            "fis_action": "aws:ec2:api-insufficient-instance-capacity-error",
            "target_key": "Roles",
            "resource_type": "aws:iam:role",
            "parameters": [
                {
                    "name": "duration",
                    "aws_name": "duration",
                },
                {
                    "name": "availability_zone_identifiers",
                    "aws_name": "availabilityZoneIdentifiers",
                },
                {
                    "name": "percentage",
                    "aws_name": "percentage",
                },
            ],
        },
        {
            "id": "asg-insufficient-instance-capacity-error",
            "fis_action": "aws:ec2:asg-insufficient-instance-capacity-error",
            "target_key": "AutoScalingGroups",
            "resource_type": "aws:ec2:autoscaling-group",
            "parameters": [
                {
                    "name": "duration",
                    "aws_name": "duration",
                },
                {
                    "name": "availability_zone_identifiers",
                    "aws_name": "availabilityZoneIdentifiers",
                },
                {
                    "name": "percentage",
                    "aws_name": "percentage",
                },
            ],
        },
    ],
)
def test_ec2_fis_template_builder(experiment):

    builder = FISTemplateBuilder()

    template = builder.build(
        service={"id": "ec2"},
        experiment=experiment,
        experiment_name="EC2 Chaos Test",
        description="EC2 FIS test",
        target_arn="arn:aws:ec2:eu-central-1:123456789012:instance/i-test",
        role_arn="arn:aws:iam::123456789012:role/FISRole",
        parameters={
            "start_instances_after_duration": "PT5M",
            "duration_before_interruption": "PT2M",
            "duration": "PT5M",
            "availability_zone_identifiers": "eu-central-1a",
            "percentage": 100,
        },
    )

    action = template["actions"]["Action1"]
    target = template["targets"]["Target1"]

    assert action["actionId"] == experiment["fis_action"]
    assert action["targets"] == {experiment["target_key"]: "Target1"}

    assert target["resourceType"] == experiment["resource_type"]
    assert target["resourceArns"] == [
        "arn:aws:ec2:eu-central-1:123456789012:instance/i-test"
    ]
    assert target["selectionMode"] == "ALL"


@pytest.mark.parametrize(
    "experiment",
    [
        {
            "id": "kinesis-provisioned-throughput-exception",
            "fis_action": "aws:kinesis:stream-provisioned-throughput-exception",
            "target_key": "KinesisStreams",
            "resource_type": "aws:kinesis:stream",
            "parameters": [
                {
                    "name": "duration",
                    "aws_name": "duration",
                },
                {
                    "name": "percentage",
                    "aws_name": "percentage",
                },
            ],
        },
        {
            "id": "kinesis-expired-iterator-exception",
            "fis_action": "aws:kinesis:stream-expired-iterator-exception",
            "target_key": "KinesisStreams",
            "resource_type": "aws:kinesis:stream",
            "parameters": [
                {
                    "name": "duration",
                    "aws_name": "duration",
                },
                {
                    "name": "percentage",
                    "aws_name": "percentage",
                },
            ],
        },
    ],
)
def test_kinesis_fis_template_builder(experiment):

    builder = FISTemplateBuilder()

    template = builder.build(
        service={"id": "kinesis"},
        experiment=experiment,
        experiment_name="Kinesis Chaos Test",
        description="Kinesis FIS test",
        target_arn=("arn:aws:kinesis:eu-central-1:123456789012:stream/test-stream"),
        role_arn="arn:aws:iam::123456789012:role/FISRole",
        parameters={
            "duration": "PT5M",
            "percentage": 100,
        },
    )

    action = template["actions"]["Action1"]
    target = template["targets"]["Target1"]

    assert action["actionId"] == experiment["fis_action"]
    assert action["targets"] == {"KinesisStreams": "Target1"}

    assert action["parameters"] == {
        "duration": "PT5M",
        "percentage": "100",
    }

    assert target["resourceType"] == "aws:kinesis:stream"
    assert target["resourceArns"] == [
        "arn:aws:kinesis:eu-central-1:123456789012:stream/test-stream"
    ]
    assert target["selectionMode"] == "ALL"


from unittest.mock import MagicMock, patch


def test_build_target_uses_default_resource_type():
    builder = FISTemplateBuilder()

    target = builder._build_target(
        service={"id": "lambda"},
        experiment={},
        target_arn="arn:lambda:test",
        parameters={},
        region=None,
    )

    assert target == {
        "resourceType": "aws:lambda:function",
        "resourceArns": ["arn:lambda:test"],
        "selectionMode": "ALL",
    }


def test_build_target_rejects_unsupported_service():
    builder = FISTemplateBuilder()

    with pytest.raises(
        ValueError,
        match="Unsupported FIS service: unknown",
    ):
        builder._build_target(
            service={"id": "unknown"},
            experiment={},
            target_arn="arn:test",
            parameters={},
            region=None,
        )


def test_build_target_s3_uses_resource_tags():
    builder = FISTemplateBuilder()

    target = builder._build_target(
        service={"id": "s3"},
        experiment={},
        target_arn="arn:aws:s3:::test",
        parameters={
            "tag_key": "Environment",
            "tag_value": "ChaosTest",
        },
        region=None,
    )

    assert target == {
        "resourceType": "aws:s3:bucket",
        "resourceTags": {
            "Environment": "ChaosTest",
        },
        "selectionMode": "ALL",
    }


def test_build_target_s3_uses_default_tag_key():
    builder = FISTemplateBuilder()

    target = builder._build_target(
        service={"id": "s3"},
        experiment={},
        target_arn="arn:aws:s3:::test",
        parameters={
            "tag_value": "Production",
        },
        region=None,
    )

    assert target["resourceTags"] == {
        "Name": "Production",
    }


def test_build_target_s3_rejects_empty_tag_value():
    builder = FISTemplateBuilder()

    with pytest.raises(
        ValueError,
        match="Resource Tag Value is required for S3 FIS experiments",
    ):
        builder._build_target(
            service={"id": "s3"},
            experiment={},
            target_arn="arn:aws:s3:::test",
            parameters={
                "tag_key": "Environment",
                "tag_value": "   ",
            },
            region=None,
        )


@patch("chaosforge.providers.aws.fis.template_builder.boto3.client")
def test_normalize_ec2_instance_id_to_arn(mock_boto_client):
    builder = FISTemplateBuilder()

    sts_client = MagicMock()
    sts_client.get_caller_identity.return_value = {
        "Account": "123456789012",
    }
    mock_boto_client.return_value = sts_client

    result = builder._normalize_ec2_target(
        " i-1234567890abcdef0 ",
        "eu-central-1",
    )

    assert (
        result
        == "arn:aws:ec2:eu-central-1:123456789012:instance/"
        "i-1234567890abcdef0"
    )

    mock_boto_client.assert_called_once_with(
        "sts",
        region_name="eu-central-1",
    )

    sts_client.get_caller_identity.assert_called_once_with()


def test_normalize_ec2_existing_arn():
    builder = FISTemplateBuilder()

    target = (
        "arn:aws:ec2:eu-central-1:123456789012:"
        "instance/i-1234567890abcdef0"
    )

    result = builder._normalize_ec2_target(
        target,
        "eu-central-1",
    )

    assert result == target


@pytest.mark.parametrize(
    "target",
    [
        None,
        "",
        "   ",
        "invalid-instance-id",
    ],
)
def test_normalize_ec2_invalid_target(target):
    builder = FISTemplateBuilder()

    with pytest.raises(ValueError):
        builder._normalize_ec2_target(
            target,
            "eu-central-1",
        )


def test_build_target_normalizes_ec2_instance_id():
    builder = FISTemplateBuilder()

    with patch.object(
        builder,
        "_normalize_ec2_target",
        return_value="arn:normalized",
    ) as mock_normalize:

        target = builder._build_target(
            service={"id": "ec2"},
            experiment={
                "resource_type": "aws:ec2:instance",
            },
            target_arn="i-1234567890abcdef0",
            parameters={},
            region="eu-central-1",
        )

    mock_normalize.assert_called_once_with(
        "i-1234567890abcdef0",
        "eu-central-1",
    )

    assert target["resourceArns"] == ["arn:normalized"]


def test_build_action_maps_parameters_and_skips_target_parameters():
    builder = FISTemplateBuilder()

    experiment = {
        "id": "test-experiment",
        "fis_action": "aws:test:action",
        "target_key": "Instances",
        "parameters": [
            {
                "name": "duration",
                "aws_name": "durationSeconds",
            },
            {
                "name": "enabled",
                "aws_name": "enabled",
            },
        ],
    }

    action = builder._build_action(
        experiment,
        {
            "duration": "PT5M",
            "enabled": True,
            "tag_key": "Environment",
            "tag_value": "Test",
            "empty": "",
            "none_value": None,
            "unknown": 42,
        },
    )

    assert action["parameters"] == {
        "durationSeconds": "PT5M",
        "enabled": "true",
        "unknown": "42",
    }

    assert action["targets"] == {
        "Instances": "Target1",
    }


def test_build_action_converts_false_boolean():
    builder = FISTemplateBuilder()

    experiment = {
        "id": "test-experiment",
        "fis_action": "aws:test:action",
        "target_key": "Instances",
        "parameters": [
            {
                "name": "enabled",
            },
        ],
    }

    action = builder._build_action(
        experiment,
        {
            "enabled": False,
        },
    )

    assert action["parameters"] == {
        "enabled": "false",
    }


def test_build_action_missing_target_key():
    builder = FISTemplateBuilder()

    experiment = {
        "id": "test-experiment",
        "fis_action": "aws:test:action",
    }

    with pytest.raises(
        ValueError,
        match="Missing 'target_key' for experiment 'test-experiment'",
    ):
        builder._build_action(
            experiment,
            {},
        )
