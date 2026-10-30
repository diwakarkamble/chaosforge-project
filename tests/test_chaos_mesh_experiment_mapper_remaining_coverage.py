import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)


def make_pod_kill_experiment(tmp_path, configuration):
    definition_path = tmp_path / "pod-kill.json"
    definition_path.write_text(
        json.dumps(
            {
                "chaos_mesh": {"kind": "PodChaos", "action": "pod-kill"},
                "configuration": {"mode": "one", **configuration},
            }
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(id="pod-kill", json_file=str(definition_path), variables={})


def test_mapper_resolves_deployment_labels_for_pod_selector(tmp_path):
    resolver = MagicMock()
    resolver.deployment_selector.return_value = {"app": "orders"}
    resolver.pod_selector.return_value = {
        "namespaces": ["apps"],
        "labelSelectors": {"app": "orders"},
    }
    experiment = make_pod_kill_experiment(
        tmp_path,
        {"eks_cluster": "cluster-a", "namespace": "apps", "deployment": "orders"},
    )

    manifest = ChaosMeshExperimentMapper(target_resolver=resolver).build_manifest(experiment)

    resolver.deployment_selector.assert_called_once_with("cluster-a", "apps", "orders")
    resolver.pod_selector.assert_called_once_with(
        namespace="apps", pod=None, labels={"app": "orders"}
    )
    assert manifest["spec"]["selector"] == resolver.pod_selector.return_value


def test_mapper_converts_integer_duration_to_seconds(tmp_path):
    experiment = make_pod_kill_experiment(tmp_path, {"duration": 30})

    manifest = ChaosMeshExperimentMapper().build_manifest(experiment)

    assert manifest["spec"]["duration"] == "30s"
