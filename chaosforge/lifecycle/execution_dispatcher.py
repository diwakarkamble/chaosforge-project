from chaosforge.engines.chaos_mesh.chaos_mesh_execution_gate import (
    ChaosMeshExecutionGate,
)
from chaosforge.engines.chaos_mesh.chaos_mesh_runner import ChaosMeshRunner
from chaosforge.engines.chaos_toolkit.runner import ExperimentRunner
from chaosforge.providers.aws.fis.runner import FISExperimentRunner


class ExecutionDispatcher:
    CHAOS_TOOLKIT = "Chaos Toolkit"
    AWS_FIS = "AWS FIS"
    CHAOS_MESH = "Chaos Mesh"
    AZURE_CHAOS_STUDIO = "Azure Chaos Studio"
    AZURE_SDK = "Azure SDK"

    def __init__(
        self,
        chaos_toolkit_runner=None,
        fis_runner=None,
        chaos_mesh_runner=None,
        discovery=None,
        chaos_mesh_execution_gate=None,
    ):
        self.chaos_toolkit_runner = (
            chaos_toolkit_runner or ExperimentRunner()
        )

        self.fis_runner = fis_runner or FISExperimentRunner()

        self.chaos_mesh_runner = (
            chaos_mesh_runner
            or ChaosMeshRunner(discovery=discovery)
        )

        self.chaos_mesh_execution_gate = (
            chaos_mesh_execution_gate
            or ChaosMeshExecutionGate(
                discovery=discovery,
            )
        )

    def execute(self, experiment, observer=None):
        engine = (
            getattr(experiment, "engine", None)
            or self.CHAOS_TOOLKIT
        )

        if engine == self.CHAOS_TOOLKIT:
            return self.chaos_toolkit_runner.execute(experiment)

        if (
            engine == self.AZURE_CHAOS_STUDIO
            and getattr(experiment, "service", "") == "azure_redis"
            and getattr(experiment, "id", "") == "azure-redis-reboot"
        ):
            return self._execute_azure_redis_reboot(experiment)

        if engine == self.AZURE_CHAOS_STUDIO and getattr(experiment, "service", "").startswith("azure_"):
            return self._execute_azure_classic(experiment)

        # AKS remains an Azure Chaos Studio engine. Its provider-owned workflow
        # definition is executed by the shared definition runner before the
        # Azure Studio action starts; it is not a Toolkit experiment category.
        if engine in {self.AZURE_CHAOS_STUDIO, self.AZURE_SDK}:
            return self.chaos_toolkit_runner.execute(experiment)

        if engine == self.AWS_FIS:
            return self._execute_fis(experiment)

        if engine == self.CHAOS_MESH:
            return self._execute_chaos_mesh(experiment, observer=observer)

        raise ValueError(
            f"Unsupported execution engine: {engine}. "
            f"Supported engines: "
            f"{self.CHAOS_TOOLKIT}, "
            f"{self.AWS_FIS}, "
            f"{self.CHAOS_MESH}, "
            f"{self.AZURE_CHAOS_STUDIO}."
        )

    def _execute_fis(self, experiment):
        if self.fis_runner is None:
            raise RuntimeError(
                "AWS FIS execution engine is not configured."
            )

        return self.fis_runner.execute(experiment)

    def _execute_chaos_mesh(self, experiment, observer=None):
        if self.chaos_mesh_runner is None:
            raise RuntimeError(
                "Chaos Mesh execution engine is not configured."
            )

        self.chaos_mesh_execution_gate.ensure_ready(experiment)

        if observer is None:
            return self.chaos_mesh_runner.execute(experiment)
        return self.chaos_mesh_runner.execute(experiment, observer=observer)

    @staticmethod
    def _execute_azure_redis_reboot(experiment):
        from azure.identity import DefaultAzureCredential

        from chaosforge.providers.azure.components.azure_redis.chaos_identity import (
            AzureRedisChaosIdentityService,
            redis_target_id,
        )
        from chaosforge.providers.azure.components.azure_redis.experiments.chaos_studio.actions.redis_reboot import (
            run_experiment,
        )

        variables = experiment.variables
        target_id = redis_target_id(
            variables["subscription_id"], variables["resource_group"], variables["redis_name"]
        )
        readiness = AzureRedisChaosIdentityService(
            variables["subscription_id"], DefaultAzureCredential()
        ).readiness(variables["chaos_identity_id"], target_id)
        if readiness["status"] != "ready":
            raise RuntimeError(readiness.get("message", "Azure Redis chaos identity is not ready."))
        result = run_experiment(
            subscription_id=variables["subscription_id"],
            resource_group=variables["resource_group"],
            redis_name=variables["redis_name"],
            chaos_identity_id=variables["chaos_identity_id"],
            reboot_type=variables.get("reboot_type", "AllNodes"),
            shard_id=variables.get("shard_id", 0),
        )
        experiment.status = "SUCCESS"
        return result

    @staticmethod
    def _execute_azure_classic(experiment):
        from azure.identity import DefaultAzureCredential

        from chaosforge.providers.azure.chaos_studio.classic import (
            AzureChaosIdentityService,
            run_service_direct_classic_experiment,
        )
        from chaosforge.providers.azure.chaos_studio.classic_faults import (
            action_parameters,
            fault_details,
        )

        capability_urn, selector_target, role_name = fault_details(experiment.service, experiment.id)
        variables = experiment.variables
        readiness = AzureChaosIdentityService(
            variables["subscription_id"], DefaultAzureCredential()
        ).readiness(
            variables["chaos_identity_id"], variables["resource_id"], role_name
        )
        if readiness["status"] != "ready":
            raise RuntimeError(readiness.get("message", "Azure Chaos identity is not ready."))

        completion_check = None

        if experiment.id == "azure-cosmos-db-failover":
            from azure.identity import DefaultAzureCredential
            from azure.mgmt.cosmosdb import CosmosDBManagementClient

            account_name = (
                variables["resource_id"]
                .rstrip("/")
                .rsplit("/", 1)[-1]
            )

            requested_region = variables["read_region"].casefold()

            client = CosmosDBManagementClient(
                DefaultAzureCredential(),
                variables["subscription_id"],
            )

            def requested_region_priority():
                account = client.database_accounts.get(
                    variables["resource_group"],
                    account_name,
                )

                return next(
                    (
                        getattr(
                            location,
                            "failover_priority",
                            None,
                        )
                        for location in (
                            getattr(account, "locations", None)
                            or []
                        )
                        if str(
                            getattr(
                                location,
                                "location_name",
                                "",
                            )
                        ).casefold()
                        == requested_region
                    ),
                    None,
                )

            initial_priority = requested_region_priority()

            if initial_priority is None:
                raise ValueError(
                    f"Cosmos DB account does not have a region "
                    f"named '{variables['read_region']}'."
                )

            if initial_priority == 0:
                raise ValueError(
                    f"Cosmos DB region "
                    f"'{variables['read_region']}' "
                    "is already failover priority 0."
                )

            def completion_check():
                return requested_region_priority() == 0

        params = action_parameters(
            experiment.service,
            experiment.id,
            variables,
        )

        result = run_service_direct_classic_experiment(
            subscription_id=variables["subscription_id"],
            resource_group=variables["resource_group"],
            target_resource_id=variables["resource_id"],
            capability_urn=capability_urn,
            selector_target=selector_target,
            chaos_identity_id=variables["chaos_identity_id"],
            action_parameters=params,
            duration=variables.get("duration"),
            completion_check=completion_check,
        )
        experiment.status = "SUCCESS"
        return result
