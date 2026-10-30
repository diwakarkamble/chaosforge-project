import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.lifecycle.execution_dispatcher import ExecutionDispatcher
from chaosforge.providers.aws.fis.runner import FISExperimentRunner


class FakeRunner:
    def __init__(self, result="success"):
        self.result = result
        self.calls = []

    def execute(self, experiment):
        self.calls.append(experiment)
        return self.result

class FakeGate:
    def __init__(self):
        self.calls = []

    def ensure_ready(self, experiment):
        self.calls.append(experiment)


def make_experiment(engine):
    return SimpleNamespace(
        id="test-experiment",
        service="eks",
        name="Test Experiment",
        engine=engine,
        variables={},
    )


def test_dispatches_chaos_toolkit():
    runner = FakeRunner()

    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=runner,
    )

    experiment = make_experiment("Chaos Toolkit")

    result = dispatcher.execute(experiment)

    assert result == "success"
    assert runner.calls == [experiment]


def test_dispatches_aws_fis():
    runner = FakeRunner()

    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=FakeRunner(),
        fis_runner=runner,
    )

    experiment = make_experiment("AWS FIS")

    result = dispatcher.execute(experiment)

    assert result == "success"
    assert runner.calls == [experiment]


def test_dispatches_chaos_mesh():
    runner = FakeRunner()
    gate = FakeGate()

    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=FakeRunner(),
        chaos_mesh_runner=runner,
        chaos_mesh_execution_gate=gate,
    )

    experiment = make_experiment("Chaos Mesh")

    result = dispatcher.execute(experiment)

    assert result == "success"
    assert gate.calls == [experiment]
    assert runner.calls == [experiment]


def test_dispatches_azure_redis_reboot_directly(monkeypatch):
    runner = FakeRunner()
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=runner)
    experiment = SimpleNamespace(
        id="azure-redis-reboot",
        service="azure_redis",
        name="Reboot Redis",
        engine="Azure Chaos Studio",
        status="Pending",
        variables={
            "subscription_id": "sub",
            "resource_group": "rg",
            "redis_name": "cache",
            "chaos_identity_id": "identity",
        },
    )
    action = __import__(
        "chaosforge.providers.azure.components.azure_redis.experiments.chaos_studio.actions.redis_reboot",
        fromlist=["run_experiment"],
    )
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    identity_service = __import__(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity",
        fromlist=["AzureRedisChaosIdentityService"],
    )
    monkeypatch.setattr(
        identity_service.AzureRedisChaosIdentityService,
        "readiness",
        lambda *_args: {"status": "ready"},
    )
    monkeypatch.setattr(action, "run_experiment", lambda **kwargs: {"status": "started", **kwargs})

    result = dispatcher.execute(experiment)

    assert result["status"] == "started"
    assert experiment.status == "SUCCESS"
    assert runner.calls == []


def test_azure_redis_reboot_blocks_before_mutation_when_identity_is_unready(monkeypatch):
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=FakeRunner())
    experiment = SimpleNamespace(
        id="azure-redis-reboot", service="azure_redis", engine="Azure Chaos Studio",
        variables={
            "subscription_id": "sub", "resource_group": "rg", "redis_name": "cache",
            "chaos_identity_id": "identity",
        },
    )
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    identity_service = __import__(
        "chaosforge.providers.azure.components.azure_redis.chaos_identity",
        fromlist=["AzureRedisChaosIdentityService"],
    )
    monkeypatch.setattr(
        identity_service.AzureRedisChaosIdentityService,
        "readiness",
        lambda *_args: {"status": "missing_role", "message": "Grant Contributor"},
    )
    action = __import__(
        "chaosforge.providers.azure.components.azure_redis.experiments.chaos_studio.actions.redis_reboot",
        fromlist=["run_experiment"],
    )
    run = MagicMock()
    monkeypatch.setattr(action, "run_experiment", run)

    with pytest.raises(RuntimeError, match="Grant Contributor"):
        dispatcher.execute(experiment)

    run.assert_not_called()


def test_fis_defaults_to_direct_aws_fis_runner():
    runner = FakeRunner()
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=runner)

    assert isinstance(dispatcher.fis_runner, FISExperimentRunner)
    assert runner.calls == []


def test_missing_chaos_mesh_runner_uses_default_runner():
    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=FakeRunner(),
    )

    assert dispatcher.chaos_mesh_runner is not None


def test_unknown_engine_fails_clearly():
    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=FakeRunner(),
    )

    experiment = make_experiment("Unknown Engine")

    with pytest.raises(
        ValueError,
        match="Unsupported execution engine",
    ):
        dispatcher.execute(experiment)


def test_missing_engine_defaults_to_chaos_toolkit():
    runner = FakeRunner()

    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=runner,
    )

    experiment = make_experiment(None)

    result = dispatcher.execute(experiment)

    assert result == "success"
    assert runner.calls == [experiment]


def test_chaos_mesh_gate_failure_prevents_execution():
    runner = FakeRunner()

    class BlockingGate:
        def ensure_ready(self, experiment):
            raise RuntimeError("Chaos Mesh is not ready.")

    dispatcher = ExecutionDispatcher(
        chaos_toolkit_runner=FakeRunner(),
        chaos_mesh_runner=runner,
        chaos_mesh_execution_gate=BlockingGate(),
    )

    experiment = make_experiment("Chaos Mesh")

    with pytest.raises(
        RuntimeError,
        match="Chaos Mesh is not ready",
    ):
        dispatcher.execute(experiment)

    assert runner.calls == []


def test_dispatches_azure_classic_fault_with_translated_parameters(monkeypatch):
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=FakeRunner())
    experiment = SimpleNamespace(
        id="azure-vm-shutdown", service="azure_vm", engine="Azure Chaos Studio", status="PENDING",
        variables={"subscription_id": "sub", "resource_group": "rg", "resource_id": "/vm", "chaos_identity_id": "/identity", "duration": "PT1M"},
    )
    classic = __import__("chaosforge.providers.azure.chaos_studio.classic", fromlist=["run_service_direct_classic_experiment"])
    faults = __import__("chaosforge.providers.azure.chaos_studio.classic_faults", fromlist=["fault_details"])
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    monkeypatch.setattr(classic.AzureChaosIdentityService, "readiness", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(classic, "run_service_direct_classic_experiment", MagicMock(return_value={"status": "started"}))
    monkeypatch.setattr(faults, "fault_details", lambda *_: ("urn", "target", "Virtual Machine Contributor"))
    monkeypatch.setattr(faults, "action_parameters", lambda *_: {"abruptShutdown": False})
    assert dispatcher.execute(experiment) == {"status": "started"}
    assert experiment.status == "SUCCESS"


def test_azure_classic_fault_blocks_before_mutation_when_identity_is_unready(monkeypatch):
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=FakeRunner())
    experiment = SimpleNamespace(
        id="azure-vm-shutdown", service="azure_vm", engine="Azure Chaos Studio",
        variables={
            "subscription_id": "sub", "resource_group": "rg", "resource_id": "/vm",
            "chaos_identity_id": "/identity",
        },
    )
    classic = __import__("chaosforge.providers.azure.chaos_studio.classic", fromlist=["run_service_direct_classic_experiment"])
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    monkeypatch.setattr(classic.AzureChaosIdentityService, "readiness", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(classic.AzureChaosIdentityService, "readiness", lambda *_args: {"status": "missing_role", "message": "Grant Contributor"})
    run = MagicMock()
    monkeypatch.setattr(classic, "run_service_direct_classic_experiment", run)

    with pytest.raises(RuntimeError, match="Grant Contributor"):
        dispatcher.execute(experiment)

    run.assert_not_called()


def test_cosmos_failover_completes_when_the_requested_region_becomes_priority_zero(monkeypatch):
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=FakeRunner())
    experiment = SimpleNamespace(
        id="azure-cosmos-db-failover", service="azure_cosmos_db", engine="Azure Chaos Studio", status="PENDING",
        variables={"subscription_id": "sub", "resource_group": "rg", "resource_id": "/accounts/account", "chaos_identity_id": "/identity", "read_region": "UK South"},
    )
    classic = __import__("chaosforge.providers.azure.chaos_studio.classic", fromlist=["run_service_direct_classic_experiment"])
    faults = __import__("chaosforge.providers.azure.chaos_studio.classic_faults", fromlist=["fault_details"])
    run = MagicMock(return_value={"status": "started"})
    monkeypatch.setattr(classic, "run_service_direct_classic_experiment", run)
    monkeypatch.setattr(faults, "fault_details", lambda *_: ("urn", "target", "Cosmos DB Operator"))
    parameters = MagicMock(return_value={"readRegion": "UK South"})
    monkeypatch.setattr(faults, "action_parameters", parameters)
    priorities = iter([1, 0])
    client = SimpleNamespace(
        database_accounts=SimpleNamespace(
            get=lambda *_: SimpleNamespace(
                locations=[SimpleNamespace(location_name="UK South", failover_priority=next(priorities))]
            )
        )
    )
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    monkeypatch.setattr(classic.AzureChaosIdentityService, "readiness", lambda *_args: {"status": "ready"})
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.cosmosdb",
        SimpleNamespace(CosmosDBManagementClient=lambda *_: client),
    )

    dispatcher.execute(experiment)

    parameters.assert_called_once_with("azure_cosmos_db", "azure-cosmos-db-failover", experiment.variables)
    assert run.call_args.kwargs["action_parameters"] == {"readRegion": "UK South"}
    assert run.call_args.kwargs["completion_check"]() is True


@pytest.mark.parametrize(
    ("locations", "message"),
    [
        ([SimpleNamespace(location_name="West Europe", failover_priority=0)], "does not have a region"),
        ([SimpleNamespace(location_name="UK South", failover_priority=0)], "already failover priority 0"),
    ],
)
def test_cosmos_failover_rejects_invalid_or_already_primary_regions(monkeypatch, locations, message):
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=FakeRunner())
    experiment = SimpleNamespace(
        id="azure-cosmos-db-failover", service="azure_cosmos_db", engine="Azure Chaos Studio", status="PENDING",
        variables={"subscription_id": "sub", "resource_group": "rg", "resource_id": "/accounts/account", "chaos_identity_id": "/identity", "read_region": "UK South"},
    )
    classic = __import__("chaosforge.providers.azure.chaos_studio.classic", fromlist=["run_service_direct_classic_experiment"])
    faults = __import__("chaosforge.providers.azure.chaos_studio.classic_faults", fromlist=["fault_details"])
    run = MagicMock()
    monkeypatch.setattr(classic, "run_service_direct_classic_experiment", run)
    monkeypatch.setattr(faults, "fault_details", lambda *_: ("urn", "target", "Cosmos DB Operator"))
    monkeypatch.setattr(faults, "action_parameters", lambda *_: {"readRegion": "UK South"})
    monkeypatch.setitem(sys.modules, "azure.identity", SimpleNamespace(DefaultAzureCredential=lambda: object()))
    monkeypatch.setattr(classic.AzureChaosIdentityService, "readiness", lambda *_args: {"status": "ready"})
    monkeypatch.setitem(
        sys.modules,
        "azure.mgmt.cosmosdb",
        SimpleNamespace(
            CosmosDBManagementClient=lambda *_: SimpleNamespace(
                database_accounts=SimpleNamespace(get=lambda *_: SimpleNamespace(locations=locations))
            )
        ),
    )

    with pytest.raises(ValueError, match=message):
        dispatcher.execute(experiment)
    run.assert_not_called()


def test_direct_engine_helpers_reject_missing_runners_and_forward_observer():
    experiment = make_experiment("Chaos Mesh")
    dispatcher = ExecutionDispatcher(chaos_toolkit_runner=FakeRunner())
    dispatcher.fis_runner = None
    dispatcher.chaos_mesh_runner = None
    with pytest.raises(RuntimeError, match="AWS FIS execution engine"):
        dispatcher._execute_fis(experiment)
    with pytest.raises(RuntimeError, match="Chaos Mesh execution engine"):
        dispatcher._execute_chaos_mesh(experiment)

    class ObserverRunner:
        def execute(self, received, observer=None):
            return received, observer

    dispatcher.chaos_mesh_runner = ObserverRunner()
    dispatcher.chaos_mesh_execution_gate = FakeGate()
    observer = object()
    assert dispatcher._execute_chaos_mesh(experiment, observer=observer) == (experiment, observer)
    assert dispatcher._execute_chaos_mesh(experiment) == (experiment, None)
