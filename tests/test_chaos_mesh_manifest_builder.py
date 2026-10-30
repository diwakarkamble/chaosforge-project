import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_manifest_builder import (
    ChaosMeshManifestBuilder,
)


@pytest.fixture
def builder():
    return ChaosMeshManifestBuilder()


def test_build_pod_kill(builder):
    manifest = builder.build_pod_chaos(
        name="pod-kill-test",
        namespace="default",
        action="pod-kill",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "demo",
            }
        },
    )

    assert manifest["apiVersion"] == "chaos-mesh.org/v1alpha1"
    assert manifest["kind"] == "PodChaos"
    assert manifest["metadata"]["name"] == "pod-kill-test"
    assert manifest["spec"]["action"] == "pod-kill"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["selector"]["labelSelectors"]["app"] == "demo"


def test_build_network_delay(builder):
    manifest = builder.build_network_chaos(
        name="network-delay",
        action="delay",
        mode="all",
        selector={
            "namespaces": ["default"],
            "labelSelectors": {
                "app": "web-show",
            },
        },
        delay={
            "latency": "10ms",
            "correlation": "100",
            "jitter": "0ms",
        },
    )

    assert manifest["kind"] == "NetworkChaos"
    assert manifest["spec"]["action"] == "delay"
    assert manifest["spec"]["delay"]["latency"] == "10ms"


def test_build_network_partition(builder):
    manifest = builder.build_network_chaos(
        name="network-partition",
        action="partition",
        mode="all",
        selector={
            "labelSelectors": {
                "app": "app1",
            }
        },
        direction="to",
        target={
            "mode": "all",
            "selector": {
                "labelSelectors": {
                    "app": "app2",
                }
            },
        },
    )

    assert manifest["spec"]["action"] == "partition"
    assert manifest["spec"]["direction"] == "to"
    assert manifest["spec"]["target"]["selector"]["labelSelectors"]["app"] == "app2"


def test_build_dns_error(builder):
    manifest = builder.build_dns_chaos(
        name="dns-error",
        action="error",
        mode="all",
        patterns=["example.com"],
        selector={
            "namespaces": ["default"],
        },
    )

    assert manifest["kind"] == "DNSChaos"
    assert manifest["spec"]["action"] == "error"
    assert manifest["spec"]["patterns"] == ["example.com"]


def test_build_http_abort(builder):
    manifest = builder.build_http_chaos(
        name="http-abort",
        mode="all",
        selector={
            "labelSelectors": {
                "app": "nginx",
            }
        },
        target="Request",
        port=80,
        method="GET",
        path="/api",
        abort=True,
        duration="5m",
    )

    assert manifest["kind"] == "HTTPChaos"
    assert manifest["spec"]["target"] == "Request"
    assert manifest["spec"]["port"] == 80
    assert manifest["spec"]["abort"] is True
    assert manifest["spec"]["duration"] == "5m"


def test_build_io_latency(builder):
    manifest = builder.build_io_chaos(
        name="io-latency",
        action="latency",
        mode="one",
        volume_path="/var/run/etcd",
        path="/var/run/etcd/**/*",
        delay="100ms",
        percent=50,
        duration="400s",
    )

    assert manifest["kind"] == "IOChaos"
    assert manifest["spec"]["action"] == "latency"
    assert manifest["spec"]["volumePath"] == "/var/run/etcd"
    assert manifest["spec"]["delay"] == "100ms"
    assert manifest["spec"]["percent"] == 50


def test_build_stress_cpu(builder):
    manifest = builder.build_stress_chaos(
        name="cpu-stress",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "hello-kubernetes",
            }
        },
        stressors={
            "cpu": {
                "workers": 1,
                "load": 20,
                "options": [
                    "--cpu 1",
                    "--timeout 600",
                ],
            }
        },
        duration="20s",
    )

    assert manifest["kind"] == "StressChaos"
    assert manifest["spec"]["stressors"]["cpu"]["workers"] == 1
    assert manifest["spec"]["stressors"]["cpu"]["load"] == 20


def test_build_generic_registered_kind(builder):
    manifest = builder.build_generic(
        kind="AWSChaos",
        name="aws-chaos-test",
        spec={
            "action": "example",
        },
    )

    assert manifest["kind"] == "AWSChaos"
    assert manifest["spec"]["action"] == "example"


def test_unknown_kind_rejected(builder):
    with pytest.raises(
        ValueError,
        match="Unsupported Chaos Mesh kind",
    ):
        builder.build_generic(
            kind="UnknownChaos",
            name="invalid",
            spec={},
        )


def test_invalid_pod_action_rejected(builder):
    with pytest.raises(
        ValueError,
        match="Unsupported PodChaos action",
    ):
        builder.build_pod_chaos(
            name="invalid",
            action="bad-action",
            mode="one",
        )


def test_invalid_dns_action_rejected(builder):
    with pytest.raises(
        ValueError,
        match="DNSChaos action",
    ):
        builder.build_dns_chaos(
            name="invalid",
            action="bad-action",
            mode="one",
        )


def test_invalid_network_action_rejected(builder):
    with pytest.raises(
        ValueError,
        match="Unsupported NetworkChaos action",
    ):
        builder.build_network_chaos(
            name="invalid",
            action="bad-action",
            mode="one",
        )


def test_io_volume_path_required(builder):
    with pytest.raises(
        ValueError,
        match="volume_path is required",
    ):
        builder.build_io_chaos(
            name="invalid",
            action="latency",
            mode="one",
            volume_path="",
        )


def test_stress_requires_stressor(builder):
    with pytest.raises(
        ValueError,
        match="at least one stressor",
    ):
        builder.build_stress_chaos(
            name="invalid",
            mode="one",
            stressors={},
        )


def test_build_pod_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_pod_chaos(
        name="pod-test",
        namespace="default",
        action="pod-kill",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        duration="30s",
    )

    assert manifest["kind"] == "PodChaos"
    assert manifest["spec"]["action"] == "pod-kill"
    assert manifest["spec"]["mode"] == "one"


def test_build_network_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_network_chaos(
        name="network-test",
        namespace="default",
        action="delay",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        duration="30s",
        direction="to",
        target=None,
        delay={"latency": "100ms"},
    )

    assert manifest["kind"] == "NetworkChaos"
    assert manifest["spec"]["action"] == "delay"


def test_build_dns_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_dns_chaos(
        name="dns-test",
        namespace="default",
        action="error",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        duration="30s",
    )

    assert manifest["kind"] == "DNSChaos"
    assert manifest["spec"]["action"] == "error"


def test_build_http_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_http_chaos(
        name="http-test",
        namespace="default",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        duration="30s",
        port=80,
        path="/",
        method="GET",
    )

    assert manifest["kind"] == "HTTPChaos"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["selector"] == {
        "pods": {"default": ["pod-a"]}
    }
    assert manifest["spec"]["port"] == 80
    assert manifest["spec"]["path"] == "/"
    assert manifest["spec"]["method"] == "GET"
    assert manifest["spec"]["duration"] == "30s"


def test_build_io_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_io_chaos(
        name="io-test",
        namespace="default",
        action="latency",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        duration="30s",
        volume_path="/data",
        delay="100ms",
    )

    assert manifest["kind"] == "IOChaos"
    assert manifest["spec"]["action"] == "latency"


def test_build_stress_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_stress_chaos(
        name="stress-test",
        namespace="default",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        duration="30s",
        stressors={"cpu": {"workers": 1}},
    )

    assert manifest["kind"] == "StressChaos"


def test_build_time_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_time_chaos(
        name="time-test",
        namespace="default",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        duration="30s",
        clock="CLOCK_REALTIME",
        offset="1s",
    )

    assert manifest["kind"] == "TimeChaos"



def test_build_aws_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_aws_chaos(
        name="aws-test",
        namespace="default",
        action="ec2-stop",
        aws_region="eu-central-1",
        ec2_instance="i-123",
        mode="one",
        duration="30s",
    )

    assert manifest["kind"] == "AWSChaos"


def test_build_jvm_chaos():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_jvm_chaos(
        name="jvm-test",
        namespace="default",
        action="stress",
        mode="one",
        selector={"pods": {"default": ["pod-a"]}},
        cpu_count=1,
    )

    assert manifest["kind"] == "JVMChaos"


def test_build_schedule():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_schedule(
        name="schedule-test",
        namespace="default",
        schedule="*/10 * * * *",
        history_limit=5,
        concurrency_policy="Forbid",
        experiment_spec={
            "action": "pod-kill",
            "mode": "one",
            "selector": {},
            "duration": "30s",
        },
        experiment_type="PodChaos",
    )

    assert manifest["kind"] == "Schedule"
    assert manifest["spec"]["schedule"] == "*/10 * * * *"
    assert manifest["spec"]["historyLimit"] == 5


def test_build_status_check():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_status_check(
        name="status-test",
        namespace="default",
        url="http://example.com",
        status_code="200",
        mode="Synchronous",
        method="GET",
    )

    assert manifest["name"] == "status-test"
    assert manifest["templateType"] == "StatusCheck"
    assert manifest["statusCheck"]["type"] == "HTTP"


def test_build_generic():
    builder = ChaosMeshManifestBuilder()

    manifest = builder.build_generic(
        name="generic-test",
        kind="PodChaos",
        namespace="default",
        spec={
            "action": "pod-kill",
            "mode": "one",
        },
    )

    assert manifest["kind"] == "PodChaos"
    assert manifest["spec"]["action"] == "pod-kill"



def test_build_time_chaos_with_optional_fields(builder):
    manifest = builder.build_time_chaos(
        name="time-test",
        mode="one",
        clock="CLOCK_REALTIME",
        offset="1s",
        namespace="default",
        selector={
            "labelSelectors": {
                "app": "demo",
            }
        },
        container_names=["app"],
        pid=1234,
        duration="30s",
    )

    assert manifest["kind"] == "TimeChaos"
    assert manifest["spec"]["clock"] == "CLOCK_REALTIME"
    assert manifest["spec"]["offset"] == "1s"
    assert manifest["spec"]["containerNames"] == ["app"]
    assert manifest["spec"]["pid"] == 1234
    assert manifest["spec"]["duration"] == "30s"


def test_build_time_chaos_invalid_mode(builder):
    with pytest.raises(ValueError, match="Unsupported TimeChaos mode"):
        builder.build_time_chaos(
            name="invalid",
            mode="invalid",
            clock="CLOCK_REALTIME",
            offset="1s",
        )


def test_build_time_chaos_required_fields(builder):
    with pytest.raises(ValueError, match="clock is required"):
        builder.build_time_chaos(
            name="invalid",
            mode="one",
            clock="",
            offset="1s",
        )

    with pytest.raises(ValueError, match="offset is required"):
        builder.build_time_chaos(
            name="invalid",
            mode="one",
            clock="CLOCK_REALTIME",
            offset="",
        )


def test_build_kernel_chaos(builder):
    manifest = builder.build_kernel_chaos(
        name="kernel-test",
        mode="one",
        fail_kern={
            "failtype": "0",
            "probability": "1",
        },
        namespace="default",
        selector={
            "labelSelectors": {
                "app": "demo",
            }
        },
        duration="30s",
    )

    assert manifest["kind"] == "KernelChaos"
    assert manifest["spec"]["failKern"]["failtype"] == "0"
    assert manifest["spec"]["duration"] == "30s"


def test_build_kernel_chaos_validation(builder):
    with pytest.raises(ValueError, match="requires fail_kern"):
        builder.build_kernel_chaos(
            name="invalid",
            mode="one",
            fail_kern={},
        )

    with pytest.raises(ValueError, match="Unsupported KernelChaos mode"):
        builder.build_kernel_chaos(
            name="invalid",
            mode="invalid",
            fail_kern={"failtype": "0"},
        )


def test_build_aws_chaos_ec2_stop(builder):
    manifest = builder.build_aws_chaos(
        name="aws-stop",
        action="ec2-stop",
        aws_region="eu-central-1",
        ec2_instance="i-1234567890",
        namespace="default",
        secret_name="aws-secret",
        duration="30s",
        mode="one",
        value="test",
    )

    assert manifest["kind"] == "AWSChaos"
    assert manifest["spec"]["action"] == "ec2-stop"
    assert manifest["spec"]["awsRegion"] == "eu-central-1"
    assert manifest["spec"]["ec2Instance"] == "i-1234567890"
    assert manifest["spec"]["secretName"] == "aws-secret"
    assert manifest["spec"]["duration"] == "30s"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["value"] == "test"


def test_build_aws_chaos_detach_volume(builder):
    manifest = builder.build_aws_chaos(
        name="aws-volume",
        action="detach-volume",
        aws_region="eu-central-1",
        ec2_instance="i-1234567890",
        volume_id="vol-123456",
        device_name="/dev/sdf",
    )

    assert manifest["kind"] == "AWSChaos"
    assert manifest["spec"]["action"] == "detach-volume"
    assert manifest["spec"]["volumeID"] == "vol-123456"
    assert manifest["spec"]["deviceName"] == "/dev/sdf"


def test_build_aws_chaos_validation(builder):
    with pytest.raises(ValueError, match="Unsupported AWSChaos action"):
        builder.build_aws_chaos(
            name="invalid",
            action="invalid",
            aws_region="eu-central-1",
            ec2_instance="i-123",
        )

    with pytest.raises(ValueError, match="aws_region is required"):
        builder.build_aws_chaos(
            name="invalid",
            action="ec2-stop",
            aws_region="",
            ec2_instance="i-123",
        )

    with pytest.raises(ValueError, match="ec2_instance is required"):
        builder.build_aws_chaos(
            name="invalid",
            action="ec2-stop",
            aws_region="eu-central-1",
            ec2_instance="",
        )

    with pytest.raises(ValueError, match="requires volume_id"):
        builder.build_aws_chaos(
            name="invalid",
            action="detach-volume",
            aws_region="eu-central-1",
            ec2_instance="i-123",
        )

    with pytest.raises(ValueError, match="requires device_name"):
        builder.build_aws_chaos(
            name="invalid",
            action="detach-volume",
            aws_region="eu-central-1",
            ec2_instance="i-123",
            volume_id="vol-123",
        )


def test_build_jvm_chaos_latency(builder):
    manifest = builder.build_jvm_chaos(
        name="jvm-latency",
        action="latency",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "java",
            }
        },
        class_name="com.example.Service",
        method="process",
        latency=100,
        port=8080,
    )

    assert manifest["kind"] == "JVMChaos"
    assert manifest["spec"]["class"] == "com.example.Service"
    assert manifest["spec"]["method"] == "process"
    assert manifest["spec"]["latency"] == 100
    assert manifest["spec"]["port"] == 8080


def test_build_jvm_chaos_return_and_exception(builder):
    return_manifest = builder.build_jvm_chaos(
        name="jvm-return",
        action="return",
        mode="one",
        selector={"labelSelectors": {"app": "java"}},
        class_name="com.example.Service",
        method="process",
        value="0",
    )

    assert return_manifest["spec"]["value"] == "0"

    exception_manifest = builder.build_jvm_chaos(
        name="jvm-exception",
        action="exception",
        mode="one",
        selector={"labelSelectors": {"app": "java"}},
        class_name="com.example.Service",
        method="process",
        exception="java.lang.RuntimeException",
    )

    assert exception_manifest["spec"]["exception"] == (
        "java.lang.RuntimeException"
    )


def test_build_jvm_chaos_stress_and_rule_data(builder):
    stress_manifest = builder.build_jvm_chaos(
        name="jvm-stress",
        action="stress",
        mode="one",
        selector={"labelSelectors": {"app": "java"}},
        cpu_count=2,
        mem_type="heap",
    )

    assert stress_manifest["spec"]["cpuCount"] == 2
    assert stress_manifest["spec"]["memType"] == "heap"

    rule_manifest = builder.build_jvm_chaos(
        name="jvm-rule",
        action="ruleData",
        mode="one",
        selector={"labelSelectors": {"app": "java"}},
        rule_data="RULE DATA",
    )

    assert rule_manifest["spec"]["ruleData"] == "RULE DATA"


def test_build_jvm_chaos_validation(builder):
    selector = {"labelSelectors": {"app": "java"}}

    with pytest.raises(ValueError, match="Unsupported JVMChaos action"):
        builder.build_jvm_chaos(
            name="invalid",
            action="invalid",
            mode="one",
            selector=selector,
        )

    with pytest.raises(ValueError, match="Unsupported JVMChaos mode"):
        builder.build_jvm_chaos(
            name="invalid",
            action="stress",
            mode="invalid",
            selector=selector,
        )

    with pytest.raises(ValueError, match="selector is required"):
        builder.build_jvm_chaos(
            name="invalid",
            action="stress",
            mode="one",
            selector={},
        )

    with pytest.raises(ValueError, match="requires class_name"):
        builder.build_jvm_chaos(
            name="invalid",
            action="latency",
            mode="one",
            selector=selector,
        )

    with pytest.raises(ValueError, match="requires method"):
        builder.build_jvm_chaos(
            name="invalid",
            action="latency",
            mode="one",
            selector=selector,
            class_name="com.example.Service",
        )

    with pytest.raises(ValueError, match="requires latency"):
        builder.build_jvm_chaos(
            name="invalid",
            action="latency",
            mode="one",
            selector=selector,
            class_name="com.example.Service",
            method="process",
        )


def test_build_block_chaos(builder):
    manifest = builder.build_block_chaos(
        name="block-delay",
        action="delay",
        mode="one",
        volume_name="data-volume",
        namespace="default",
        selector={
            "labelSelectors": {
                "app": "demo",
            }
        },
        value="test",
        latency="100ms",
    )

    assert manifest["kind"] == "BlockChaos"
    assert manifest["spec"]["volumeName"] == "data-volume"
    assert manifest["spec"]["value"] == "test"
    assert manifest["spec"]["delay"]["latency"] == "100ms"


def test_build_block_chaos_freeze(builder):
    manifest = builder.build_block_chaos(
        name="block-freeze",
        action="freeze",
        mode="all",
        volume_name="data-volume",
        selector={"labelSelectors": {"app": "demo"}},
    )

    assert manifest["spec"]["action"] == "freeze"


def test_build_block_chaos_validation(builder):
    selector = {"labelSelectors": {"app": "demo"}}

    with pytest.raises(ValueError, match="Unsupported BlockChaos action"):
        builder.build_block_chaos(
            name="invalid",
            action="invalid",
            mode="one",
            volume_name="data",
            selector=selector,
        )

    with pytest.raises(ValueError, match="Unsupported BlockChaos mode"):
        builder.build_block_chaos(
            name="invalid",
            action="delay",
            mode="invalid",
            volume_name="data",
            selector=selector,
            latency="100ms",
        )

    with pytest.raises(ValueError, match="volume_name is required"):
        builder.build_block_chaos(
            name="invalid",
            action="delay",
            mode="one",
            volume_name="",
            selector=selector,
            latency="100ms",
        )

    with pytest.raises(ValueError, match="selector is required"):
        builder.build_block_chaos(
            name="invalid",
            action="delay",
            mode="one",
            volume_name="data",
            selector={},
            latency="100ms",
        )

    with pytest.raises(ValueError, match="requires latency"):
        builder.build_block_chaos(
            name="invalid",
            action="delay",
            mode="one",
            volume_name="data",
            selector=selector,
        )


def test_build_physical_machine_chaos(builder):
    manifest = builder.build_physical_machine_chaos(
        name="physical-test",
        action="stress-cpu",
        mode="one",
        selector={
            "physicalMachines": {
                "default": ["physical-machine-a"],
            }
        },
        namespace="default",
        action_config={
            "load": 50,
            "workers": 2,
        },
        duration="30s",
    )

    assert manifest["kind"] == "PhysicalMachineChaos"
    assert manifest["spec"]["action"] == "stress-cpu"
    assert manifest["spec"]["selector"]["physicalMachines"]
    assert manifest["spec"]["stress-cpu"]["load"] == 50
    assert manifest["spec"]["duration"] == "30s"


def test_build_physical_machine_chaos_validation(builder):
    selector = {
        "physicalMachines": {
            "default": ["physical-machine-a"],
        }
    }

    with pytest.raises(
        ValueError,
        match="Unsupported PhysicalMachineChaos action",
    ):
        builder.build_physical_machine_chaos(
            name="invalid",
            action="invalid",
            mode="one",
            selector=selector,
        )

    with pytest.raises(
        ValueError,
        match="Unsupported PhysicalMachineChaos mode",
    ):
        builder.build_physical_machine_chaos(
            name="invalid",
            action="stress-cpu",
            mode="invalid",
            selector=selector,
        )

    with pytest.raises(
        ValueError,
        match="selector is required",
    ):
        builder.build_physical_machine_chaos(
            name="invalid",
            action="stress-cpu",
            mode="one",
            selector={},
        )


def test_build_workflow(builder):
    manifest = builder.build_workflow(
        name="workflow-test",
        entry="task",
        templates=[
            {
                "name": "task",
                "templateType": "Task",
            }
        ],
        namespace="default",
    )

    assert manifest["kind"] == "Workflow"
    assert manifest["spec"]["entry"] == "task"
    assert manifest["spec"]["templates"][0]["name"] == "task"


def test_build_workflow_validation(builder):
    with pytest.raises(ValueError, match="entry is required"):
        builder.build_workflow(
            name="invalid",
            entry="",
            templates=[{"name": "task", "templateType": "Task"}],
        )

    with pytest.raises(ValueError, match="templates are required"):
        builder.build_workflow(
            name="invalid",
            entry="task",
            templates=[],
        )

    with pytest.raises(ValueError, match="does not match"):
        builder.build_workflow(
            name="invalid",
            entry="missing",
            templates=[{"name": "task", "templateType": "Task"}],
        )

    with pytest.raises(
        ValueError,
        match="does not match any template name",
    ):
        builder.build_workflow(
            name="invalid",
            entry="task",
            templates=["task"],
        )

    with pytest.raises(
        ValueError,
        match="requires templateType",
    ):
        builder.build_workflow(
            name="invalid",
            entry="task",
            templates=[{"name": "task"}],
        )


def test_build_schedule_with_optional_fields(builder):
    manifest = builder.build_schedule(
        name="schedule-test",
        schedule="*/10 * * * *",
        experiment_type="PodChaos",
        experiment_spec={
            "action": "pod-kill",
            "mode": "one",
            "selector": {},
            "duration": "30s",
        },
        namespace="default",
        history_limit="5",
        concurrency_policy="Forbid",
        starting_deadline_seconds=60,
    )

    assert manifest["kind"] == "Schedule"
    assert manifest["spec"]["historyLimit"] == 5
    assert manifest["spec"]["concurrencyPolicy"] == "Forbid"
    assert manifest["spec"]["startingDeadlineSeconds"] == 60
    assert manifest["spec"]["podChaos"]["action"] == "pod-kill"


def test_build_schedule_validation(builder):
    experiment_spec = {"action": "pod-kill"}

    with pytest.raises(ValueError, match="Schedule expression is required"):
        builder.build_schedule(
            name="invalid",
            schedule="",
            experiment_type="PodChaos",
            experiment_spec=experiment_spec,
        )

    with pytest.raises(
        ValueError,
        match="experiment_type is required",
    ):
        builder.build_schedule(
            name="invalid",
            schedule="*/10 * * * *",
            experiment_type="",
            experiment_spec=experiment_spec,
        )

    with pytest.raises(
        ValueError,
        match="experiment_spec is required",
    ):
        builder.build_schedule(
            name="invalid",
            schedule="*/10 * * * *",
            experiment_type="PodChaos",
            experiment_spec={},
        )

    with pytest.raises(
        ValueError,
        match="concurrency_policy",
    ):
        builder.build_schedule(
            name="invalid",
            schedule="*/10 * * * *",
            experiment_type="PodChaos",
            experiment_spec=experiment_spec,
            concurrency_policy="Invalid",
        )

    with pytest.raises(
        ValueError,
        match="history_limit must be an integer",
    ):
        builder.build_schedule(
            name="invalid",
            schedule="*/10 * * * *",
            experiment_type="PodChaos",
            experiment_spec=experiment_spec,
            history_limit="abc",
        )


def test_build_status_check_full_options(builder):
    manifest = builder.build_status_check(
        name="status-test",
        url="http://example.com",
        status_code="200",
        namespace="default",
        mode="Continuous",
        method="POST",
        headers={"Content-Type": ["application/json"]},
        body="{}",
        interval_seconds=1,
        timeout_seconds=5,
        failure_threshold=3,
        success_threshold=1,
        duration="30s",
        records_history_limit=10,
        abort_with_status_check=True,
        deadline="60s",
    )

    assert manifest["templateType"] == "StatusCheck"
    assert manifest["statusCheck"]["mode"] == "Continuous"
    assert manifest["statusCheck"]["http"]["method"] == "POST"
    assert manifest["statusCheck"]["http"]["headers"]
    assert manifest["statusCheck"]["http"]["body"] == "{}"
    assert manifest["statusCheck"]["intervalSeconds"] == 1
    assert manifest["statusCheck"]["timeoutSeconds"] == 5
    assert manifest["statusCheck"]["failureThreshold"] == 3
    assert manifest["statusCheck"]["successThreshold"] == 1
    assert manifest["statusCheck"]["duration"] == "30s"
    assert manifest["statusCheck"]["recordsHistoryLimit"] == 10
    assert manifest["abortWithStatusCheck"] is True
    assert manifest["deadline"] == "60s"


def test_build_status_check_validation(builder):
    with pytest.raises(ValueError, match="URL is required"):
        builder.build_status_check(
            name="invalid",
            url="",
            status_code="200",
        )

    with pytest.raises(ValueError, match="status_code is required"):
        builder.build_status_check(
            name="invalid",
            url="http://example.com",
            status_code="",
        )

    with pytest.raises(ValueError, match="mode must be"):
        builder.build_status_check(
            name="invalid",
            url="http://example.com",
            status_code="200",
            mode="Invalid",
        )

    with pytest.raises(ValueError, match="method must be"):
        builder.build_status_check(
            name="invalid",
            url="http://example.com",
            status_code="200",
            method="PUT",
        )


def test_build_http_optional_values_and_port_validation(builder):
    manifest = builder.build_http_chaos(
        name="http-full",
        mode="one",
        target="Response",
        port="8080",
        method="POST",
        path="/api",
        duration="30s",
        abort=False,
        delay="100ms",
        replace={"body": "test"},
        patch={"headers": {}},
        request_headers={"X-Test": "true"},
    )

    assert manifest["spec"]["target"] == "Response"
    assert manifest["spec"]["port"] == 8080
    assert manifest["spec"]["method"] == "POST"
    assert manifest["spec"]["replace"] == {"body": "test"}
    assert manifest["spec"]["patch"] == {"headers": {}}

    with pytest.raises(ValueError, match="port must be an integer"):
        builder.build_http_chaos(
            name="invalid",
            mode="one",
            port="abc",
        )

    with pytest.raises(ValueError, match="target must be"):
        builder.build_http_chaos(
            name="invalid",
            mode="one",
            target="Invalid",
        )


def test_build_base_manifest_validation(builder):
    with pytest.raises(ValueError, match="name is required"):
        builder.build(
            kind="PodChaos",
            name="",
        )

    with pytest.raises(ValueError, match="namespace is required"):
        builder.build(
            kind="PodChaos",
            name="test",
            namespace="",
        )