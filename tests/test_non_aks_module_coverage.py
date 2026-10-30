import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.application.services.planning import PlanService
from chaosforge.application.validation.legacy_experiment_validator import (
    ExperimentValidator as LegacyExperimentValidator,
)
from chaosforge.catalog.loader import ExperimentCatalog
from chaosforge.common.paths import ChaosForgePaths
from chaosforge.engines.chaos_mesh.chaos_mesh_installer import ChaosMeshInstaller
from chaosforge.engines.chaos_mesh.chaos_mesh_preflight import ChaosMeshPreflight
from chaosforge.engines.chaos_mesh.chaos_mesh_target_resolver import (
    ChaosMeshTargetResolver,
)
from chaosforge.engines.chaos_toolkit.runner import (
    ExperimentRunner,
    _deviation_reason,
)


def test_legacy_validator_reports_required_range_type_and_unknown_variable_errors():
    result = LegacyExperimentValidator().validate(
        {
            "inputs": [
                {"name": "required", "required": True, "type": "string"},
                {"name": "count", "type": "integer", "min": 2, "max": 4},
                {"name": "ratio", "type": "float", "min": 0.5, "max": 1.5},
                {"name": "enabled", "type": "boolean"},
            ]
        },
        {"required": " ", "count": True, "ratio": "2.0", "enabled": "yes", "extra": 1},
    )

    assert result["valid"] is False
    assert "Required variable 'required' is missing." in result["errors"]
    assert any("count" in error and "integer" in error for error in result["errors"])
    assert any("ratio" in error and "less than or equal to 1.5" in error for error in result["errors"])
    assert any("enabled" in error and "boolean" in error for error in result["errors"])
    assert result["warnings"] == ["Variable 'extra' is not defined in experiment metadata."]


def test_paths_create_only_runtime_artifact_directories(tmp_path):
    paths = ChaosForgePaths(tmp_path)

    assert paths.runtime == tmp_path / "runtime"
    paths.ensure_runtime_directories()

    assert all(directory.is_dir() for directory in (
        paths.campaigns, paths.executions, paths.evidence, paths.reports, paths.logs, paths.rollback,
    ))


def test_catalog_uses_migrated_metadata_and_definition_paths(tmp_path):
    metadata_path = tmp_path / "chaosforge/providers/aws/components/lambda/experiments/metadata.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps({"experiments": [{"id": "memory"}]}), encoding="utf-8")
    catalog = ExperimentCatalog(ChaosForgePaths(tmp_path))

    assert catalog.metadata_path("lambda") == metadata_path
    assert catalog.list_services() == ["lambda"]
    assert catalog.load_service("lambda") == {"experiments": [{"id": "memory"}]}
    assert catalog.get_experiment("lambda", "memory") == {"id": "memory"}
    assert catalog.definition_path("lambda", "memory.json") == (
        metadata_path.parent / "toolkit/definitions/memory.json"
    )
    assert catalog.definition_path("unknown", "missing.json").name == "missing-definition.json"


def test_planner_blocks_missing_metadata_and_uses_json_recovery_fallback(tmp_path):
    experiment = SimpleNamespace(
        id="memory", service="lambda", name="Memory", engine="Chaos Toolkit", variables={"aws_region": "eu"},
    )
    service = PlanService(discovery_factory=MagicMock())

    with patch("chaosforge.application.services.planning.load_metadata", return_value=None):
        result = service.plan_experiment(experiment)

    assert result.executable is False
    assert result.experiments[0]["status"] == "BLOCKED"

    definition_file = tmp_path / "definition.json"
    definition_file.write_text(json.dumps({"rollbacks": [{"name": "restore memory"}]}), encoding="utf-8")
    recovery_result = SimpleNamespace(recovery={"behavior": "UNKNOWN", "details": []})
    with patch("chaosforge.application.services.planning.open", create=True) as open_file:
        open_file.return_value.__enter__.return_value.read.return_value = definition_file.read_text()
        PlanService._add_recovery({"json": "definition.json"}, experiment, recovery_result)

    assert recovery_result.recovery["behavior"] == "Experiment rollback actions"
    assert recovery_result.recovery["details"] == [{"experiment_id": "memory", "rollback_actions": ["restore memory"]}]


def test_planner_chaos_mesh_preflight_blocks_missing_cluster_before_calling_factory():
    experiment = SimpleNamespace(id="mesh", variables={}, engine="Chaos Mesh")
    result = SimpleNamespace(blockers=[], warnings=[])
    plan = {"status": "PLANNED"}
    factory = MagicMock()

    PlanService(chaos_mesh_preflight_factory=factory)._run_chaos_mesh_preflight(
        experiment, {"chaos_mesh": {"kind": "PodChaos"}}, MagicMock(), result, plan
    )

    assert plan["status"] == "BLOCKED"
    assert "requires an EKS cluster" in result.blockers[0]
    factory.assert_not_called()


def test_installer_classifies_release_absence_and_repository_add_failure():
    installer = ChaosMeshInstaller()
    absent = SimpleNamespace(returncode=1, stdout="", stderr="release: not found")
    with patch("chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run", return_value=absent):
        assert installer.release_status()[0].value == "ABSENT"

    repo_list = SimpleNamespace(returncode=0, stdout="other-repo", stderr="")
    repo_add = SimpleNamespace(returncode=1, stdout="", stderr="denied")
    with patch("chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run", side_effect=[repo_list, repo_add]):
        with pytest.raises(RuntimeError, match="denied"):
            installer._ensure_repository()


def test_preflight_warns_when_apps_api_is_unavailable_without_blocking_ready_checks():
    discovery = MagicMock()
    discovery.k8s_core_api = MagicMock()
    discovery.k8s_apps_api = None
    custom_api = MagicMock()
    with patch.object(ChaosMeshPreflight, "_custom_objects_api", return_value=custom_api):
        result = ChaosMeshPreflight(discovery).check("cluster", "Schedule", namespace="default")

    assert result.status == "READY"
    assert len(result.warnings) == 1
    assert {check["name"] for check in result.checks} >= {"Kubernetes API", "Schedule CRD", "Target Namespace", "Chaos Controller Manager"}


def test_target_resolver_validates_missing_values_and_selector_copies_labels():
    resolver = ChaosMeshTargetResolver(MagicMock())
    with pytest.raises(ValueError, match="EKS cluster"):
        resolver.resolve_namespace("", "default")
    with pytest.raises(ValueError, match="deployment"):
        resolver.resolve_deployment("cluster", "default", "")
    labels = {"app": "orders"}
    selector = resolver.pod_selector(namespace="default", pod="orders-1", labels=labels)
    labels["app"] = "changed"

    assert selector == {"namespaces": ["default"], "pods": {"default": ["orders-1"]}, "labelSelectors": {"app": "orders"}}


def test_runner_journal_deviations_are_interpreted_consistently():
    assert "before the fault" in _deviation_reason({"steady_states": {"before": {"steady_state_met": False, "probes": []}}})
    assert "without executing" in _deviation_reason({"steady_states": {"before": {}}, "run": []})
    assert "target may not" in _deviation_reason({
        "steady_states": {"after": {"steady_state_met": False, "probes": []}},
        "run": [{}],
    })
    assert ExperimentRunner._contains_failed_action("=> failed: genuine failure") is True
