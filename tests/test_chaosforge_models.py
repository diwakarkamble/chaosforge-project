from chaosforge.models import (
    Campaign,
    ExecutionContext,
    ExecutionState,
    Experiment,
    PlanResult,
)


def test_canonical_models_are_importable_from_one_namespace():
    assert Campaign.__module__ == "chaosforge.models.campaign"
    assert Experiment.__module__ == "chaosforge.models.experiment"
    assert ExecutionContext.__module__ == "chaosforge.models.execution"
    assert ExecutionState.__module__ == "chaosforge.models.execution"
    assert PlanResult.__module__ == "chaosforge.models.planning"


def test_canonical_models_preserve_current_defaults():
    assert Campaign().name == "Default Campaign"
    assert Campaign().cloud_provider == "aws"
    assert Experiment("id", "service", "name", "definition.json", {}).status == "Pending"
    assert ExecutionContext("id", "experiment", "service", "name").state is ExecutionState.PLANNED
    assert PlanResult().finalize().executable is True
