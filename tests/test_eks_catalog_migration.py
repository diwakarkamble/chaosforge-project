import importlib
import inspect
import json
from pathlib import Path

EXPERIMENTS = (
    Path(__file__).resolve().parents[1]
    / "chaosforge"
    / "providers"
    / "aws"
    / "components"
    / "eks"
    / "experiments"
)


def _python_providers(activity):
    provider = activity.get("provider", {})
    if provider.get("type") == "python":
        yield provider


def test_eks_catalog_uses_migrated_definitions_and_providers():
    metadata = json.loads((EXPERIMENTS / "metadata.json").read_text(encoding="utf-8"))

    assert len(metadata["experiments"]) == 4

    for experiment in metadata["experiments"]:
        definition_path = EXPERIMENTS / "toolkit" / "definitions" / experiment["json"]
        assert definition_path.is_file()

        definition = json.loads(definition_path.read_text(encoding="utf-8"))
        activities = definition.get("method", []) + definition.get("rollbacks", [])

        for activity in activities:
            for provider in _python_providers(activity):
                module = importlib.import_module(provider["module"])
                assert hasattr(module, provider["func"])
                assert provider["module"].startswith("chaosforge.providers.aws.components.eks.")
                signature = inspect.signature(getattr(module, provider["func"]))
                assert set(provider.get("arguments", {})) <= set(signature.parameters)


def test_eks_catalog_uses_safe_wrappers_for_kubernetes_mutations():
    definitions = EXPERIMENTS / "toolkit" / "definitions"

    expected = {
        "eks-node-drain-chaos.json": "drain_eks_node",
        "eks-node-cordon-chaos.json": "cordon_eks_node",
        "eks-container-restart-chaos.json": "restart_eks_container",
    }

    for filename, function in expected.items():
        definition = json.loads((definitions / filename).read_text(encoding="utf-8"))
        provider = definition["method"][0]["provider"]
        assert provider["func"] == function
        assert provider["module"].startswith("chaosforge.providers.aws.components.eks.")
