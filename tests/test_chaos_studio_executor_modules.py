import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

from chaosforge.providers.azure.components.aks.experiments.chaos_studio import (
    execution_support,
    executor,
    lifecycle_cleanup,
    lifecycle_operations,
    node_operations,
    node_stress_execution,
    node_stress_operations,
    studio_execution,
    studio_runtime,
    vmss_operations,
    zone_operations,
)


def test_executor_keeps_public_entry_points_and_helper_signatures():
    assert str(inspect.signature(executor.setup_studio)).startswith("(experiment_id")
    assert str(inspect.signature(executor.run_experiment)).startswith("(experiment_id")
    assert str(inspect.signature(executor.cleanup_experiment)).startswith("(experiment_id")
    assert inspect.signature(executor._build_spec) == inspect.signature(
        studio_execution._build_spec
    )
    assert inspect.signature(executor._run_node_drain) == inspect.signature(
        node_operations._run_node_drain
    )
    assert inspect.signature(executor._resolve_azure_details) == inspect.signature(
        execution_support._resolve_azure_details
    )
    assert inspect.signature(executor._run_vmss_experiment) == inspect.signature(
        vmss_operations._run_vmss_experiment
    )
    assert inspect.signature(executor.setup_studio) == inspect.signature(
        lifecycle_operations.setup_studio
    )


def test_executor_helpers_are_owned_by_their_domain_modules():
    assert executor.setup_studio.__module__ == lifecycle_operations.__name__
    assert executor.run_experiment.__module__ == lifecycle_operations.__name__
    assert executor.cleanup_experiment.__module__ == lifecycle_cleanup.__name__
    assert executor._build_spec.__module__ == studio_execution.__name__
    assert executor._load_state.__module__ == execution_support.__name__
    assert executor._run_node_cpu_stress.__module__ == node_stress_execution.__name__
    assert executor._run_zone_failure.__module__ == zone_operations.__name__


def test_executor_monkeypatches_are_forwarded_to_extracted_helpers(monkeypatch):
    kubectl = MagicMock(return_value=SimpleNamespace(stdout="True", returncode=0))
    monkeypatch.setattr(executor, "_kubectl", kubectl)

    assert executor._node_is_ready("node-a") is True
    kubectl.assert_called_once()


def test_executor_bridge_forwards_dependencies(monkeypatch):
    def helper():
        return globals()["dependency"]()

    wrapped = execution_support.executor_compatible(helper)
    monkeypatch.setattr(executor, "dependency", lambda: "patched", raising=False)

    assert wrapped() == "patched"


def test_extracted_module_exports_are_complete_and_disjoint():
    modules = (
        execution_support,
        lifecycle_cleanup,
        lifecycle_operations,
        studio_execution,
        studio_runtime,
        node_operations,
        node_stress_execution,
        node_stress_operations,
        vmss_operations,
        zone_operations,
    )
    exported = [set(module.__all__) for module in modules]
    owned = {
        name
        for module in modules
        for name in module.__all__
        if getattr(module, name).__module__ == module.__name__
    }

    assert all(exported)
    assert len(owned) == len({getattr(executor, name) for name in owned})
    assert all(hasattr(executor, name) for names in exported for name in names)
