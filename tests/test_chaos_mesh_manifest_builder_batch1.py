import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_manifest_builder import (
    ChaosMeshManifestBuilder,
)


@pytest.fixture
def builder():
    return ChaosMeshManifestBuilder()


def test_build_time_chaos(builder):
    manifest = builder.build_time_chaos(
        name="clock-offset",
        mode="one",
        clock="CLOCK_MONOTONIC",
        offset="5m",
        namespace="default",
        selector={
            "labelSelectors": {
                "app": "demo",
            }
        },
        container_names=["app"],
        duration="30s",
    )

    assert manifest["kind"] == "TimeChaos"
    assert manifest["metadata"]["name"] == "clock-offset"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["clock"] == "CLOCK_MONOTONIC"
    assert manifest["spec"]["offset"] == "5m"
    assert manifest["spec"]["containerNames"] == ["app"]
    assert manifest["spec"]["duration"] == "30s"


def test_time_chaos_requires_clock(builder):
    with pytest.raises(
        ValueError,
        match="clock is required",
    ):
        builder.build_time_chaos(
            name="invalid",
            mode="one",
            clock="",
            offset="5m",
        )


def test_time_chaos_requires_offset(builder):
    with pytest.raises(
        ValueError,
        match="offset is required",
    ):
        builder.build_time_chaos(
            name="invalid",
            mode="one",
            clock="CLOCK_MONOTONIC",
            offset="",
        )


def test_build_kernel_chaos(builder):
    manifest = builder.build_kernel_chaos(
        name="kernel-fault",
        mode="one",
        fail_kern={
            "type": "FAULT",
            "value": "1",
        },
        selector={
            "nodes": ["node-1"],
        },
        duration="30s",
    )

    assert manifest["kind"] == "KernelChaos"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["failKern"]["type"] == "FAULT"
    assert manifest["spec"]["failKern"]["value"] == "1"
    assert manifest["spec"]["duration"] == "30s"


def test_kernel_chaos_requires_fail_kern(builder):
    with pytest.raises(
        ValueError,
        match="fail_kern configuration",
    ):
        builder.build_kernel_chaos(
            name="invalid",
            mode="one",
            fail_kern={},
        )


def test_build_aws_ec2_stop(builder):
    manifest = builder.build_aws_chaos(
        name="ec2-stop",
        action="ec2-stop",
        aws_region="eu-central-1",
        ec2_instance="i-1234567890",
        secret_name="aws-secret",
        duration="5m",
    )

    assert manifest["kind"] == "AWSChaos"
    assert manifest["spec"]["action"] == "ec2-stop"
    assert manifest["spec"]["awsRegion"] == "eu-central-1"
    assert manifest["spec"]["ec2Instance"] == "i-1234567890"
    assert manifest["spec"]["secretName"] == "aws-secret"
    assert manifest["spec"]["duration"] == "5m"


def test_build_aws_ec2_restart(builder):
    manifest = builder.build_aws_chaos(
        name="ec2-restart",
        action="ec2-restart",
        aws_region="eu-central-1",
        ec2_instance="i-1234567890",
    )

    assert manifest["kind"] == "AWSChaos"
    assert manifest["spec"]["action"] == "ec2-restart"


def test_build_aws_detach_volume(builder):
    manifest = builder.build_aws_chaos(
        name="detach-volume",
        action="detach-volume",
        aws_region="eu-central-1",
        ec2_instance="i-1234567890",
        volume_id="vol-1234567890",
        device_name="/dev/sdf",
        duration="5m",
    )

    assert manifest["kind"] == "AWSChaos"
    assert manifest["spec"]["action"] == "detach-volume"
    assert manifest["spec"]["volumeID"] == "vol-1234567890"
    assert manifest["spec"]["deviceName"] == "/dev/sdf"


def test_aws_detach_volume_requires_volume_id(builder):
    with pytest.raises(
        ValueError,
        match="requires volume_id",
    ):
        builder.build_aws_chaos(
            name="invalid",
            action="detach-volume",
            aws_region="eu-central-1",
            ec2_instance="i-1234567890",
            device_name="/dev/sdf",
        )


def test_aws_detach_volume_requires_device_name(builder):
    with pytest.raises(
        ValueError,
        match="requires device_name",
    ):
        builder.build_aws_chaos(
            name="invalid",
            action="detach-volume",
            aws_region="eu-central-1",
            ec2_instance="i-1234567890",
            volume_id="vol-1234567890",
        )


def test_aws_requires_region(builder):
    with pytest.raises(
        ValueError,
        match="aws_region is required",
    ):
        builder.build_aws_chaos(
            name="invalid",
            action="ec2-stop",
            aws_region="",
            ec2_instance="i-1234567890",
        )


def test_aws_requires_instance(builder):
    with pytest.raises(
        ValueError,
        match="ec2_instance is required",
    ):
        builder.build_aws_chaos(
            name="invalid",
            action="ec2-stop",
            aws_region="eu-central-1",
            ec2_instance="",
        )


def test_aws_rejects_unknown_action(builder):
    with pytest.raises(
        ValueError,
        match="Unsupported AWSChaos action",
    ):
        builder.build_aws_chaos(
            name="invalid",
            action="terminate-node",
            aws_region="eu-central-1",
            ec2_instance="i-1234567890",
        )
