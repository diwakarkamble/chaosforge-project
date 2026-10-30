from pathlib import Path
from types import SimpleNamespace

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)

ROOT = Path(__file__).resolve().parents[1]


def make_experiment(experiment_id, filename, variables=None):
    return SimpleNamespace(
        id=experiment_id,
        name=experiment_id,
        service="chaos_mesh",
        json_file=str(
            ROOT
            / "chaosforge"
            / "engines"
            / "chaos_mesh"
            / "experiments"
            / "definitions"
            / filename
        ),
        variables=variables or {},
    )


def test_pod_failure_definition_maps_to_podchaos():
    mapper = ChaosMeshExperimentMapper()

    manifest = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-pod-failure",
            "pod-failure.json",
        )
    )

    assert manifest["apiVersion"] == "chaos-mesh.org/v1alpha1"
    assert manifest["kind"] == "PodChaos"
    assert manifest["metadata"]["namespace"] == "default"
    assert manifest["spec"]["action"] == "pod-failure"
    assert manifest["spec"]["mode"] == "one"
    assert manifest["spec"]["duration"] == "30s"


def test_mapper_converts_iso8601_duration_to_kubernetes_seconds():
    manifest = ChaosMeshExperimentMapper().build_manifest(
        make_experiment(
            "chaos-mesh-pod-failure",
            "pod-failure.json",
            {
                "namespace": "default",
                "pod": "pod-a",
                "target_mode": "pod",
                "mode": "one",
                "duration": "PT2M",
            },
        )
    )

    assert manifest["spec"]["duration"] == "120s"
    assert manifest["metadata"]["namespace"] == "default"

    assert manifest["spec"]["action"] == "pod-failure"
    assert manifest["spec"]["mode"] == "one"


def test_pod_kill_definition_maps_to_podchaos():
    mapper = ChaosMeshExperimentMapper()

    manifest = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-pod-kill",
            "pod-kill.json",
        )
    )

    assert manifest["kind"] == "PodChaos"
    assert manifest["spec"]["action"] == "pod-kill"
    assert manifest["spec"]["mode"] == "one"


def test_container_kill_definition_maps_to_podchaos():
    mapper = ChaosMeshExperimentMapper()

    manifest = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-container-kill",
            "container-kill.json",
        )
    )

    assert manifest["kind"] == "PodChaos"
    assert manifest["spec"]["action"] == "container-kill"
    assert manifest["spec"]["mode"] == "one"


def test_runtime_variables_override_definition():
    mapper = ChaosMeshExperimentMapper()

    manifest = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-pod-failure",
            "pod-failure.json",
            {
                "namespace": "chaos-testing",
                "mode": "all",
                "duration": "60s",
                "region": "eu-central-1",
            },
        )
    )

    assert manifest["metadata"]["namespace"] == "chaos-testing"
    assert manifest["spec"]["mode"] == "all"
    assert manifest["spec"]["duration"] == "60s"


def test_runtime_selector_is_passed_to_podchaos():
    mapper = ChaosMeshExperimentMapper()

    manifest = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-pod-kill",
            "pod-kill.json",
            {
                "namespace": "production",
                "selector": {
                    "labelSelectors": {
                        "app": "orders",
                    }
                },
            },
        )
    )

    assert manifest["metadata"]["namespace"] == "production"
    assert manifest["spec"]["selector"] == {
        "labelSelectors": {
            "app": "orders",
        }
    }


def test_network_delay_accepts_aks_equivalent_jitter_and_correlation():
    manifest = ChaosMeshExperimentMapper().build_manifest(
        make_experiment(
            "chaos-mesh-network-delay",
            "network-delay.json",
            {"delay": "500ms", "jitter": "100ms", "correlation": 50},
        )
    )

    assert manifest["spec"]["delay"] == {
        "latency": "500ms", "jitter": "100ms", "correlation": "50"
    }


def test_dns_and_io_accept_aks_equivalent_parameter_names():
    mapper = ChaosMeshExperimentMapper()
    dns = mapper.build_manifest(
        make_experiment("chaos-mesh-dns-error", "dns-error.json", {"dns_pattern": "api.example.com"})
    )
    io = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-io-fault", "io-fault.json", {"io_errno": 5, "io_percent": 50}
        )
    )

    assert dns["spec"]["patterns"] == ["api.example.com"]
    assert io["spec"]["errno"] == 5
    assert io["spec"]["percent"] == 50


def test_podchaos_ignores_shared_aks_validation_context():
    mapper = ChaosMeshExperimentMapper()

    manifest = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-pod-kill",
            "pod-kill.json",
            {
                "namespace": "sample-app",
                "pod": "api-1",
                "target_mode": "pod",
                "owning_deployment": "api",
                "label_key": "app",
                "label_val": "api",
                "original_replicas": 3,
            },
        )
    )

    assert manifest["spec"]["action"] == "pod-kill"
    assert "owning_deployment" not in manifest["spec"]
    assert "original_replicas" not in manifest["spec"]


def test_podchaos_ignores_execution_only_controls():
    manifest = ChaosMeshExperimentMapper().build_manifest(
        make_experiment(
            "chaos-mesh-pod-failure",
            "pod-failure.json",
            {"dry_run": "false", "wait_for_completion": True, "timeout_seconds": 60},
        )
    )

    assert "dry_run" not in manifest["spec"]
    assert "wait_for_completion" not in manifest["spec"]
    assert "timeout_seconds" not in manifest["spec"]


def test_replica_reduction_context_never_reaches_any_chaos_mesh_builder():
    manifest = ChaosMeshExperimentMapper().build_manifest(
        make_experiment(
            "chaos-mesh-network-delay",
            "network-delay.json",
            {"original_replicas": 3},
        )
    )

    assert "original_replicas" not in manifest["spec"]

def test_awschaos_preserves_aws_region():
    mapper = ChaosMeshExperimentMapper()

    manifest = mapper.build_manifest(
        make_experiment(
            "chaos-mesh-aws",
            "aws-chaos.json",
            {
                "aws_region": "eu-central-1",
                "ec2_instance": "i-0123456789abcdef0",
            },
        )
    )

    assert manifest["kind"] == "AWSChaos"
    assert manifest["metadata"]["namespace"] == "default"
    assert manifest["spec"]["action"] == "ec2-stop"
    assert manifest["spec"]["awsRegion"] == "eu-central-1"
    assert manifest["spec"]["ec2Instance"] == "i-0123456789abcdef0"


def test_io_latency_uses_runtime_eks_pod():
    mapper = ChaosMeshExperimentMapper()

    experiment = make_experiment(
        "chaos-mesh-io-latency",
        "io-latency.json",
        {
            "aws_region": "eu-central-1",
            "eks_cluster": "Chaos-POC-v2",
            "namespace": "default",
            "pod": "chaosforge-io-test-897dbd5d5-cpx8t",
        },
    )

    manifest = mapper.build_manifest(experiment)

    assert manifest["kind"] == "IOChaos"
    assert manifest["metadata"]["namespace"] == "default"

    selector = manifest["spec"]["selector"]

    assert selector["namespaces"] == ["default"]
    assert selector["pods"]["default"] == [
        "chaosforge-io-test-897dbd5d5-cpx8t"
    ]
