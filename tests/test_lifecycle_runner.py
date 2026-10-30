import sys
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, patch

from chaosforge.engines.chaos_mesh.chaos_mesh_models import ChaosMeshExecutionResult
from chaosforge.lifecycle.lifecycle_runner import LifecycleRunner


class MockExperiment:
    id = "test-experiment"
    service = "eks"
    name = "Test Experiment"
    variables: ClassVar[dict] = {
        "cluster": "test-cluster",
        "namespace": "default",
    }
    status = "Pending"
    error_message = ""


def make_experiment(status="Pending", error_message=""):
    return SimpleNamespace(
        id="test-experiment",
        service="eks",
        name="Test Experiment",
        variables={
            "cluster": "test-cluster",
            "namespace": "default",
        },
        status=status,
        error_message=error_message,
    )


def make_runner(check=None):
    runner = MagicMock()
    resolver = MagicMock()
    resolver.resolve.return_value = check

    return LifecycleRunner(
        runner=runner,
        check_resolver=resolver,
        discovery=MagicMock(),
    )


def test_execute_without_lifecycle_check_uses_common_lifecycle():
    experiment = make_experiment(status="SUCCESS")
    lifecycle_runner = make_runner(check=None)

    lifecycle_runner.runner.execute.return_value = None

    result = lifecycle_runner.execute(experiment)

    assert result is not None
    assert result.experiment_id == experiment.id
    assert result.service == experiment.service

    lifecycle_runner.runner.execute.assert_called_once_with(
        experiment
    )

    assert result.injection["passed"] is True
    assert result.injection["experiment_status"] == experiment.status

    assert result.validation["enabled"] is False
    assert result.recovery["enabled"] is False

    assert result.result["success"] is True
    assert result.result["validation_available"] is False


def test_eks_chaos_mesh_dry_run_skips_post_validation(monkeypatch):
    experiment = SimpleNamespace(
        id="chaos-mesh-pod-kill",
        service="chaos_mesh",
        name="Pod Kill",
        variables={
            "eks_cluster": "test-cluster",
            "namespace": "default",
            "deployment": "api",
            "dry_run": "true",
        },
        status="SUCCESS",
        error_message="",
    )
    lifecycle_runner = make_runner(check=None)
    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.get_experiment",
        lambda *_: {"id": experiment.id},
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.ExperimentValidationService",
        lambda: MagicMock(validate_experiment=lambda _: {"valid": True}),
    )

    result = lifecycle_runner.execute(experiment)

    assert result.validation == {
        "enabled": False,
        "passed": True,
        "message": "Dry run preview only; post-validation was not run.",
    }


def test_execute_blocks_invalid_catalog_configuration_before_dispatch():
    experiment = SimpleNamespace(
        id="lambda-memory",
        service="lambda",
        name="Memory Modification",
        variables={
            "lambda_name": "demo",
            "aws_region": "eu-central-1",
            "target_memory_size": 1,
            "wait_seconds": 30,
        },
        status="Pending",
        error_message="",
    )
    lifecycle_runner = make_runner(check=None)

    result = lifecycle_runner.execute(experiment)

    lifecycle_runner.runner.execute.assert_not_called()
    assert experiment.status == "FAILED"
    assert "target_memory_size" in experiment.error_message
    assert result.injection["passed"] is False



@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_precheck_failure(
    mock_lifecycle,
    mock_evidence_builder,
    mock_artifact_writer,
    mock_bundle_writer,
):
    experiment = make_experiment()
    lifecycle_runner = make_runner(check=MagicMock())

    lifecycle = mock_lifecycle.return_value

    lifecycle.create_context.return_value = MagicMock(
        execution_id="execution-1",
        state=SimpleNamespace(value="PLANNED"),
    )

    lifecycle.run_precheck.return_value = False

    context = lifecycle_runner.execute(experiment)

    assert context is lifecycle.create_context.return_value
    assert experiment.status == "FAILED"
    assert (
        experiment.error_message
        == "Experiment precheck failed."
    )

    lifecycle.run_precheck.assert_called_once()

    lifecycle.complete.assert_called_once_with(context)

    mock_evidence_builder.return_value.build.assert_called_once_with(
        context,
        experiment,
    )


@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_runner_exception_marks_injection_failed(
    mock_lifecycle,
    mock_evidence_builder,
    mock_artifact_writer,
    mock_bundle_writer,
):
    experiment = make_experiment()
    lifecycle_runner = make_runner(check=MagicMock())

    lifecycle = mock_lifecycle.return_value

    lifecycle.create_context.return_value = MagicMock(
        execution_id="execution-2",
        state=SimpleNamespace(value="PLANNED"),
    )

    lifecycle.run_precheck.return_value = True
    lifecycle_runner.runner.execute.side_effect = RuntimeError(
        "chaos execution failed"
    )

    context = lifecycle_runner.execute(experiment)

    assert context is lifecycle.create_context.return_value
    assert experiment.status == "FAILED"
    assert experiment.error_message == "chaos execution failed"
    assert context.injection["passed"] is False
    assert context.injection["experiment_status"] == "FAILED"
    assert context.injection["check"] == experiment.name
    assert context.injection["error"] == "chaos execution failed"

    lifecycle.mark_injection_failed.assert_called_once_with(
        context,
        "chaos execution failed",
    )

    lifecycle.complete.assert_called_once_with(context)


@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_keyboard_interrupt_records_terminal_evidence(
    mock_lifecycle,
    _mock_evidence_builder,
    _mock_artifact_writer,
    _mock_bundle_writer,
):
    experiment = make_experiment()
    lifecycle_runner = make_runner(check=MagicMock())
    lifecycle = mock_lifecycle.return_value
    lifecycle.create_context.return_value = MagicMock(
        execution_id="execution-interrupt",
        state=SimpleNamespace(value="PLANNED"),
    )
    lifecycle.run_precheck.return_value = True
    lifecycle_runner.runner.execute.side_effect = KeyboardInterrupt

    lifecycle_runner.execute(experiment)

    assert experiment.status == "FAILED"
    assert experiment.error_message == "KeyboardInterrupt interrupted execution"
    lifecycle.mark_injection_failed.assert_called_once_with(
        lifecycle.create_context.return_value,
        "KeyboardInterrupt interrupted execution",
    )
    lifecycle.complete.assert_called_once_with(lifecycle.create_context.return_value)


@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_non_success_experiment_status(
    mock_lifecycle,
    mock_evidence_builder,
    mock_artifact_writer,
    mock_bundle_writer,
):
    experiment = make_experiment(
        status="FAILED",
        error_message="experiment failed",
    )

    lifecycle_runner = make_runner(check=MagicMock())
    lifecycle = mock_lifecycle.return_value

    lifecycle.create_context.return_value = MagicMock(
        execution_id="execution-3",
        state=SimpleNamespace(value="PLANNED"),
    )

    lifecycle.run_precheck.return_value = True

    context = lifecycle_runner.execute(experiment)

    assert context is lifecycle.create_context.return_value

    lifecycle.mark_injection_failed.assert_called_once_with(
        context,
        "experiment failed",
    )

    lifecycle.complete.assert_called_once_with(context)

@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_non_success_uses_default_error_message(
    mock_lifecycle,
    mock_evidence_builder,
    mock_artifact_writer,
    mock_bundle_writer,
):
    experiment = make_experiment(status="FAILED")
    del experiment.error_message

    lifecycle_runner = make_runner(check=MagicMock())
    lifecycle = mock_lifecycle.return_value

    lifecycle.create_context.return_value = MagicMock(
        execution_id="execution-4",
        state=SimpleNamespace(value="PLANNED"),
    )

    lifecycle.run_precheck.return_value = True

    context = lifecycle_runner.execute(experiment)

    assert context is lifecycle.create_context.return_value

    lifecycle.mark_injection_failed.assert_called_once_with(
        context,
        "Chaos experiment failed.",
    )


@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_success_runs_post_validation_and_recovery(
    mock_lifecycle,
    mock_evidence_builder,
    mock_artifact_writer,
    mock_bundle_writer,
):
    experiment = make_experiment(status="SUCCESS")

    lifecycle_runner = make_runner(check=MagicMock())
    lifecycle = mock_lifecycle.return_value

    lifecycle.create_context.return_value = MagicMock(
        execution_id="execution-5",
        state=SimpleNamespace(value="PLANNED"),
    )

    lifecycle.run_precheck.return_value = True
    lifecycle.validate.return_value = True
    lifecycle.validate_recovery.return_value = True

    context = lifecycle_runner.execute(experiment)

    assert context is lifecycle.create_context.return_value

    lifecycle.mark_running.assert_called_once_with(context)

    lifecycle.mark_injection_succeeded.assert_called_once_with(
        context,
    )

    lifecycle.validate.assert_called_once_with(
        context,
        experiment.variables,
        phase="post",
    )

    lifecycle.validate_recovery.assert_called_once_with(
        context,
        experiment.variables,
    )

    lifecycle.complete.assert_called_once_with(context)


@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_success_handles_failed_validation_and_recovery(
    mock_lifecycle,
    mock_evidence_builder,
    mock_artifact_writer,
    mock_bundle_writer,
):
    experiment = make_experiment(status="SUCCESS")

    lifecycle_runner = make_runner(check=MagicMock())
    lifecycle = mock_lifecycle.return_value

    lifecycle.create_context.return_value = MagicMock(
        execution_id="execution-6",
        state=SimpleNamespace(value="PLANNED"),
    )

    lifecycle.run_precheck.return_value = True
    lifecycle.validate.return_value = False
    lifecycle.validate_recovery.return_value = False

    context = lifecycle_runner.execute(experiment)

    assert context is lifecycle.create_context.return_value

    lifecycle.validate.assert_called_once_with(
        context,
        experiment.variables,
        phase="post",
    )

    lifecycle.validate_recovery.assert_called_once_with(
        context,
        experiment.variables,
    )

    lifecycle.complete.assert_called_once_with(context)


@patch("chaosforge.lifecycle.lifecycle_runner.get_experiment", return_value=None)
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_eks_workload_reports_phases_and_dispatches_direct_execution(
    mock_lifecycle,
    _mock_get_experiment,
):
    experiment = SimpleNamespace(
        id="chaos-mesh-network-delay",
        service="chaos_mesh",
        name="Network Delay",
        variables={
            "eks_cluster": "cluster-a",
            "namespace": "default",
            "deployment": "api",
        },
        status="SUCCESS",
        error_message="",
    )
    dispatcher = MagicMock()
    lifecycle_runner = LifecycleRunner(
        runner=MagicMock(),
        check_resolver=MagicMock(),
        dispatcher=dispatcher,
    )
    lifecycle_runner.check_resolver.resolve.return_value = None
    lifecycle = mock_lifecycle.return_value
    context = MagicMock()
    context.state.value = "PLANNED"
    lifecycle.create_context.return_value = context
    lifecycle.run_precheck.return_value = True
    lifecycle_runner._complete_with_evidence = MagicMock(return_value=context)

    phase_ui = MagicMock()
    phase_ui.phase.return_value.__enter__.return_value = MagicMock()
    phase_ui_constructor = MagicMock(return_value=phase_ui)
    phase_ui_module = MagicMock(PhaseUI=phase_ui_constructor)

    with patch.dict(
        sys.modules,
        {"chaosforge.interfaces.cli.interactive.phase_ui": phase_ui_module},
    ):
        assert lifecycle_runner.execute(experiment) is context

    phase_ui_constructor.assert_called_once_with(experiment.id)
    assert phase_ui.phase.call_args_list == [
        (("setup",),),
        (("pre-check",),),
        (("experiment-setup",),),
        (("experiment",),),
        (("rollback",),),
        (("post-check",),),
    ]
    assert phase_ui.phase.return_value.__enter__.return_value.step.call_count == 9
    dispatcher.execute.assert_called_once_with(experiment, observer=None)


@patch("chaosforge.lifecycle.lifecycle_runner.get_experiment", return_value=None)
@patch("chaosforge.lifecycle.lifecycle_runner.LifecycleCoordinator")
def test_execute_eks_workload_records_failed_direct_execution(
    mock_lifecycle,
    _mock_get_experiment,
):
    experiment = SimpleNamespace(
        id="chaos-mesh-network-delay",
        service="chaos_mesh",
        name="Network Delay",
        variables={"eks_cluster": "cluster-a", "namespace": "default"},
        status="SUCCESS",
        error_message="",
    )
    dispatcher = MagicMock()
    dispatcher.execute.return_value = ChaosMeshExecutionResult(
        success=False,
        resource_kind="NetworkChaos",
        resource_name="delay",
        namespace="default",
        error="Chaos Mesh rejected the resource",
    )
    lifecycle_runner = LifecycleRunner(
        runner=MagicMock(),
        check_resolver=MagicMock(resolve=MagicMock(return_value=None)),
        dispatcher=dispatcher,
    )
    lifecycle = mock_lifecycle.return_value
    context = MagicMock()
    context.state.value = "PLANNED"
    lifecycle.create_context.return_value = context
    lifecycle.run_precheck.return_value = True
    lifecycle_runner._complete_with_evidence = MagicMock(return_value=context)
    phase_ui = MagicMock()
    phase_ui.phase.return_value.__enter__.return_value = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "chaosforge.interfaces.cli.interactive.phase_ui": MagicMock(
                PhaseUI=MagicMock(return_value=phase_ui)
            )
        },
    ):
        assert lifecycle_runner.execute(experiment) is context

    assert experiment.error_message == "Chaos Mesh rejected the resource"
    lifecycle.mark_injection_failed.assert_called_once_with(
        context, "Chaos Mesh rejected the resource"
    )


def test_build_target_returns_copy_of_experiment_variables():
    experiment = make_experiment()

    target = LifecycleRunner._build_target(experiment)

    assert target == experiment.variables
    assert target is not experiment.variables


def test_build_target_extracts_ec2_instance_id_from_fis_arn():
    experiment = SimpleNamespace(
        variables={
            "service_id": "ec2",
            "target_arn": "arn:aws:ec2:eu-central-1:123456789012:instance/i-123",
        }
    )

    target = LifecycleRunner._build_target(experiment)

    assert target["instance_ids"] == ["i-123"]


def test_build_target_extracts_lambda_name_from_fis_arn():
    experiment = SimpleNamespace(
        variables={
            "service_id": "lambda",
            "target_arn": "arn:aws:lambda:eu-central-1:123456789012:function:processor",
        }
    )

    target = LifecycleRunner._build_target(experiment)

    assert target["lambda_name"] == "processor"


def test_build_target_marks_only_eks_pod_delete_as_exact_pod_target():
    experiment = SimpleNamespace(
        variables={"service_id": "eks", "experiment_id": "pod-cpu-stress"}
    )

    assert "target_mode" not in LifecycleRunner._build_target(experiment)


def test_build_target_marks_eks_fis_pod_delete_as_exact_pod_target():
    experiment = SimpleNamespace(
        variables={"service_id": "eks", "experiment_id": "pod-delete"}
    )

    assert LifecycleRunner._build_target(experiment)["target_mode"] == "pod"


def test_s3_lifecycle_precheck_uses_catalog_bucket_name(monkeypatch, tmp_path):
    from chaosforge.lifecycle.checks.aws_adapters import S3BucketAdapter
    from chaosforge.lifecycle.checks.resolver import CheckResolver

    client = MagicMock()
    client.head_bucket.return_value = {}
    client.get_bucket_encryption.return_value = {}
    client.get_bucket_versioning.return_value = {}
    client.get_public_access_block.return_value = {}
    client.get_bucket_lifecycle_configuration.return_value = {}
    client.get_bucket_policy.return_value = {}
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.aws_adapters.boto3.client",
        lambda *_args, **_kwargs: client,
    )

    experiment = SimpleNamespace(
        id="s3-versioning",
        service="s3",
        name="Bucket Versioning",
        engine="Chaos Toolkit",
        variables={"aws_region": "eu-central-1", "bucket_name": "test-bucket"},
        status="Pending",
        error_message="",
    )
    check = CheckResolver().resolve(experiment)

    assert isinstance(check.adapter, S3BucketAdapter)
    baseline = check.capture(experiment.variables)

    assert baseline["identity"]["bucket"] == "test-bucket"
    client.head_bucket.assert_called_once_with(Bucket="test-bucket")


@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter")
@patch("chaosforge.lifecycle.lifecycle_runner.EvidenceBuilder")
def test_complete_with_evidence(
    mock_evidence_builder,
    mock_artifact_writer,
    mock_bundle_writer,
):
    lifecycle_runner = LifecycleRunner(
        runner=MagicMock(),
        check_resolver=MagicMock(),
    )

    lifecycle = MagicMock()
    context = MagicMock()
    experiment = make_experiment()

    evidence_builder = mock_evidence_builder.return_value
    evidence_writer = mock_artifact_writer.return_value
    bundle_writer = mock_bundle_writer.return_value

    context.execution_id = "execution-7"
    context.state.value = "COMPLETE"

    evidence = {"execution": {"id": "execution-7"}}

    evidence_builder.build.return_value = evidence
    evidence_writer.write.return_value = "/tmp/evidence"
    bundle_writer.create_bundle.return_value = "/tmp/evidence.zip"

    result = lifecycle_runner._complete_with_evidence(
        lifecycle,
        context,
        experiment,
        evidence_builder,
        evidence_writer,
        bundle_writer,
    )

    assert result is context

    lifecycle.complete.assert_called_once_with(context)

    evidence_builder.build.assert_called_once_with(
        context,
        experiment,
    )

    evidence_writer.write.assert_called_once_with(evidence)

    bundle_writer.create_bundle.assert_called_once_with(
        "execution-7",
    )

    assert context.evidence == evidence


def test_complete_with_evidence_prints_failure_details_and_keeps_toolkit_log(capsys):
    lifecycle_runner = LifecycleRunner(runner=MagicMock(), check_resolver=MagicMock())
    lifecycle = MagicMock()
    context = MagicMock()
    context.execution_id = "execution-failure"
    context.state.value = "FAULT_INJECTION_FAILED"
    context.validation = {}
    context.injection = {"passed": False, "error": "provider rejected the target"}
    context.precheck = {}
    context.recovery = {}
    context.errors = ["provider rejected the target"]
    context.logs = []
    experiment = make_experiment(status="FAILED", error_message="provider rejected the target")
    experiment.cli_output = "Action update: failed\n"

    evidence_builder = MagicMock()
    evidence_writer = MagicMock()
    bundle_writer = MagicMock()
    evidence_builder.build.return_value = {}
    evidence_writer.write.return_value = "/tmp/evidence"
    bundle_writer.create_bundle.return_value = "/tmp/evidence.zip"

    lifecycle_runner._complete_with_evidence(
        lifecycle,
        context,
        experiment,
        evidence_builder,
        evidence_writer,
        bundle_writer,
    )

    assert "Failure details:" in capsys.readouterr().out
    assert context.logs == ["Action update: failed\n"]


def test_failure_details_collects_distinct_lifecycle_error_sources():
    context = SimpleNamespace(
        injection={"error": "injection failed"},
        precheck={"error": "precheck failed"},
        validation={"error": "validation failed"},
        recovery={"error": "recovery failed"},
        errors=["injection failed", "additional context"],
    )
    experiment = SimpleNamespace(error_message="provider rejected target")

    assert LifecycleRunner._failure_details(context, experiment) == [
        "provider rejected target",
        "injection failed",
        "precheck failed",
        "validation failed",
        "recovery failed",
        "additional context",
    ]


def test_lifecycle_runner_executes_without_check(
    tmp_path,
    monkeypatch,
):
    from chaosforge.lifecycle.lifecycle_runner import LifecycleRunner

    class MockExperiment:
        id = "test-experiment"
        service = "eks"
        name = "Test Experiment"
        json_file = "mock.json"
        engine = "Chaos Toolkit"
        variables: ClassVar[dict[str, str]] = {
            "function_name": "test-function",
            "region": "us-east-1",
        }
        status = "Pending"
        error_message = None

    class MockRunner:
        def execute(self, experiment):
            experiment.status = "SUCCESS"

    class MockResolver:
        def resolve(self, experiment, discovery=None):
            return None

    class MockEvidenceWriter:
        def __init__(self):
            self.evidence_root = str(tmp_path)

        def write(self, evidence):
            execution_id = evidence["execution"]["execution_id"]
            execution_dir = tmp_path / execution_id
            execution_dir.mkdir(
                parents=True,
                exist_ok=True,
            )
            return str(execution_dir)

    class MockBundleWriter:
        def create_bundle(self, execution_id):
            return str(
                tmp_path / f"{execution_id}.zip"
            )

    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter",
        MockEvidenceWriter,
    )

    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter",
        MockBundleWriter,
    )

    lifecycle_runner = LifecycleRunner(
        runner=MockRunner(),
        check_resolver=MockResolver(),
    )

    context = lifecycle_runner.execute(
        MockExperiment()
    )

    assert context.injection["passed"] is True
    assert context.validation["enabled"] is False
    assert context.recovery["enabled"] is False
    assert context.result["success"] is True
    assert context.result["validation_available"] is False

def test_lambda_lifecycle_runner_executes_with_real_resolver(
    tmp_path,
    monkeypatch,
):
    class FakeLambdaAdapter:
        name = "lambda-resource-adapter"

        def __init__(self):
            self.snapshots = iter(
                [
                    {
                        "exists": True,
                        "configuration": {
                            "memory_size": 512,
                            "timeout": 30,
                        },
                    },
                    {
                        "exists": True,
                        "configuration": {
                            "memory_size": 512,
                            "timeout": 30,
                        },
                    },
                    {
                        "exists": True,
                        "configuration": {
                            "memory_size": 512,
                            "timeout": 30,
                        },
                    },
                ]
            )

        def capture(self, target):
            return next(self.snapshots)

    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.resolver.LambdaResourceAdapter",
        FakeLambdaAdapter,
    )

    class MockExperiment:
        id = "lambda-memory"
        service = "lambda"
        name = "Lambda Memory Chaos"
        json_file = "lambda-memory-chaos.json"
        engine = "Chaos Toolkit"
        variables: ClassVar[dict[str, object]] = {
            "lambda_name": "test-function",
            "aws_region": "ap-south-1",
            "target_memory_size": 1024,
            "wait_seconds": 1,
        }
        status = "Pending"
        error_message = None

    class MockRunner:
        def execute(self, experiment):
            experiment.status = "SUCCESS"

    class MockEvidenceWriter:
        def __init__(self):
            self.evidence_root = str(tmp_path)

        def write(self, evidence):
            execution_id = evidence["execution"]["execution_id"]
            execution_dir = tmp_path / execution_id
            execution_dir.mkdir(
                parents=True,
                exist_ok=True,
            )
            return str(execution_dir)

    class MockBundleWriter:
        def create_bundle(self, execution_id):
            return str(tmp_path / f"{execution_id}.zip")

    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceArtifactWriter",
        MockEvidenceWriter,
    )

    monkeypatch.setattr(
        "chaosforge.lifecycle.lifecycle_runner.EvidenceBundleWriter",
        MockBundleWriter,
    )

    lifecycle_runner = LifecycleRunner(
        runner=MockRunner(),
        check_resolver=__import__(
            "chaosforge.lifecycle.checks.resolver",
            fromlist=["CheckResolver"],
        ).CheckResolver(),
    )

    context = lifecycle_runner.execute(
        MockExperiment()
    )

    assert context.injection["passed"] is True

    assert context.precheck["enabled"] is True
    assert context.precheck["passed"] is True

    assert context.validation["enabled"] is True
    assert context.validation["phase"] == "post"
    assert context.state.value == "VALIDATION_PASSED"

    assert context.recovery["enabled"] is True
    assert context.recovery["passed"] is True

    assert context.result["success"] is True
    assert context.result["validation_available"] is True
