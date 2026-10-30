from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from chaosforge.engines.chaos_mesh.chaos_mesh_client import ChaosMeshClient
from chaosforge.engines.chaos_mesh.chaos_mesh_models import (
    ChaosMeshExecutionResult,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_runner import ChaosMeshRunner
from chaosforge.lifecycle.checks.kubernetes_chaos import (
    SharedChaosMeshValidationCheck,
)
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.lifecycle.lifecycle_runner import LifecycleRunner


def _experiment(experiment_id="chaos-mesh-pod-kill", **variables):
    return SimpleNamespace(
        id=experiment_id,
        name="Kubernetes chaos",
        service="eks",
        engine="Chaos Mesh",
        json_file=None,
        variables=variables,
        status="Pending",
        error_message="",
    )


def _manifest(kind="PodChaos", name="pod-kill"):
    return {
        "apiVersion": "chaos-mesh.org/v1alpha1",
        "kind": kind,
        "metadata": {"name": name, "namespace": "chaos-testing"},
        "spec": {"action": "pod-kill", "mode": "one"},
    }


def test_shared_check_runs_existing_pre_and_post_profiles(monkeypatch):
    pre_builder = MagicMock(
        return_value={"Pods Ready": lambda: (True, "all pods ready")}
    )
    post_builder = MagicMock(
        return_value={"Pods Recovered": lambda: (True, "all pods recovered")}
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.build_pre_validation_checks",
        pre_builder,
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.build_post_validation_checks",
        post_builder,
    )
    configure = MagicMock()
    discovery = SimpleNamespace(
        eks_kube_context="arn:aws:eks:region:account:cluster/demo",
        _configure_eks_kubernetes_client=configure,
    )
    experiment = _experiment(
        eks_cluster="demo",
        namespace="apps",
        deployment="api",
        labels={"app": "api"},
        pod="api-0",
        container_name="server",
        path="/cache",
    )
    check = SharedChaosMeshValidationCheck(discovery, experiment)

    baseline = check.capture(experiment.variables)
    post = check.validate(experiment.variables, baseline)

    assert baseline["validation_available"] is True
    assert baseline["validation_experiment_id"] == "aks-pod-kill"
    assert baseline["checks"]["Pods Ready"]["detail"] == "all pods ready"
    assert post["passed"] is True
    assert post["validation_experiment_id"] == "aks-pod-kill"
    assert post["checks"]["Pods Recovered"]["detail"] == "all pods recovered"
    assert configure.call_args_list == [call("demo"), call("demo")]
    assert pre_builder.call_args.kwargs["aks_context"] == discovery.eks_kube_context
    assert pre_builder.call_args.kwargs["target_mode"] == "pod"
    assert pre_builder.call_args.kwargs["exact_pod_name"] == "api-0"
    assert post_builder.call_args.args[:4] == (
        "aks-pod-kill",
        discovery.eks_kube_context,
        "apps",
        "api",
    )
    assert post_builder.call_args.kwargs["volume_path"] == "/cache"


def test_shared_check_records_warning_and_chaos_observer_samples(monkeypatch):
    observations = iter(
        [
            "probe unavailable",
            {"severity": "CHAOS", "message": "pod disruption observed"},
        ]
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.observe_fault",
        lambda *args, **kwargs: next(observations),
    )
    experiment = _experiment(namespace="apps", deployment="api")
    check = SharedChaosMeshValidationCheck(SimpleNamespace(), experiment)

    first = check.observe_during(
        experiment.variables,
        _manifest(),
        {"status": {"phase": "Running"}},
    )
    second = check.observe_during(
        experiment.variables,
        _manifest(),
        {"status": {"phase": "Running"}},
    )

    assert first == {
        "resource_phase": "Running",
        "severity": "WARNING",
        "message": "probe unavailable",
    }
    assert second["severity"] == "CHAOS"
    assert check.runtime_validation["samples"] == [first, second]
    assert check.runtime_validation["fault_observed"] is True
    assert check.runtime_validation["passed"] is True


def test_unmapped_chaos_mesh_experiment_is_a_validation_no_op():
    experiment = _experiment("chaos-mesh-jvm", manifest=_manifest("JVMChaos"))

    assert CheckResolver().resolve(experiment, discovery=SimpleNamespace()) is None

    check = SharedChaosMeshValidationCheck(SimpleNamespace(), experiment)
    assert check.capture(experiment.variables) == {"validation_available": False}
    assert check.runtime_validation == {
        "available": False,
        "passed": False,
        "fault_observed": False,
        "samples": [],
    }


def test_runner_observer_receives_created_and_polled_resources():
    manifest = _manifest()
    created = {**manifest, "status": {"phase": "Running"}}
    running = {**manifest, "status": {"phase": "Running"}}
    finished = {**manifest, "status": {"phase": "Finished"}}
    client = MagicMock()
    client.create.return_value = created

    def wait_for(**kwargs):
        kwargs["on_poll"](running)
        kwargs["on_poll"](finished)
        return finished

    client.wait_for.side_effect = wait_for
    observer = MagicMock()
    observer.runtime_validation = {
        "available": True,
        "passed": True,
        "fault_observed": True,
        "samples": [{"severity": "CHAOS"}],
    }
    experiment = _experiment(manifest=manifest)

    result = ChaosMeshRunner(client=client).execute(experiment, observer=observer)

    assert result.success is True
    assert result.validation == observer.runtime_validation
    assert observer.observe_during.call_args_list == [
        call(experiment.variables, manifest, created),
        call(experiment.variables, manifest, running),
        call(experiment.variables, manifest, finished),
    ]


def test_client_observes_every_poll_including_terminal_resource():
    running = {"status": {"phase": "Running"}}
    finished = {"status": {"phase": "Finished"}}
    client = ChaosMeshClient(custom_objects_api=MagicMock())
    client.get = MagicMock(side_effect=[running, finished])
    observer = MagicMock()

    result = client.wait_for(
        kind="PodChaos",
        name="pod-kill",
        namespace="apps",
        predicate=lambda resource: resource["status"]["phase"] == "Finished",
        on_poll=observer,
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert result is finished
    assert observer.call_args_list == [call(running), call(finished)]


def test_runner_observer_forces_wait_and_reports_unobserved_fault():
    manifest = _manifest()
    created = {**manifest, "status": {"phase": "Running"}}
    finished = {**manifest, "status": {"phase": "Finished"}}
    client = MagicMock()
    client.create.return_value = created
    client.wait_for.return_value = finished
    observer = MagicMock()
    observer.runtime_validation = {
        "available": True,
        "passed": False,
        "fault_observed": False,
        "samples": [],
    }

    result = ChaosMeshRunner(client=client).execute(
        _experiment(manifest=manifest), observer=observer
    )

    assert result.success is False
    assert result.error == "The configured fault was not observed."
    client.wait_for.assert_called_once()


def test_runner_timeout_still_attempts_cleanup():
    manifest = _manifest()
    created = {**manifest, "status": {"phase": "Running"}}
    client = MagicMock()
    client.create.return_value = created
    client.wait_for.side_effect = TimeoutError("observation timed out")
    observer = MagicMock()
    observer.runtime_validation = {
        "available": True,
        "passed": False,
        "fault_observed": False,
        "samples": [],
    }

    result = ChaosMeshRunner(client=client).execute(
        _experiment(manifest=manifest, timeout_seconds=0), observer=observer
    )

    assert result.success is False
    assert result.error == "observation timed out"
    assert result.cleanup == {
        "attempted": True,
        "deleted": True,
        "confirmed_absent": True,
    }
    observer.observe_during.assert_called_once_with(
        _experiment(manifest=manifest, timeout_seconds=0).variables,
        manifest,
        created,
    )


@pytest.mark.parametrize("failure_method", ["delete", "wait_for_deleted"])
def test_runner_cleanup_failure_overrides_success(failure_method):
    manifest = _manifest()
    created = {**manifest, "status": {"phase": "Running"}}
    client = MagicMock()
    client.create.return_value = created
    getattr(client, failure_method).side_effect = RuntimeError("cleanup failed")

    result = ChaosMeshRunner(client=client).execute(_experiment(manifest=manifest))

    assert result.success is False
    assert result.error == "cleanup failed"
    assert result.cleanup == {
        "attempted": True,
        "deleted": False,
        "confirmed_absent": False,
        "error": "cleanup failed",
    }


def test_lifecycle_evidence_keeps_during_fault_and_post_validation(monkeypatch):
    runtime_validation = {
        "available": True,
        "passed": True,
        "fault_observed": True,
        "samples": [{"severity": "CHAOS", "message": "fault observed"}],
    }
    post_validation = {
        "passed": True,
        "validation_experiment_id": "aks-pod-kill",
        "checks": {"Pods Recovered": {"passed": True}},
    }

    class Check:
        name = "shared-kubernetes-chaos-validation"
        recovery_supported = False

        def capture(self, target):
            return {"passed": True}

        def observe_during(self, target, manifest, resource):
            raise AssertionError("the dispatcher owns during-fault observation")

        def validate(self, target, baseline):
            return post_validation

    class Dispatcher:
        def __init__(self):
            self.observer = None

        def execute(self, experiment, observer=None):
            self.observer = observer
            return ChaosMeshExecutionResult(
                success=True,
                resource_kind="PodChaos",
                resource_name="pod-kill",
                namespace="apps",
                manifest=_manifest(),
                validation=runtime_validation,
                cleanup={"attempted": True, "deleted": True},
            )

    written = []

    class EvidenceWriter:
        def write(self, evidence):
            written.append(evidence)
            return "/tmp/evidence"

    class BundleWriter:
        def create_bundle(self, execution_id):
            return "/tmp/evidence.zip"

    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter", EvidenceWriter
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter", BundleWriter
    )
    dispatcher = Dispatcher()
    experiment = _experiment(namespace="apps", deployment="api")
    runner = LifecycleRunner(
        runner=MagicMock(),
        check_resolver=SimpleNamespace(resolve=lambda *args: Check()),
        dispatcher=dispatcher,
    )

    context = runner.execute(experiment)

    assert dispatcher.observer is not None
    assert context.observability["chaos_mesh"]["during_fault"] == runtime_validation
    assert context.observability["chaos_mesh"]["cleanup"] == {
        "attempted": True,
        "deleted": True,
    }
    assert context.validation["result"] == post_validation
    assert context.events == runtime_validation["samples"]
    assert written[0]["observability"] == context.observability
    assert written[0]["validation"] == context.validation
    assert written[0]["result"]["success"] is True


def test_lifecycle_keeps_advisory_post_validation_as_warning_success(monkeypatch):
    post_validation = {
        "passed": True,
        "checks": {
            "Probe Failures Stopped (post)": {
                "passed": False,
                "severity": "ADVISORY",
                "detail": "Recent Unhealthy probe events remain.",
            }
        },
        "warnings": [
            {
                "label": "Probe Failures Stopped (post)",
                "severity": "ADVISORY",
                "detail": "Recent Unhealthy probe events remain.",
            }
        ],
        "blocking_failures": [],
    }

    class Check:
        name = "shared-kubernetes-chaos-validation"
        recovery_supported = False

        def capture(self, target):
            return {"passed": True}

        def validate(self, target, baseline):
            return post_validation

    class Dispatcher:
        def execute(self, experiment, observer=None):
            return ChaosMeshExecutionResult(
                success=True,
                resource_kind="NetworkChaos",
                resource_name="network-delay",
                namespace="apps",
                manifest=_manifest("NetworkChaos", "network-delay"),
                validation={"samples": []},
                cleanup={"attempted": True, "deleted": True},
            )

    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter",
        lambda: MagicMock(write=lambda evidence: "/tmp/evidence"),
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter",
        lambda: MagicMock(create_bundle=lambda execution_id: "/tmp/evidence.zip"),
    )
    experiment = _experiment("chaos-mesh-network-delay", namespace="apps", deployment="api")
    runner = LifecycleRunner(
        runner=MagicMock(),
        check_resolver=SimpleNamespace(resolve=lambda *args: Check()),
        dispatcher=Dispatcher(),
    )

    context = runner.execute(experiment)

    assert experiment.status == "SUCCESS_WITH_WARNINGS"
    assert experiment.warnings == post_validation["warnings"]
    assert context.result["success"] is True
    assert context.result["outcome"] == "SUCCESS_WITH_WARNINGS"
    assert context.result["warnings"] == post_validation["warnings"]
    assert context.validation["result"] == post_validation
