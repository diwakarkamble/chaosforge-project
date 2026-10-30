import uuid
from contextlib import nullcontext

from chaosforge.application.metadata import get_experiment
from chaosforge.application.services.experiment_validation import (
    ExperimentValidationService,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_models import ChaosMeshExecutionResult
from chaosforge.engines.chaos_mesh.target_contract import is_workload_experiment
from chaosforge.lifecycle.evidence import EvidenceBuilder
from chaosforge.lifecycle.execution_dispatcher import ExecutionDispatcher
from chaosforge.lifecycle.lifecycle import LifecycleCoordinator
from chaosforge.lifecycle.lifecycle_report import LifecycleReportRenderer
from chaosforge.models.execution import ExecutionContext
from chaosforge.models.outcome import ExperimentOutcome, is_success
from chaosforge.storage.evidence_artifact import EvidenceArtifactWriter
from chaosforge.storage.evidence_bundle import EvidenceBundleWriter


class LifecycleRunner:
    """
    Lifecycle-aware wrapper around the existing ExperimentRunner.

    This class adds lifecycle management without replacing the
    existing experiment execution engine.

    The existing ExperimentRunner remains responsible for
    executing Chaos Toolkit.
    """

    def __init__(
        self,
        runner,
        check_resolver,
        discovery=None,
        dispatcher=None,
    ):
        self.report_renderer = LifecycleReportRenderer()
        self.runner = runner
        self.check_resolver = check_resolver
        self.discovery = discovery
        self.dispatcher = dispatcher or ExecutionDispatcher(
            chaos_toolkit_runner=self.runner,
            discovery=self.discovery,
        )

    def execute(self, experiment):
        """
        Execute one experiment through the lifecycle.

        The lifecycle is:

            PLANNED
                ↓
            PRECHECK
                ↓
            BASELINE
                ↓
            RUNNING
                ↓
            FAULT INJECTION
                ↓
            VALIDATION
                ↓
            RECOVERY
                ↓
            COMPLETE

        If no lifecycle check is available for the experiment,
        execution still passes through the common lifecycle,
        with validation marked as unavailable.
        """

        check = self.check_resolver.resolve(
            experiment,
            self.discovery,
        )


        execution_id = str(uuid.uuid4())

        lifecycle = LifecycleCoordinator(check)
        evidence_builder = EvidenceBuilder()
        evidence_writer = EvidenceArtifactWriter()
        bundle_writer = EvidenceBundleWriter()

        context = lifecycle.create_context(
            execution_id=execution_id,
            experiment_id=experiment.id,
            service=experiment.service,
            experiment_name=experiment.name,
        )

        print("\n" + "=" * 70)
        print("ChaosForge Lifecycle Execution")
        print("=" * 70)
        print(f"Execution ID : {execution_id}")
        print(f"Experiment   : {experiment.id}")
        print(f"Service      : {experiment.service}")
        print(f"State        : {context.state.value}")
        print("=" * 70)

        target = self._build_target(experiment)
        is_eks_workload = (
            experiment.service == "chaos_mesh"
            and is_workload_experiment(experiment.id)
            and target.get("eks_cluster")
        )
        phase_ui = None
        if is_eks_workload:
            from chaosforge.interfaces.cli.interactive.phase_ui import PhaseUI

            phase_ui = PhaseUI(experiment.id)

        context.target = {
            "resolved": dict(target),
        }

        metadata = get_experiment(experiment.service, experiment.id)
        validation = (
            ExperimentValidationService().validate_experiment(experiment)
            if metadata is not None
            else {"valid": True}
        )
        if not validation["valid"]:
            error_message = "; ".join(validation["errors"])
            experiment.status = "FAILED"
            experiment.error_message = error_message
            lifecycle.mark_injection_failed(context, error_message)
            context.injection = {
                "passed": False,
                "success": False,
                "experiment_status": experiment.status,
                "engine": getattr(experiment, "engine", None),
                "check": experiment.name,
                "display": self._build_execution_display(check, target),
                "error": error_message,
            }
            return self._complete_with_evidence(
                lifecycle,
                context,
                experiment,
                evidence_builder,
                evidence_writer,
                bundle_writer,
            )

        if phase_ui is not None:
            with phase_ui.phase("setup") as ui:
                ui.step(f"Resolving EKS cluster: {target['eks_cluster']}")
                ui.step(f"Target namespace: {target['namespace']}")
                ui.step(
                    f"Target: {target.get('pod') or target.get('deployment')} "
                    f"({target.get('target_mode', 'deployment')})"
                )
                ui.step("Validating workload readiness before fault injection")
        precheck_phase = phase_ui.phase("pre-check") if phase_ui is not None else nullcontext()
        with precheck_phase:
            precheck_passed = lifecycle.run_precheck(context, target)
        if not precheck_passed:
            experiment.status = "FAILED"
            precheck_error = context.precheck.get("error")
            experiment.error_message = (
                precheck_error
                if isinstance(precheck_error, str) and precheck_error
                else "Experiment precheck failed."
            )

            return self._complete_with_evidence(
                lifecycle,
                context,
                experiment,
                evidence_builder,
                evidence_writer,
                bundle_writer,
            )


        lifecycle.mark_running(context)

        try:
            observer = check if hasattr(check, "observe_during") else None
            if phase_ui is not None:
                with phase_ui.phase("experiment-setup") as ui:
                    ui.step("Validating the selected workload selector")
                    ui.step("Building the direct Chaos Mesh custom resource")
                with phase_ui.phase("experiment") as ui:
                    ui.step("Creating the Chaos Mesh resource and waiting for fault observation")
                    execution_result = self.dispatcher.execute(experiment, observer=observer)
                    if (
                        isinstance(execution_result, ChaosMeshExecutionResult)
                        and not execution_result.success
                    ):
                        raise RuntimeError(
                            execution_result.error or "Direct Chaos Mesh PodChaos execution failed."
                        )
                    ui.step("Fault observation completed")
                with phase_ui.phase("rollback") as ui:
                    ui.step("Chaos Mesh resource cleanup confirmed")
            elif observer is None:
                execution_result = self.dispatcher.execute(experiment)
            else:
                execution_result = self.dispatcher.execute(experiment, observer=observer)

            if isinstance(execution_result, ExecutionContext):
                context.recovery = dict(execution_result.recovery)
                context.logs.extend(execution_result.logs)

            if isinstance(
                execution_result,
                ChaosMeshExecutionResult,
            ):
                experiment.status = (
                    "SUCCESS"
                    if execution_result.success
                    else "FAILED"
                )

                experiment.error_message = (
                    execution_result.error
                    or ""
                )
                context.observability["chaos_mesh"] = {
                    "manifest": execution_result.manifest,
                    "during_fault": execution_result.validation,
                    "cleanup": execution_result.cleanup,
                }
                context.events.extend(
                    execution_result.validation.get("samples", [])
                )

        except BaseException as exc:
            # Engines must be allowed to finish their provider-specific
            # rollback before an interrupt leaves this common lifecycle.
            error_message = str(exc) or f"{type(exc).__name__} interrupted execution"

            lifecycle.mark_injection_failed(
                context,
                error_message,
            )

            experiment.status = "FAILED"
            experiment.error_message = error_message
            context.injection = {
                "passed": False,
                "success": False,
                "experiment_status": experiment.status,
                "engine": getattr(experiment, "engine", None),
                "check": experiment.name,
                "display": self._build_execution_display(
                    check,
                    target,
                ),
                "error": error_message,
            }

            return self._complete_with_evidence(
                lifecycle,
                context,
                experiment,
                evidence_builder,
                evidence_writer,
                bundle_writer,
            )

        if is_success(experiment.status):

            lifecycle.mark_injection_succeeded(
                context,
            )

            context.injection = {
                "passed": True,
                "success": True,
                "experiment_status": experiment.status,
                "engine": getattr(experiment, "engine", None),
                "check": experiment.name,
                "display": self._build_execution_display(
                    check,
                    target,
                ),
            }

            if str(experiment.variables.get("dry_run", "")).lower() == "true":
                context.validation = {
                    "enabled": False,
                    "passed": True,
                    "message": "Dry run preview only; post-validation was not run.",
                }
                return self._complete_with_evidence(
                    lifecycle, context, experiment, evidence_builder, evidence_writer, bundle_writer
                )

        else:

            error_message = getattr(
                experiment,
                "error_message",
                "Chaos experiment failed.",
            )

            lifecycle.mark_injection_failed(
                context,
                error_message,
            )

            context.injection = {
                "passed": False,
                "success": False,
                "experiment_status": experiment.status,
                "engine": getattr(experiment, "engine", None),
                "check": experiment.name,
                "display": self._build_execution_display(
                    check,
                    target,
                ),
                "error": error_message,
            }

            return self._complete_with_evidence(
                lifecycle,
                context,
                experiment,
                evidence_builder,
                evidence_writer,
                bundle_writer,
            )

        post_phase = phase_ui.phase("post-check") if phase_ui is not None else nullcontext()
        with post_phase:
            post_validation_passed = lifecycle.validate(
                context,
                target,
                phase="post",
            )

        recovery_passed = lifecycle.validate_recovery(
            context,
            target,
        )

        if not post_validation_passed or not recovery_passed:
            experiment.status = "FAILED"
            if not getattr(experiment, "error_message", ""):
                if not post_validation_passed:
                    experiment.error_message = "Post-execution validation failed."
                else:
                    experiment.error_message = "Recovery validation failed."
        elif context.warnings:
            experiment.status = ExperimentOutcome.SUCCESS_WITH_WARNINGS.value
            experiment.warnings = list(context.warnings)

        return self._complete_with_evidence(
            lifecycle,
            context,
            experiment,
            evidence_builder,
            evidence_writer,
            bundle_writer,
        )




    def _render_lifecycle_report(self, context):
        """
        Render the client-facing lifecycle validation report.

        This is presentation-only. It does not modify lifecycle state,
        execution behavior, validation, or recovery.
        """

        precheck = getattr(context, "precheck", {}) or {}
        injection = getattr(context, "injection", {}) or {}
        validation = getattr(context, "validation", {}) or {}

        validation_result = validation.get("result", {})
        if not isinstance(validation_result, dict):
            validation_result = {}

        report_precheck = {
            "enabled": precheck.get("enabled", False),
            "check": precheck.get("check", "-"),
            "resource": self._format_resource(
                context.target.get("resolved", {})
            ),
            "baseline": "Captured",
            "passed": precheck.get("passed"),
            "error": precheck.get("error"),
        }

        report_injection = {
            "check": injection.get(
                "check",
                getattr(context, "experiment_name", None)
                or context.experiment_id,
            ),
            "success": injection.get("passed"),
            "display": injection.get("display", {}),
        }

        report_validation = {
            "enabled": validation.get("enabled", False),
            "check": validation.get("check", "-"),
            "passed": validation_result.get("passed"),
            "display": validation_result.get("display", {}),
            "warnings": validation_result.get("warnings", []),
        }

        report = self.report_renderer.render(
            precheck=report_precheck,
            injection=report_injection,
            validation=report_validation,
        )

        print("\n" + report)

    @staticmethod
    def _format_resource(target):
        """
        Format the resolved lifecycle target for client-facing output.
        """

        if not target:
            return "-"

        preferred_keys = (
            "lambda_name",
            "pod_name",
            "pod",
            "deployment_name",
                "eks_cluster",
                "redis_name",
            "physical_machine",
        )

        for key in preferred_keys:
            value = target.get(key)
            if value:
                return str(value)

        for key, value in target.items():
            if value and key not in {
                "aws_region",
                "namespace",
                "mode",
                "duration",
            }:
                return str(value)

        return "-"

    @staticmethod
    def _build_execution_display(check, target):
        if check is None:
            return {}

        builder = getattr(
            check,
            "build_execution_display",
            None,
        )

        if builder is None:
            return {}

        try:
            return builder(target)
        except Exception:  # noqa: BLE001
            return {}

    def _complete_with_evidence(
        self,
        lifecycle,
        context,
        experiment,
        evidence_builder,
        evidence_writer,
        bundle_writer,
    ):
        """
        Complete the lifecycle, build evidence, persist the evidence
        files, and create the ZIP evidence bundle.

        This method is used by every terminal execution path.
        """

        lifecycle.complete(context)

        cli_output = getattr(experiment, "cli_output", "")
        if isinstance(cli_output, str) and cli_output and cli_output not in context.logs:
            context.logs.append(cli_output)

        validation = getattr(
            context,
            "validation",
            {},
        )

        if isinstance(validation, dict):
            lifecycle_validation_enabled = (
                validation.get("enabled") is True
            )
        else:
            lifecycle_validation_enabled = False

        if lifecycle_validation_enabled:
            validation_result = validation.get("result", {})
            validation_passed = (
                validation_result.get("passed")
                if isinstance(validation_result, dict)
                else validation.get("passed")
            )
            recovery = getattr(context, "recovery", {})
            recovery_enabled = isinstance(recovery, dict) and recovery.get("enabled") is True
            recovery_result = recovery.get("result", {}) if isinstance(recovery, dict) else {}
            recovery_passed = (
                recovery_result.get("passed")
                if isinstance(recovery_result, dict)
                else recovery.get("passed") if isinstance(recovery, dict) else False
            )
            success = bool(validation_passed) and (
                not recovery_enabled or bool(recovery_passed)
            )
        else:
            injection = getattr(
                context,
                "injection",
                {},
            )

            errors = getattr(
                context,
                "errors",
                [],
            )

            success = (
                isinstance(injection, dict)
                and injection.get("passed") is True
                and not errors
            )

        outcome = (
            ExperimentOutcome.SUCCESS_WITH_WARNINGS
            if success and context.warnings
            else ExperimentOutcome.SUCCESS if success else ExperimentOutcome.FAILED
        )
        context.result = {
            "execution_id": context.execution_id,
            "experiment_id": context.experiment_id,
            "state": context.state.value,
            "success": success,
            "outcome": outcome.value,
            "warnings": list(context.warnings),
            "validation_available": lifecycle_validation_enabled,
            "errors": list(context.errors),
        }

        failure_details = self._failure_details(context, experiment)
        if failure_details:
            print("\nFailure details:")
            for detail in failure_details:
                print(f"  - {detail}")

        context.evidence = evidence_builder.build(
            context,
            experiment,
        )

        evidence_directory = evidence_writer.write(
            context.evidence,
        )

        evidence_bundle = bundle_writer.create_bundle(
            context.execution_id,
        )

        self._render_lifecycle_report(context)

        print(
            f"\nFinal execution state: "
            f"{context.state.value}"
        )

        print(
            f"Evidence generated for execution: "
            f"{context.execution_id}"
        )

        print(
            f"Evidence directory: "
            f"{evidence_directory}"
        )

        print(
            f"Evidence bundle: "
            f"{evidence_bundle}"
        )

        return context

    @staticmethod
    def _failure_details(context, experiment):
        """Collect distinct actionable failures for console, evidence, and reports."""

        details = []
        for value in (
            getattr(experiment, "error_message", ""),
            (getattr(context, "injection", {}) or {}).get("error"),
            (getattr(context, "precheck", {}) or {}).get("error"),
            (getattr(context, "validation", {}) or {}).get("error"),
            (getattr(context, "recovery", {}) or {}).get("error"),
            *getattr(context, "errors", []),
        ):
            detail = str(value or "").strip()
            if detail and detail not in details:
                details.append(detail)
        return details


    @staticmethod
    def _build_target(experiment):
        """
        Build the lifecycle target from experiment variables.

        The target structure is intentionally generic so that
        future lifecycle checks can consume their own target
        definitions without changing the runner.
        """

        target = dict(experiment.variables)
        target_arn = str(target.get("target_arn") or "").strip()

        if (
            target.get("service_id") == "ec2"
            and target_arn
            and not target.get("instance_ids")
        ):
            instance_id = target_arn.rsplit("/", 1)[-1]

            if instance_id.startswith("i-"):
                target["instance_ids"] = [instance_id]

        if target.get("service_id") == "lambda" and target_arn:
            target["lambda_name"] = target_arn.rsplit(":function:", 1)[-1]

        if target.get("service_id") == "eks" and target.get("experiment_id") == "pod-delete":
            target["target_mode"] = "pod"

        if (
            getattr(experiment, "id", "") == "chaos-mesh-pod-kill"
            and target.get("eks_cluster")
            and target.get("pod")
        ):
            from chaosforge.providers.aws.discovery import AWSDiscovery

            discovery = AWSDiscovery(target.get("aws_region", "eu-central-1"))
            target.update(
                discovery.get_eks_pod_context(
                    target["eks_cluster"], target["namespace"], target["pod"]
                )
            )
            target["target_mode"] = "pod"
            experiment.variables.update(target)

        return target
