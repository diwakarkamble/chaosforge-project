"""Web presentation adapter for the shared lifecycle execution service."""

from chaosforge.application.services.lifecycle_execution import LifecycleExecutionService
from chaosforge.interfaces.web.log_manager import log_manager
from chaosforge.models.outcome import is_failure, is_warning_success
from chaosforge.reporting.report_generator import generate_report


class WebExperimentRunner:
    def __init__(self, lifecycle_service=None, logs=None, before_experiment=None, after_experiment=None):
        self.lifecycle_service = lifecycle_service or LifecycleExecutionService()
        self._logs = logs
        self.before_experiment = before_experiment
        self.after_experiment = after_experiment
        self.report_file = None

    @property
    def logs(self):
        return self._logs if self._logs is not None else log_manager

    def execute(self, experiment):
        result = self.lifecycle_service.execute_experiment(experiment)
        if is_failure(experiment.status):
            self.logs.append("Experiment Failed")
            if getattr(experiment, "error_message", ""):
                self.logs.append(f"Error: {experiment.error_message}")
        elif is_warning_success(experiment.status):
            self.logs.append("Experiment Completed With Warnings")
            for warning in getattr(experiment, "warnings", []):
                self.logs.append(f"Warning: {warning.get('label')}: {warning.get('detail')}")
        else:
            self.logs.append("Experiment Completed Successfully")
        return result

    def execute_campaign(self, campaign):
        total = len(campaign.experiments)
        self.logs.total = total
        self.logs.current = 0
        self.logs.current_experiment = "Preparing..."
        self.logs.append(f"Campaign Started ({total} experiment(s))")

        def before_experiment(index, _total, experiment):
            if self.before_experiment is not None:
                self.before_experiment(index, experiment)
            self.logs.current_experiment = experiment.name
            self.logs.append(f"Experiment {index}/{total}: {experiment.name}")

        def after_experiment(index, _total, experiment, _execution_result):
            self.logs.current = index
            self.logs.append(f"Result: {experiment.status}")
            if is_failure(experiment.status) and getattr(experiment, "error_message", ""):
                self.logs.append(f"Error: {experiment.error_message}")
            if self.after_experiment is not None:
                self.after_experiment(index, experiment)

        result = self.lifecycle_service.execute_campaign(
            campaign,
            before_experiment=before_experiment,
            after_experiment=after_experiment,
        )
        self.logs.current_experiment = f"Campaign {result.status}"
        self.logs.append(f"Campaign Finished: {result.status}")
        report_file = generate_report(campaign, show_summary=False)
        self.report_file = report_file
        self.logs.append("")
        self.logs.append("Mission Summary")
        self.logs.append(f"Campaign: {getattr(campaign, 'name', 'Current Campaign')}")
        self.logs.append(f"Experiments: {len(campaign.experiments)}")
        self.logs.append(f"Successful: {len(result.executed) - len(result.failed)}")
        self.logs.append(f"With Warnings: {len(getattr(result, 'warnings', []))}")
        self.logs.append(f"Failed: {len(result.failed)}")
        self.logs.append(f"Overall Result: {result.status}")
        self.logs.append(f"Report: {report_file}")
        return result
