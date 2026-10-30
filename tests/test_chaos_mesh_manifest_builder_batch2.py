import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_manifest_builder import (
    ChaosMeshManifestBuilder,
)


@pytest.fixture
def builder():
    return ChaosMeshManifestBuilder()


def test_build_jvm_latency(builder):
    manifest = builder.build_jvm_chaos(
        name="jvm-latency",
        action="latency",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "java-app",
            }
        },
        class_name="Main",
        method="getValue",
        latency=500,
        port=9277,
    )

    assert manifest["kind"] == "JVMChaos"
    assert manifest["spec"]["action"] == "latency"
    assert manifest["spec"]["class"] == "Main"
    assert manifest["spec"]["method"] == "getValue"
    assert manifest["spec"]["latency"] == 500
    assert manifest["spec"]["port"] == 9277


def test_build_jvm_return(builder):
    manifest = builder.build_jvm_chaos(
        name="jvm-return",
        action="return",
        mode="all",
        selector={
            "labelSelectors": {
                "app": "java-app",
            }
        },
        class_name="Main",
        method="getValue",
        value="9999",
    )

    assert manifest["spec"]["action"] == "return"
    assert manifest["spec"]["value"] == "9999"


def test_build_jvm_exception(builder):
    manifest = builder.build_jvm_chaos(
        name="jvm-exception",
        action="exception",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "java-app",
            }
        },
        class_name="Main",
        method="getValue",
        exception='java.io.IOException("BOOM")',
    )

    assert manifest["spec"]["exception"] == (
        'java.io.IOException("BOOM")'
    )


def test_build_jvm_stress(builder):
    manifest = builder.build_jvm_chaos(
        name="jvm-stress",
        action="stress",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "java-app",
            }
        },
        cpu_count=2,
    )

    assert manifest["spec"]["cpuCount"] == 2


def test_build_jvm_gc(builder):
    manifest = builder.build_jvm_chaos(
        name="jvm-gc",
        action="gc",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "java-app",
            }
        },
    )

    assert manifest["spec"]["action"] == "gc"


def test_build_jvm_rule_data(builder):
    manifest = builder.build_jvm_chaos(
        name="jvm-rule",
        action="ruleData",
        mode="one",
        selector={
            "labelSelectors": {
                "app": "java-app",
            }
        },
        rule_data="RULE example",
    )

    assert manifest["spec"]["ruleData"] == "RULE example"


def test_jvm_requires_class_and_method(builder):
    with pytest.raises(ValueError):
        builder.build_jvm_chaos(
            name="invalid",
            action="return",
            mode="one",
            selector={"labelSelectors": {"app": "java"}},
            value="123",
        )


def test_build_block_delay(builder):
    manifest = builder.build_block_chaos(
        name="block-delay",
        action="delay",
        mode="one",
        volume_name="data-volume",
        selector={
            "labelSelectors": {
                "app": "storage-app",
            }
        },
        latency="500ms",
    )

    assert manifest["kind"] == "BlockChaos"
    assert manifest["spec"]["action"] == "delay"
    assert manifest["spec"]["volumeName"] == "data-volume"
    assert manifest["spec"]["delay"]["latency"] == "500ms"


def test_build_block_freeze(builder):
    manifest = builder.build_block_chaos(
        name="block-freeze",
        action="freeze",
        mode="all",
        volume_name="data-volume",
        selector={
            "labelSelectors": {
                "app": "storage-app",
            }
        },
    )

    assert manifest["spec"]["action"] == "freeze"


def test_block_delay_requires_latency(builder):
    with pytest.raises(
        ValueError,
        match="requires latency",
    ):
        builder.build_block_chaos(
            name="invalid",
            action="delay",
            mode="one",
            volume_name="data-volume",
            selector={"labelSelectors": {"app": "storage"}},
        )


def test_build_physical_machine_chaos(builder):
    manifest = builder.build_physical_machine_chaos(
        name="physical-network-delay",
        action="network-delay",
        mode="one",
        selector={
            "labelSelectors": {
                "arch": "amd64",
            }
        },
        action_config={
            "device": "ens33",
            "ip-address": "10.0.0.10",
            "latency": "1000ms",
        },
        duration="10m",
    )

    assert manifest["kind"] == "PhysicalMachineChaos"
    assert manifest["spec"]["action"] == "network-delay"
    assert manifest["spec"]["network-delay"]["device"] == "ens33"
    assert manifest["spec"]["network-delay"]["latency"] == "1000ms"
    assert manifest["spec"]["duration"] == "10m"


def test_physical_machine_rejects_unknown_action(builder):
    with pytest.raises(
        ValueError,
        match="Unsupported PhysicalMachineChaos action",
    ):
        builder.build_physical_machine_chaos(
            name="invalid",
            action="unknown",
            mode="one",
            selector={"labelSelectors": {"arch": "amd64"}},
        )


def test_build_workflow(builder):
    manifest = builder.build_workflow(
        name="demo-workflow",
        entry="entry",
        templates=[
            {
                "name": "entry",
                "templateType": "Serial",
                "children": ["pod-kill"],
            },
            {
                "name": "pod-kill",
                "templateType": "PodChaos",
                "deadline": "30s",
                "podChaos": {
                    "action": "pod-kill",
                    "mode": "one",
                    "selector": {
                        "labelSelectors": {
                            "app": "demo",
                        }
                    },
                },
            },
        ],
    )

    assert manifest["kind"] == "Workflow"
    assert manifest["spec"]["entry"] == "entry"
    assert len(manifest["spec"]["templates"]) == 2


def test_workflow_requires_valid_entry(builder):
    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        builder.build_workflow(
            name="invalid-workflow",
            entry="missing",
            templates=[
                {
                    "name": "entry",
                    "templateType": "Serial",
                }
            ],
        )


def test_build_schedule(builder):
    manifest = builder.build_schedule(
        name="scheduled-network-delay",
        schedule="*/5 * * * *",
        experiment_type="NetworkChaos",
        experiment_spec={
            "action": "delay",
            "mode": "one",
            "selector": {
                "labelSelectors": {
                    "app": "demo",
                }
            },
            "delay": {
                "latency": "100ms",
            },
            "duration": "30s",
        },
        history_limit=2,
        concurrency_policy="Forbid",
    )

    assert manifest["kind"] == "Schedule"
    assert manifest["spec"]["schedule"] == "*/5 * * * *"
    assert manifest["spec"]["type"] == "NetworkChaos"
    assert manifest["spec"]["networkChaos"]["action"] == "delay"
    assert manifest["spec"]["historyLimit"] == 2
    assert manifest["spec"]["concurrencyPolicy"] == "Forbid"


def test_schedule_rejects_invalid_policy(builder):
    with pytest.raises(
        ValueError,
        match="concurrency_policy",
    ):
        builder.build_schedule(
            name="invalid",
            schedule="@hourly",
            experiment_type="PodChaos",
            experiment_spec={
                "action": "pod-kill",
                "mode": "one",
                "selector": {},
            },
            concurrency_policy="Invalid",
        )


def test_build_status_check(builder):
    template = builder.build_status_check(
        name="health-check",
        url="http://demo.default.svc/health",
        status_code="200",
        mode="Continuous",
        method="GET",
        interval_seconds=1,
        timeout_seconds=2,
        failure_threshold=3,
        success_threshold=1,
        abort_with_status_check=True,
        deadline="60s",
    )

    assert template["name"] == "health-check"
    assert template["templateType"] == "StatusCheck"
    assert template["statusCheck"]["type"] == "HTTP"
    assert template["statusCheck"]["http"]["url"] == (
        "http://demo.default.svc/health"
    )
    assert template["statusCheck"]["http"]["criteria"]["statusCode"] == "200"
    assert template["statusCheck"]["failureThreshold"] == 3
    assert template["abortWithStatusCheck"] is True
    assert template["deadline"] == "60s"


def test_status_check_rejects_invalid_mode(builder):
    with pytest.raises(
        ValueError,
        match="Synchronous",
    ):
        builder.build_status_check(
            name="invalid",
            url="http://demo/health",
            status_code="200",
            mode="Invalid",
        )
