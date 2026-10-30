import builtins
import json
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.application.services import generic
from chaosforge.engines.chaos_mesh.chaos_mesh_execution_gate import (
    ChaosMeshExecutionGate,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshReleaseInfo,
    HelmReleaseStatus,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_preflight import (
    ChaosMeshPreflight,
    ChaosMeshPreflightResult,
)
from chaosforge.engines.chaos_toolkit import runner as toolkit_runner
from chaosforge.interfaces.web import app as web_app
from chaosforge.interfaces.web import execution as web_execution
from chaosforge.lifecycle.checks.adapter import ResourceAdapter
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.lifecycle.lifecycle_report import LifecycleReportRenderer
from chaosforge.reporting import report_generator


class Builder:
    def __init__(self, available=True):
        self.available = available
        self.calls = []

    def __getattr__(self, name):
        if not self.available or not name.startswith("build_"):
            raise AttributeError(name)

        def build(**kwargs):
            self.calls.append(kwargs)
            return {
                "apiVersion": "chaos-mesh.org/v1alpha1",
                "kind": "TestChaos",
                "metadata": {"name": kwargs["name"]},
                "spec": kwargs,
            }

        return build


def _mapped(tmp_path, kind, action, configuration, builder=None):
    path = tmp_path / f"{kind}-{action}.json"
    path.write_text(
        json.dumps({
            "chaos_mesh": {"kind": kind, "action": action},
            "configuration": configuration,
        }),
        encoding="utf-8",
    )
    builder = builder or Builder()
    mapper = ChaosMeshExperimentMapper(builder=builder)
    experiment = SimpleNamespace(id="residual", variables={}, json_file=str(path))
    return mapper.build_manifest(experiment), builder


def test_mapper_remaining_normalization_and_error_paths(tmp_path, monkeypatch):
    _, builder = _mapped(
        tmp_path,
        "StressChaos",
        "stress",
        {"stressors": {"cpu": {"workers": 3}, "memory": {"size": "1GB"}}},
    )
    assert builder.calls[0]["stressors"] == {
        "cpu": {"workers": 3},
        "memory": {"size": "1GB"},
    }

    _, builder = _mapped(
        tmp_path,
        "IOChaos",
        "attrOverride",
        {"volume_path": "/data", "attr_override": {"perm": "999"}},
    )
    assert builder.calls[0]["attr"] == {"perm": 999}

    _, builder = _mapped(
        tmp_path,
        "NetworkChaos",
        "reorder",
        {"reorder": {"reorder": "20", "gap": 4}},
    )
    assert builder.calls[0]["delay"]["reorder"]["gap"] == 4

    mapper = ChaosMeshExperimentMapper(builder=Builder(available=False))
    definition = tmp_path / "missing-builder.json"
    definition.write_text(
        json.dumps({"chaos_mesh": {"kind": "PodChaos", "action": "pod-kill"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="No Chaos Mesh builder"):
        mapper.build_manifest(
            SimpleNamespace(id="pod", variables={}, json_file=str(definition))
        )

    mapper = ChaosMeshExperimentMapper(builder=Builder())
    mapper._validate_target("cluster", "apps", None, None, None)
    assert mapper._pod_selector(labels={"app": "api"}) == {
        "labelSelectors": {"app": "api"}
    }


def test_mapper_reaches_final_unsupported_kind_guard(tmp_path, monkeypatch):
    builder = Builder()
    mapper = ChaosMeshExperimentMapper(builder=builder)
    monkeypatch.setattr(mapper, "_kind_to_method", lambda kind: "alien_chaos")
    path = tmp_path / "alien.json"
    path.write_text(
        json.dumps({"chaos_mesh": {"kind": "AlienChaos", "action": "zap"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported Chaos Mesh kind"):
        mapper.build_manifest(SimpleNamespace(id="alien", variables={}, json_file=str(path)))


def test_preflight_client_factory_success_and_import_fallback(monkeypatch):
    api = object()
    client = SimpleNamespace(CustomObjectsApi=MagicMock(return_value=api))
    monkeypatch.setitem(sys.modules, "kubernetes", SimpleNamespace(client=client))
    assert ChaosMeshPreflight(MagicMock())._custom_objects_api() is api

    real_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "kubernetes":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    assert ChaosMeshPreflight(MagicMock())._custom_objects_api() is None


def test_execution_gate_reports_install_block_and_failed_final_preflight():
    discovery = SimpleNamespace(eks_kubeconfig_path="config", eks_kube_context="ctx")
    installer = MagicMock()
    installer.release_status.return_value = (HelmReleaseStatus.ABSENT, "missing")
    installer.release_info.return_value = ChaosMeshReleaseInfo(
        HelmReleaseStatus.ABSENT, "missing"
    )
    mapper = MagicMock()
    mapper.build_manifest.return_value = {
        "kind": "PodChaos",
        "metadata": {"namespace": "apps"},
    }
    blocked = ChaosMeshPreflightResult("BLOCKED", "cluster", "PodChaos")
    blocked.blockers = ["not ready"]
    preflight = MagicMock()
    preflight.check.return_value = blocked
    gate = ChaosMeshExecutionGate(discovery, installer, preflight, mapper)
    experiment = SimpleNamespace(
        variables={"eks_cluster": "cluster"}, chaos_mesh_version_action="install"
    )

    installer.ensure_installed.return_value = SimpleNamespace(
        status="BLOCKED", message="installation denied"
    )
    with pytest.raises(RuntimeError, match="installation denied"):
        gate.ensure_ready(experiment)

    installer.ensure_installed.return_value = SimpleNamespace(status="INSTALLED", message="ok")
    with pytest.raises(RuntimeError, match="still not ready.*not ready"):
        gate.ensure_ready(experiment)


def test_toolkit_fis_parameters_and_azure_recovery(monkeypatch):
    catalog = MagicMock()
    catalog.get_experiment.side_effect = [None, {"parameters": [{"name": "count"}]}]
    monkeypatch.setattr(
        "chaosforge.providers.aws.fis.catalog.FISCatalog", MagicMock(return_value=catalog)
    )
    assert toolkit_runner._fis_action_parameters({}) == {}
    assert toolkit_runner._fis_action_parameters({"count": 2}) == {"count": 2}

    cleanup = MagicMock()
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor.cleanup_experiment",
        cleanup,
    )
    lines = []
    experiment = SimpleNamespace(
        engine="Azure Chaos Studio",
        variables={"namespace": "apps", "ignored": "value"},
    )
    assert toolkit_runner._attempt_direct_recovery(experiment, lines) is True
    cleanup.assert_called_once_with(namespace="apps")
    assert "cleanup completed" in "".join(lines)


def test_toolkit_execute_passes_fis_variables_to_library_and_removes_temp_files(monkeypatch):
    run = MagicMock(return_value={"status": "completed", "steady_states": {"before": {"steady_state_met": True}}, "run": [{}], "rollbacks": []})
    monkeypatch.setattr(toolkit_runner, "load_experiment", lambda _: {})
    monkeypatch.setattr(toolkit_runner, "ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr(toolkit_runner, "run_experiment", run)
    monkeypatch.setattr(toolkit_runner, "_fis_action_parameters", lambda variables: {"count": 2})
    monkeypatch.setattr(toolkit_runner.os.path, "exists", lambda path: True)
    remove = MagicMock()
    monkeypatch.setattr(toolkit_runner.os, "remove", remove)
    experiment = SimpleNamespace(
        id="fis",
        service="fis",
        name="FIS",
        engine="AWS FIS",
        json_file="experiment.json",
        variables={"dry_run": "true"},
    )

    context = toolkit_runner.ExperimentRunner().execute(experiment)

    variables, secrets = run.call_args.kwargs["experiment_vars"]
    assert variables["fis_action_parameters_json"] == '{"count":2}'
    assert variables["dry_run"] == "true"
    assert variables["recovery_file"] == experiment.variables["recovery_file"]
    assert secrets is None
    assert context.state.value == "FAULT_INJECTION_SUCCEEDED"
    remove.assert_called_once_with(experiment.variables["recovery_file"])


def test_toolkit_interrupt_handles_provider_cleanup_error_and_removes_files(monkeypatch):
    monkeypatch.setattr(toolkit_runner, "load_experiment", lambda _: {})
    monkeypatch.setattr(toolkit_runner, "ensure_experiment_is_valid", lambda _: None)
    monkeypatch.setattr(
        toolkit_runner, "run_experiment", lambda *_args, **_kwargs: {"status": "interrupted", "interrupted": True, "rollbacks": []}
    )
    monkeypatch.setattr(
        toolkit_runner,
        "_attempt_direct_recovery",
        MagicMock(side_effect=RuntimeError("cleanup unavailable")),
    )
    monkeypatch.setattr(toolkit_runner.os.path, "exists", lambda path: True)
    remove = MagicMock()
    monkeypatch.setattr(toolkit_runner.os, "remove", remove)
    experiment = SimpleNamespace(
        id="fis",
        service="fis",
        name="FIS",
        engine="AWS FIS",
        json_file="experiment.json",
        variables={},
    )

    context = toolkit_runner.ExperimentRunner().execute(experiment)

    assert context.state.value == "CLEANUP_FAILED"
    assert "Provider cleanup failed: cleanup unavailable" in experiment.cli_output
    remove.assert_called_once_with(experiment.variables["recovery_file"])


def test_report_helpers_cover_spinner_blank_and_impact_boundaries():
    assert report_generator._format_label("target_name") == "Target Name"
    cleaned = report_generator._clean_cli_output(
        "\x1b[31mwarning\x1b[0m\n"
        "⚡  Draining worker...\n"
        "⚡  Draining worker...\n"
        "\n\ncomplete"
    )
    assert cleaned.count("live progress") == 1
    assert "\n\n\n" not in cleaned
    assert report_generator._extract_impact_summary("") == []
    assert report_generator._extract_impact_summary("ordinary output") == []
    assert report_generator._extract_impact_summary(
        "During-experiment impact observed:\n\n  latency: 20 ms\nNode health:"
    ) == ["  latency: 20 ms"]


def test_report_generation_covers_skipped_and_missing_cli_output(monkeypatch, tmp_path):
    monkeypatch.setattr(report_generator, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(report_generator, "show_report_summary", MagicMock())
    monkeypatch.setattr(report_generator, "display_name", lambda service: service.title())
    campaign = SimpleNamespace(
        name="Residual",
        experiments=[SimpleNamespace(service="lambda", name="Skip", status="SKIPPED")],
    )
    report_generator.generate_report(campaign)
    report = next(tmp_path.glob("*.txt")).read_text(encoding="utf-8")
    assert "Skipped           : 1" in report
    assert "(no CLI output captured)" in report


def test_generic_lazy_input_bridge_lifecycle_fallbacks_and_web_404(monkeypatch):
    collect = MagicMock(return_value={"count": 2})
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.input_engine.collect_inputs", collect
    )
    assert generic.collect_inputs("metadata", prefill={"count": 1}) == {"count": 2}
    collect.assert_called_once_with("metadata", prefill={"count": 1})

    with pytest.raises(NotImplementedError):
        ResourceAdapter.capture(object(), {})
    assert LifecycleReportRenderer._line("Observed", None).endswith(": -")

    web_app.app.config.update(TESTING=True)
    response = web_app.app.test_client().post("/cloud/gcp/campaign-yaml/review")
    assert response.status_code == 404


@pytest.mark.parametrize("experiment_id", ["elasticache-daily-snapshot", "s3-bucket-policy"])
def test_lifecycle_resolver_remaining_common_adapter_paths(experiment_id):
    check = CheckResolver().resolve(SimpleNamespace(id=experiment_id, variables={}))
    assert isinstance(check, CommonResourceCheck)
    assert check.name == f"{experiment_id}-lifecycle"


def test_web_execution_without_campaign_and_outer_discovery_failure(monkeypatch):
    manager = MagicMock(running=False)
    monkeypatch.setattr(web_execution, "log_manager", manager)
    web_execution.WebExecution(history=MagicMock()).execute()
    assert any("No campaign selected" in call.args[0] for call in manager.append.call_args_list)


def test_web_log_stream_strips_terminal_controls(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(web_execution, "log_manager", manager)
    stream = web_execution._WebLogStream()

    stream.write("\x1b[94mPHASE 1\x1b[0m\n\x1b[2K\rStarting\x1b[?25l\n")
    stream.write("\x1b]0;ChaosForge\x07Complete")
    stream.finish()

    assert [call.args[0] for call in manager.append.call_args_list] == [
        "PHASE 1",
        "Starting",
        "Complete",
    ]

    class InputsFailOnThirdRead(dict):
        def __init__(self):
            super().__init__(id="fault")
            self.reads = 0

        def get(self, key, default=None):
            if key == "inputs":
                self.reads += 1
                if self.reads == 3:
                    raise RuntimeError("iteration failed")
                return []
            return super().get(key, default)

    selected = InputsFailOnThirdRead()
    monkeypatch.setattr(web_app, "load_metadata", lambda service: {"experiments": [selected]})
    monkeypatch.setattr(web_app, "_web_experiment_metadata", lambda metadata, service: metadata)
    monkeypatch.setattr(web_app, "get_experiment_description", lambda *args: {})
    monkeypatch.setattr(web_app, "AWSDiscovery", MagicMock())
    monkeypatch.setattr(web_app, "render_template", MagicMock(return_value="page"))
    web_app.app.config.update(TESTING=True)
    response = web_app.app.test_client().get("/experiment/lambda/fault")
    assert response.status_code == 200
    assert web_app.render_template.call_args.kwargs["discovered_resources"] == []


def test_package_and_web_entrypoint_guards(monkeypatch):
    cli_main = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.cli.main.main", cli_main)
    monkeypatch.delitem(sys.modules, "chaosforge.__main__", raising=False)
    runpy.run_module("chaosforge.__main__", run_name="__main__")
    cli_main.assert_called_once_with()

    run = MagicMock()
    monkeypatch.setattr(web_app.app, "run", run)
    monkeypatch.delitem(
        sys.modules,
        "chaosforge.interfaces.web.__main__",
        raising=False,
    )
    runpy.run_module("chaosforge.interfaces.web.__main__", run_name="__main__")
    run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False)

    with patch("flask.Flask.run") as flask_run:
        runpy.run_path(web_app.__file__, run_name="__main__")
    flask_run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False)
