"""Shared lifecycle composition for CLI, YAML, and Web campaigns."""

from chaosforge.application.services.campaign_executor import CampaignExecutor
from chaosforge.engines.chaos_toolkit.runner import ExperimentRunner
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.lifecycle.execution_dispatcher import ExecutionDispatcher
from chaosforge.lifecycle.lifecycle_runner import LifecycleRunner
from chaosforge.providers.aws.discovery import AWSDiscovery


class LifecycleExecutionService:
    def __init__(self, toolkit_runner=None, check_resolver=None):
        self.toolkit_runner = toolkit_runner or ExperimentRunner()
        self.check_resolver = check_resolver or CheckResolver()

    def create_runner(self, experiment):
        region = experiment.variables.get("aws_region")
        discovery = AWSDiscovery(region) if region else None
        dispatcher = ExecutionDispatcher(
            chaos_toolkit_runner=self.toolkit_runner,
            discovery=discovery,
        )
        return LifecycleRunner(
            runner=self.toolkit_runner,
            check_resolver=self.check_resolver,
            discovery=discovery,
            dispatcher=dispatcher,
        )

    def execute_experiment(self, experiment):
        if getattr(experiment, "service", "") == "aks" and hasattr(
            experiment, "chaos_mesh_version_action"
        ):
            experiment.variables["chaos_mesh_version_action"] = (
                experiment.chaos_mesh_version_action
            )
            experiment.variables["chaos_mesh_installed_version"] = getattr(
                experiment, "chaos_mesh_installed_version", ""
            )
        return self.create_runner(experiment).execute(experiment)

    def execute_campaign(
        self,
        campaign,
        *,
        before_experiment=None,
        after_experiment=None,
    ):
        return CampaignExecutor().execute(
            campaign,
            self.execute_experiment,
            before_experiment=before_experiment,
            after_experiment=after_experiment,
        )
