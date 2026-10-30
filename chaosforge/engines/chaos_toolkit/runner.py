import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from chaoslib.exceptions import ChaosException
from chaoslib.experiment import ensure_experiment_is_valid, run_experiment
from chaoslib.loader import load_experiment
from chaoslib.run import Runner
from chaoslib.types import Strategy

from chaosforge.application.duration import (
    duration_seconds,
    is_iso8601_duration,
)
from chaosforge.application.duration import (
    execution_variables as normalize_duration_variables,
)
from chaosforge.common.paths import repository_paths
from chaosforge.interfaces.cli.interactive.ui.execution import (
    show_campaign_complete,
    show_campaign_start,
    show_experiment,
)
from chaosforge.models.execution import ExecutionContext, ExecutionState

PROJECT_ROOT = str(repository_paths().root)


def _fis_action_parameters(variables):
    from chaosforge.providers.aws.fis.catalog import FISCatalog

    experiment = FISCatalog().get_experiment(
        variables.get("service_id"),
        variables.get("experiment_id"),
    )

    if not experiment:
        return {}

    return {
        parameter["name"]: variables[parameter["name"]]
        for parameter in experiment.get("parameters", [])
        if parameter["name"] in variables
    }


def _run_library_experiment(definition, variables):
    """Run Toolkit definitions without signal registration in Web worker threads."""
    experiment_vars = (variables, None)
    if threading.current_thread() is threading.main_thread():
        return run_experiment(definition, experiment_vars=experiment_vars)

    # chaoslib.run.Runner.run wraps execution in exit_signals(), but Python only
    # permits signal handlers in the main interpreter thread. The Web interface
    # already runs campaigns in a worker thread, so execute the identical Runner
    # lifecycle directly without process-wide signal management.
    with Runner(Strategy.DEFAULT) as runner:
        runner.configure(definition, None, experiment_vars)
        return runner._run(
            runner.strategy,
            runner.schedule,
            definition,
            None,
            runner.config,
            runner.secrets,
            runner.settings,
            runner.event_registry,
        )


def _deviation_reason(journal):
    """
    Inspect a parsed chaostoolkit journal and return a human-readable reason
    if the run deviated (steady-state hypothesis genuinely failed and/or the
    method never executed), or None if the run genuinely completed as
    expected.

    ChaosToolkit exits with code 0 and reports "status": "completed" even
    when the *before* steady-state hypothesis fails and it safely rolls
    back without ever injecting the fault — a subprocess return code alone
    can't tell "SUCCESS" apart from "aborted, nothing was injected".

    Deliberately does NOT trust journal["deviated"] on its own: ChaosToolkit
    sets that flag whenever a method action raises mid-run, which skips the
    *after* steady-state re-check entirely — that's a "we couldn't
    re-confirm final health" signal, not proof the app is actually
    unhealthy. We only treat the after-hypothesis as a real failure when it
    genuinely ran and explicitly reported not-met.
    """
    before = (journal.get("steady_states") or {}).get("before") or {}
    after = (journal.get("steady_states") or {}).get("after") or {}

    if before.get("steady_state_met") is False:
        failed_probes = [
            p["activity"]["name"]
            for p in before.get("probes", [])
            if p.get("tolerance_met") is False
        ]
        probe_names = ", ".join(failed_probes) or "steady-state probe"
        return (
            f"Steady-state check failed before the fault could be injected "
            f"({probe_names}) — experiment was rolled back, no chaos occurred."
        )

    if not journal.get("run") and before.get("steady_state_met") is not True:
        return "Experiment ended without executing its method — no chaos occurred."

    if after.get("steady_state_met") is False:
        failed_probes = [
            p["activity"]["name"]
            for p in after.get("probes", [])
            if p.get("tolerance_met") is False
        ]
        probe_names = ", ".join(failed_probes) or "steady-state probe"
        return (
            f"Steady-state hypothesis failed after the experiment ran "
            f"({probe_names}) — the target may not have fully recovered."
        )

    def _is_post_check_only_failure(exception_lines):
        """
        Return True if a failed rollback activity's recorded exception is
        solely our own diagnostic RuntimeError('Post-experiment checks
        failed: [...]') — raised by cleanup_experiment() after it already
        completed the real cleanup (removing the NetworkChaos/PodChaos CR,
        etc.) — rather than a genuine cleanup/rollback failure (e.g. the
        kubectl delete itself erroring out). chaoslib records the traceback
        as a list of strings in rb["exception"]; the exception message we
        raise always contains this exact phrase (see azure_aks_actions.py).
        """
        text = "".join(exception_lines or []).lower()
        return "post-experiment checks failed" in text

    failed_rollbacks = [
        rb["activity"]["name"] for rb in journal.get("rollbacks", [])
        if rb.get("status") == "failed"
        and not _is_post_check_only_failure(rb.get("exception"))
    ]
    if failed_rollbacks:
        return (
            f"Rollback step(s) failed: {', '.join(failed_rollbacks)} — the "
            "target may not have fully recovered. Check the journal for details."
        )

    return None


def _journal_has_failed_action(journal):
    """Return whether a completed journal contains a genuine action failure."""
    for activity in journal.get("run", []):
        if activity.get("status") == "failed":
            return True

    for rollback in journal.get("rollbacks", []):
        if rollback.get("status") != "failed":
            continue
        exception_text = "".join(rollback.get("exception") or []).lower()
        if "post-experiment checks failed" not in exception_text:
            return True

    return False


def _journal_failure_detail(journal):
    """Return the first actionable failure recorded by Chaos Toolkit."""
    for phase in ("run", "rollbacks"):
        for activity in journal.get(phase, []):
            if activity.get("status") != "failed":
                continue
            name = activity.get("activity", {}).get("name", "unnamed action")
            detail = "".join(activity.get("exception") or []).strip().splitlines()
            return f"{name}: {detail[-1] if detail else 'failed without an exception detail'}"
    return ""


def _journal_rollback_completed(journal):
    """Return whether Chaos Toolkit recorded successful rollback activity."""
    rollbacks = journal.get("rollbacks", []) if journal else []
    return bool(rollbacks) and all(
        rollback.get("status") == "succeeded" for rollback in rollbacks
    )


def _append_interrupt_log(lines, message):
    line = f"[ChaosForge interrupt recovery] {message}"
    lines.append(line + "\n")
    print(line)


def _attempt_direct_recovery(experiment, lines):
    """Run a provider fallback when the child could not confirm rollback."""
    engine = getattr(experiment, "engine", "")
    variables = dict(getattr(experiment, "variables", {}) or {})

    if engine == "Azure Chaos Studio" and getattr(experiment, "service", "") != "azure_redis":
        from chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor import (
            cleanup_experiment,
        )

        cleanup_keys = {
            "experiment_id", "aks_context", "namespace", "deployment",
            "chaos_mode", "chaos_value", "container_name", "dns_pattern",
            "volume_path", "http_port", "subscription_id", "resource_group",
            "aks_name", "target_node", "label_key", "label_val", "duration",
            "dry_run", "latency", "jitter", "correlation", "loss_percentage",
            "rate", "corrupt_percentage", "duplicate_percentage", "io_delay",
            "io_errno", "io_percent",
        }
        cleanup_experiment(**{
            key: value for key, value in variables.items() if key in cleanup_keys
        })
        _append_interrupt_log(lines, "AKS cleanup completed successfully.")
        return True

    if engine == "AWS FIS":
        from chaosforge.providers.aws.fis.actions import recover_interrupted_experiment

        result = recover_interrupted_experiment(
            variables.get("recovery_file", ""),
            variables.get("aws_region") or variables.get("region"),
        )
        for message in result["messages"]:
            _append_interrupt_log(lines, message)
        return result["success"]

    _append_interrupt_log(
        lines,
        "No provider fallback is available; rely on the Chaos Toolkit rollback log.",
    )
    return False


def _journal_output(journal):
    """Render the library journal into the concise transcript used by reports."""
    lines = []
    for activity in journal.get("run", []):
        name = activity.get("activity", {}).get("name", "unnamed action")
        lines.append(f"Action {name}: {activity.get('status', 'unknown')}\n")
    for rollback in journal.get("rollbacks", []):
        name = rollback.get("activity", {}).get("name", "unnamed rollback")
        lines.append(f"Rollback {name}: {rollback.get('status', 'unknown')}\n")
    return lines


class ExperimentRunner:
    def execute(self, experiment):

        execution_id = str(uuid.uuid4())
        # Chaos Toolkit consumes configuration while resolving an experiment.
        # Keep the campaign model immutable across runs so CLI and Web can run
        # the same configured experiment more than once.
        execution_variables = normalize_duration_variables(experiment.variables)
        if (
            getattr(experiment, "service", "") == "aks"
            and is_iso8601_duration(execution_variables.get("duration", ""))
        ):
            execution_variables["duration"] = duration_seconds(
                execution_variables["duration"]
            )

        context = ExecutionContext(
            execution_id=execution_id,
            experiment_id=experiment.id,
            service=experiment.service,
            experiment_name=experiment.name,
        )

        context.transition(ExecutionState.PLANNED)

        context.start()
        context.transition(ExecutionState.RUNNING)

        if getattr(experiment, "engine", "") == "AWS FIS":
            action_parameters = _fis_action_parameters(execution_variables)

            if action_parameters:
                execution_variables["fis_action_parameters_json"] = json.dumps(
                    action_parameters, separators=(",", ":")
                )

        recovery_file = None
        if getattr(experiment, "engine", "") == "AWS FIS":
            recovery_file = os.path.join(
                tempfile.gettempdir(),
                f"chaosforge-fis-recovery-{execution_id}.json",
            )
            execution_variables["recovery_file"] = recovery_file
            # Direct interrupt recovery uses the file path after Toolkit returns.
            experiment.variables["recovery_file"] = recovery_file

        dry_run_tag = " (DRY RUN)" if str(execution_variables.get("dry_run", "")).lower() == "true" else ""
        header = (
            "\n" + "=" * 70 + "\n"
            f"Execution ID : {execution_id}\n"
            f"Executing    : {experiment.service} - {experiment.name}{dry_run_tag}\n"
            f"State        : {context.state.value}\n"
            + "=" * 70 + "\n"
            + "Executing through Chaos Toolkit library\n"
        )
        captured_lines = [header]
        try:
            definition = load_experiment(experiment.json_file)
            ensure_experiment_is_valid(definition)
            journal = _run_library_experiment(definition, execution_variables)
            captured_lines.extend(_journal_output(journal))
        except KeyboardInterrupt:
            journal = {"status": "interrupted", "interrupted": True, "rollbacks": []}
        except (ChaosException, OSError) as exc:
            journal = {"status": "failed", "error": str(exc), "run": [], "rollbacks": []}
            captured_lines.append(f"Chaos Toolkit error: {exc}\n")

        if journal.get("interrupted"):
            recovery_succeeded = _journal_rollback_completed(journal)
            if recovery_succeeded:
                _append_interrupt_log(captured_lines, "Chaos Toolkit completed all configured rollback actions.")
            else:
                _append_interrupt_log(captured_lines, "Configured rollback was not confirmed; attempting provider cleanup.")
                try:
                    recovery_succeeded = _attempt_direct_recovery(experiment, captured_lines)
                except Exception as exc:  # noqa: BLE001
                    _append_interrupt_log(captured_lines, f"Provider cleanup failed: {exc}")

            experiment.cli_output = "".join(captured_lines)
            recovery_status = "succeeded" if recovery_succeeded else "could not be confirmed"
            error_message = (
                f"Execution interrupted by user; recovery {recovery_status}."
            )
            context.errors.append(error_message)
            context.recovery = {
                "enabled": True,
                "passed": recovery_succeeded,
                "phase": "interrupt",
                "message": error_message,
            }
            context.transition(
                ExecutionState.ABORTED_BY_USER
                if recovery_succeeded
                else ExecutionState.CLEANUP_FAILED
            )
            experiment.status = "FAILED"
            experiment.error_message = error_message
            context.complete()

            if recovery_file and os.path.exists(recovery_file):
                os.remove(recovery_file)

            print(f"\nExecution state: {context.state.value}")
            print(error_message)
            return context

        if recovery_file and os.path.exists(recovery_file):
            os.remove(recovery_file)

        experiment.cli_output = "".join(captured_lines)
        action_failed = (
            _journal_has_failed_action(journal)
            if journal is not None
            else self._contains_failed_action(experiment.cli_output)
        )
        reason = (
            _deviation_reason(journal)
            if journal.get("status") == "completed"
            else None
        )

        if reason:
            context.transition(ExecutionState.FAULT_INJECTION_FAILED)
            experiment.status = "FAILED"
            experiment.error_message = reason
            context.errors.append(reason)

        elif action_failed:
            context.transition(ExecutionState.FAULT_INJECTION_FAILED)
            detail = _journal_failure_detail(journal)
            failure_message = (
                "Chaos Toolkit completed with one or more failed "
                "experiment actions."
            )
            if detail:
                failure_message = f"{failure_message} {detail}"
            experiment.status = "FAILED"
            experiment.error_message = failure_message
            context.errors.append(failure_message)
            print(f"Chaos Toolkit failure: {failure_message}")

        elif journal.get("status") == "completed":
            context.transition(ExecutionState.FAULT_INJECTION_SUCCEEDED)
            experiment.status = "SUCCESS"
            experiment.error_message = ""

        else:
            error_message = journal.get("error") or "Chaos Toolkit execution failed"

            context.errors.append(error_message)

            context.transition(ExecutionState.FAULT_INJECTION_FAILED)

            experiment.status = "FAILED"
            experiment.error_message = error_message
            print(f"Chaos Toolkit failure: {error_message}")

        context.complete()

        print(f"\nExecution state: {context.state.value}")

        if context.started_at and context.completed_at:
            duration = (
                context.completed_at - context.started_at
            ).total_seconds()

            print(f"Execution duration: {duration:.2f}s")

        return context

    @staticmethod
    def _contains_failed_action(output):
        """
        Chaos Toolkit may exit with code 0 even when one or more
        experiment actions fail.

        Detect explicit action failures from Chaos Toolkit output — except
        post-experiment check failures. Those are diagnostic/observability
        findings surfaced for visibility (which specific check(s) failed
        stays visible in the captured CLI output either way) — they don't
        mean the experiment itself (fault injection + rollback) failed, so
        they no longer force the overall execution status to FAILED. Any
        other action failure (setup, injection, a genuinely failed
        rollback step, etc.) is still treated as a real failure.
        """

        for line in output.splitlines():
            normalized = line.lower().strip()

            if "=> failed:" not in normalized:
                continue
            if "post-experiment checks failed" in normalized:
                continue

            return True

        return False

    def execute_campaign(self, campaign):
        campaign.start_time = datetime.now(timezone.utc)

        show_campaign_start(campaign)

        total = len(campaign.experiments)

        continue_on_failure = getattr(
            campaign,
            "continue_on_failure",
            False,
        )

        for index, experiment in enumerate(
            campaign.experiments,
            start=1,
        ):
            show_experiment(
                index,
                total,
                experiment,
            )

            self.execute(experiment)

            if (
                experiment.status == "FAILED"
                and not continue_on_failure
            ):
                print(
                    "\nCampaign stopped because "
                    "continue_on_failure is False."
                )
                break

        campaign.end_time = datetime.now(timezone.utc)

        campaign.duration = (
            campaign.end_time - campaign.start_time
        ).total_seconds()

        show_campaign_complete(campaign)
