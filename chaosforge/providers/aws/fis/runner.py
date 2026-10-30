"""Direct AWS SDK execution for native AWS FIS experiments."""

import os
import tempfile
import uuid

from chaosforge.models.execution import ExecutionContext, ExecutionState
from chaosforge.providers.aws.fis.actions import create_experiment, execute_management_action
from chaosforge.providers.aws.fis.component_actions import execute as execute_component_fis_action


class FISExperimentRunner:
    """Create, start, observe, and optionally delete AWS FIS templates via boto3."""

    def execute(self, experiment):
        variables = dict(experiment.variables)
        context = ExecutionContext(
            execution_id=str(uuid.uuid4()),
            experiment_id=experiment.id,
            service=experiment.service,
            experiment_name=experiment.name,
        )
        context.start()
        context.transition(ExecutionState.RUNNING)
        recovery_file = os.path.join(
            tempfile.gettempdir(), f"chaosforge-fis-recovery-{context.execution_id}.json"
        )
        variables["recovery_file"] = recovery_file
        experiment.variables["recovery_file"] = recovery_file

        try:
            if experiment.id == "fis-create-experiment":
                execute_component_fis_action(variables, create_experiment)
            else:
                execute_management_action(experiment.id, variables)
        except BaseException as exc:
            experiment.status = "FAILED"
            experiment.error_message = str(exc)
            context.errors.append(experiment.error_message)
            context.transition(ExecutionState.FAULT_INJECTION_FAILED)
        else:
            experiment.status = "SUCCESS"
            experiment.error_message = ""
            context.transition(ExecutionState.FAULT_INJECTION_SUCCEEDED)
        finally:
            if os.path.exists(recovery_file):
                os.remove(recovery_file)
            context.complete()

        experiment.cli_output = (
            f"Direct AWS FIS SDK execution: {experiment.status}\n"
            + (f"Error: {experiment.error_message}\n" if experiment.error_message else "")
        )
        return context
