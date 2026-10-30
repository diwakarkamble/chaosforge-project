import json
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)


class RecordingBuilder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if not name.startswith("build_"):
            raise AttributeError(name)

        def build(**kwargs):
            self.calls.append((name, kwargs))
            if name == "build_status_check":
                return {"name": kwargs["name"], "templateType": "StatusCheck", **kwargs}
            spec = dict(kwargs)
            if name == "build_time_chaos":
                spec["offset"] = kwargs["offset"]
                spec["clock"] = kwargs["clock"]
            if name == "build_kernel_chaos":
                spec["failKern"] = kwargs["fail_kern"]
            return {
                "apiVersion": "chaos-mesh.org/v1alpha1",
                "kind": name.removeprefix("build_"),
                "metadata": {"name": kwargs["name"], "namespace": kwargs["namespace"]},
                "spec": spec,
            }

        return build


def build_from_definition(tmp_path, kind, action="fault", configuration=None, **mapper_kwargs):
    definition = {
        "chaos_mesh": {"kind": kind},
        "configuration": configuration or {},
    }
    if action is not None:
        definition["chaos_mesh"]["action"] = action
    path = tmp_path / f"{kind}.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    experiment = SimpleNamespace(id="My Test_ID", json_file=str(path), variables={})
    builder = RecordingBuilder()
    mapper = ChaosMeshExperimentMapper(builder=builder, **mapper_kwargs)
    return mapper.build_manifest(experiment), builder


def test_stress_http_and_io_configuration_is_normalized(tmp_path):
    manifest, builder = build_from_definition(
        tmp_path,
        "StressChaos",
        configuration={
            "stressors": {"cpu": 2, "memory": 64, "io": {"workers": 1}},
            "duration": "20s",
        },
    )
    kwargs = builder.calls[-1][1]
    assert kwargs["stressors"] == {
        "cpu": {"workers": 2, "load": 100},
        "memory": {"workers": 1, "size": "64MB"},
        "io": {"workers": 1},
    }
    assert manifest["metadata"]["name"] == "chaosforge-my-test-id-fault"

    _, builder = build_from_definition(
        tmp_path,
        "HTTPChaos",
        action="patch",
        configuration={
            "patch": {
                "headers": {"X-Test": "yes"},
                "queries": {"page": "2"},
            },
            "request_headers": {"X-Source": "test"},
        },
    )
    kwargs = builder.calls[-1][1]
    assert kwargs["patch"] == {
        "headers": [["X-Test", "yes"]],
        "queries": [["page", "2"]],
    }
    assert kwargs["request_headers"] == {"X-Source": "test"}

    _, builder = build_from_definition(
        tmp_path,
        "IOChaos",
        action="attrOverride",
        configuration={
            "volume_path": "/data",
            "latency": "25ms",
            "attr_override": {"perm": "755"},
            "methods": ["READ"],
        },
    )
    kwargs = builder.calls[-1][1]
    assert kwargs["delay"] == "25ms"
    assert kwargs["attr"] == {"perm": 0o755}
    assert kwargs["methods"] == ["READ"]


def test_specialized_manifest_shapes_are_normalized(tmp_path):
    manifest, _ = build_from_definition(
        tmp_path,
        "TimeChaos",
        action="time",
        configuration={"clock": ["CLOCK_REALTIME"], "offset": "2h"},
    )
    assert manifest["spec"]["timeOffset"] == "2h"
    assert manifest["spec"]["clockIds"] == ["CLOCK_REALTIME"]
    assert "clock" not in manifest["spec"]

    manifest, _ = build_from_definition(
        tmp_path,
        "KernelChaos",
        configuration={"fail_kern": {"callchain": ["open"]}},
    )
    assert manifest["spec"]["failKernRequest"] == {"callchain": ["open"]}

    _, builder = build_from_definition(
        tmp_path,
        "AWSChaos",
        action="ec2-stop",
        configuration={
            "aws_region": "eu-west-1",
            "ec2_instance": "i-123",
            "secret_name": "aws-creds",
        },
    )
    assert builder.calls[-1][1]["aws_region"] == "eu-west-1"
    assert builder.calls[-1][1]["ec2_instance"] == "i-123"

    _, builder = build_from_definition(
        tmp_path,
        "JVMChaos",
        action="latency",
        configuration={"class": "Orders", "method": "submit", "latency": 500},
    )
    assert builder.calls[-1][1]["class_name"] == "Orders"
    assert builder.calls[-1][1]["latency"] == 500

    _, builder = build_from_definition(
        tmp_path,
        "BlockChaos",
        action="loss",
        configuration={"volume_name": "data", "value": "25", "duration": "ignored"},
    )
    assert builder.calls[-1][1]["volume_name"] == "data"
    assert "duration" not in builder.calls[-1][1]


def test_catalog_aliases_and_execution_controls_do_not_reach_builders(tmp_path):
    _, builder = build_from_definition(
        tmp_path,
        "TimeChaos",
        action="time",
        configuration={
            "clock": "CLOCK_REALTIME",
            "time_offset": "5m",
            "container_name": "api",
            "dry_run": True,
            "wait_for_completion": False,
            "cleanup_after_execution": True,
            "timeout_seconds": 10,
            "poll_interval_seconds": 1,
            "original_replicas": 2,
        },
    )
    kwargs = builder.calls[-1][1]
    assert kwargs["offset"] == "5m"
    assert kwargs["container_names"] == ["api"]
    assert not {"dry_run", "wait_for_completion", "cleanup_after_execution", "timeout_seconds", "poll_interval_seconds", "original_replicas"} & kwargs.keys()

    _, builder = build_from_definition(
        tmp_path,
        "HTTPChaos",
        action="delay",
        configuration={"http_port": 8080, "http_delay": "2s"},
    )
    assert builder.calls[-1][1]["port"] == 8080
    assert builder.calls[-1][1]["delay"] == "2s"

    _, builder = build_from_definition(
        tmp_path,
        "IOChaos",
        action="fault",
        configuration={"volume_path": "/data", "io_percent": 60, "io_errno": 5},
    )
    kwargs = builder.calls[-1][1]
    assert (kwargs["percent"], kwargs["errno"]) == (60, 5)

    _, builder = build_from_definition(
        tmp_path,
        "BlockChaos",
        action="fault",
        configuration={"volume_name": "data", "chaos_value": "2"},
    )
    assert builder.calls[-1][1]["value"] == "2"


def test_physical_workflow_schedule_and_status_check_are_normalized(tmp_path):
    _, builder = build_from_definition(
        tmp_path,
        "PhysicalMachineChaos",
        action="stress-cpu",
        configuration={
            "namespace": "machines",
            "physical_machine": "worker-1",
            "cpu_load": "70",
            "cpu_workers": "3",
            "duration": "1m",
        },
    )
    kwargs = builder.calls[-1][1]
    assert kwargs["selector"] == {"physicalMachines": {"machines": ["worker-1"]}}
    assert kwargs["action_config"] == {"load": 70, "workers": 3}

    _, builder = build_from_definition(
        tmp_path,
        "Workflow",
        action=None,
        configuration={
            "entry": "task",
            "templates": [{
                "name": "task",
                "task": {"container": "busybox", "command": ["true"]},
            }],
        },
    )
    task = builder.calls[-1][1]["templates"][0]["task"]
    assert task == {"container": {"name": "busybox", "command": ["true"]}}

    _, builder = build_from_definition(
        tmp_path,
        "Schedule",
        action=None,
        configuration={
            "schedule": "*/5 * * * *",
            "type": "PodChaos",
            "chaos": {"action": "pod-kill"},
            "history_limit": 4,
            "concurrency_policy": "Forbid",
            "starting_deadline_seconds": 30,
        },
    )
    kwargs = builder.calls[-1][1]
    assert kwargs["experiment_type"] == "PodChaos"
    assert kwargs["history_limit"] == 4

    manifest, builder = build_from_definition(
        tmp_path,
        "StatusCheck",
        action=None,
        configuration={
            "templates": [{
                "name": "health",
                "status_check": {
                    "url": "https://service/health",
                    "status_code": 204,
                    "method": "HEAD",
                },
            }],
        },
    )
    status_call, workflow_call = builder.calls
    assert status_call[1]["status_code"] == "204"
    assert status_call[1]["method"] == "HEAD"
    assert workflow_call[1]["entry"] == "health"
    assert manifest["spec"]["templates"][0]["name"] == "health"


@pytest.mark.parametrize(
    ("action", "configuration", "expected_action", "expected_key", "expected_value"),
    [
        ("delay", {"delay": "100ms"}, "delay", "delay", {"latency": "100ms"}),
        ("loss", {"loss": "25"}, "loss", "loss", {"loss": "25"}),
        ("duplicate", {"duplicate": "5"}, "duplicate", "duplicate", {"duplicate": "5"}),
        ("corrupt", {"corrupt": "2"}, "corrupt", "corrupt", {"corrupt": "2"}),
        (
            "reorder",
            {"reorder": "30", "latency": "50ms"},
            "netem",
            "delay",
            {"latency": "50ms", "reorder": {"reorder": "30", "gap": 1}},
        ),
        (
            "bandwidth",
            {"rate": "1mbps"},
            "bandwidth",
            "rate",
            {"rate": "1mbps", "buffer": 10000, "limit": 10000},
        ),
    ],
)
def test_network_values_are_normalized(
    tmp_path, action, configuration, expected_action, expected_key, expected_value
):
    _, builder = build_from_definition(
        tmp_path, "NetworkChaos", action=action, configuration=configuration
    )
    kwargs = builder.calls[-1][1]
    assert kwargs["action"] == expected_action
    assert kwargs[expected_key] == expected_value


def test_target_resolution_and_node_selector(tmp_path):
    resolver = MagicMock()
    resolver.pod_selector.return_value = {"namespaces": ["apps"]}
    resolver.node_selector.return_value = {"nodeSelectors": {"role": "worker"}}

    _, builder = build_from_definition(
        tmp_path,
        "PodChaos",
        action="pod-kill",
        configuration={
            "cluster": "cluster-a",
            "namespace": "apps",
            "node": "node-1",
            "mode": "one",
        },
        target_resolver=resolver,
    )
    resolver.resolve_node.assert_called_once_with("cluster-a", "node-1")
    assert builder.calls[-1][1]["selector"]["nodes"] == ["node-1"]

    mapper = ChaosMeshExperimentMapper(target_resolver=resolver)
    mapper._validate_target("c", "ns", "pod", None, None)
    mapper._validate_target("c", "ns", None, "deploy", None)
    mapper._validate_target("c", "ns", None, None, None)
    resolver.resolve_pod.assert_called_once_with("c", "ns", "pod")
    resolver.resolve_deployment.assert_called_once_with("c", "ns", "deploy")
    resolver.resolve_namespace.assert_called_once_with("c", "ns")


def test_mapper_validation_errors_are_descriptive(tmp_path):
    mapper = ChaosMeshExperimentMapper()
    with pytest.raises(ValueError, match="manifest.*json_file"):
        mapper.build_manifest(SimpleNamespace(variables={}, json_file=""))

    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match=re.escape(str(missing))):
        mapper._load_definition(str(missing))

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        mapper._load_definition(str(array))

    for definition, message in [
        ({"chaos_mesh": []}, "chaos_mesh.*object"),
        ({"chaos_mesh": {}}, "kind"),
        ({"chaos_mesh": {"kind": "PodChaos"}}, "action"),
        (
            {"chaos_mesh": {"kind": "Workflow"}, "configuration": []},
            "configuration.*object",
        ),
    ]:
        path = tmp_path / (message.split(".*")[0] + ".json")
        path.write_text(json.dumps(definition), encoding="utf-8")
        with pytest.raises((TypeError, ValueError), match=message):
            mapper.build_manifest(SimpleNamespace(variables={}, json_file=str(path)))

    with pytest.raises(ValueError, match="missing required fields"):
        mapper._validate_manifest({"kind": "PodChaos"})
    with pytest.raises(ValueError, match="Unsupported Chaos Mesh kind"):
        mapper._kind_to_method("AlienChaos")


@pytest.mark.parametrize(
    ("configuration", "message"),
    [({"templates": []}, "at least one template"), ({"templates": [{}]}, "status_check.url")],
)
def test_status_check_requires_a_template_url(tmp_path, configuration, message):
    with pytest.raises(ValueError, match=message):
        build_from_definition(
            tmp_path,
            "StatusCheck",
            action=None,
            configuration=configuration,
        )
