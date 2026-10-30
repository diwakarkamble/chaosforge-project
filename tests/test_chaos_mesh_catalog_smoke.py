import json
from pathlib import Path
from types import SimpleNamespace

from chaosforge.engines.chaos_mesh.chaos_mesh_experiment_mapper import (
    ChaosMeshExperimentMapper,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "chaosforge" / "engines" / "chaos_mesh" / "experiments"


def test_all_chaos_mesh_catalog_experiments_build_manifests():
    metadata_path = CATALOG_DIR / "metadata.json"

    metadata = json.loads(
        metadata_path.read_text(encoding="utf-8")
    )

    experiments = metadata["experiments"]

    assert len(experiments) == 31

    mapper = ChaosMeshExperimentMapper()

    failures = []

    for item in experiments:
        experiment_id = item["id"]
        json_path = CATALOG_DIR / "definitions" / item["json"]

        variables = {}

        if experiment_id == "chaos-mesh-physical-machine":
            variables["physical_machine"] = "physical-machine-a"

        experiment = SimpleNamespace(
            id=experiment_id,
            name=item["name"],
            service="chaos_mesh",
            json_file=str(json_path),
            variables=variables,
        )

        try:
            manifest = mapper.build_manifest(experiment)

            assert isinstance(manifest, dict)
            assert manifest["apiVersion"] == "chaos-mesh.org/v1alpha1"
            assert manifest["kind"]
            assert manifest["metadata"]["name"]
            assert manifest["metadata"]["namespace"]
            assert isinstance(manifest["spec"], dict)

        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"{experiment_id}: {type(exc).__name__}: {exc}"
            )

    assert not failures, (
        "Chaos Mesh catalog manifest build failures:\n"
        + "\n".join(failures)
    )
