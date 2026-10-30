from copy import deepcopy

from chaosforge.application.campaigns.builder import build_experiment
from chaosforge.application.component_fis import bind_component_fis, prepare_component_fis_variables
from chaosforge.application.experiment_descriptions import get_experiment_description
from chaosforge.application.metadata import get_experiment
from chaosforge.application.services.cloud_identity import get_cloud_identity
from chaosforge.engines.chaos_mesh.target_contract import is_workload_experiment
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.providers.aws.fis.catalog import FISCatalog


def collect_inputs(*args, **kwargs):
    """Load CLI input collection only when an interactive run needs it."""
    from chaosforge.interfaces.cli.interactive.input_engine import (
        collect_inputs as collect,
    )

    return collect(*args, **kwargs)


def add_generic(service, experiment_id, prefill=None):

    metadata = get_experiment(service, experiment_id)

    if metadata is None:
        print(f"\nExperiment '{experiment_id}' not found.")

        input("\nPress Enter...")

        return

    #
    # Clone metadata so the original is not modified
    #

    metadata = deepcopy(metadata)

    #
    # If this is an AWS FIS experiment,
    # update the display name using the FIS catalog.
    #

    if service == "fis" and prefill:
        catalog = FISCatalog()

        fis_experiment = catalog.get_experiment(
            prefill["service_id"], prefill["experiment_id"]
        )

        if fis_experiment:
            metadata["name"] = f"{fis_experiment['name']} (AWS FIS)"
            metadata = bind_component_fis(
                metadata, prefill["service_id"], prefill["experiment_id"]
            )
            identity = get_cloud_identity("aws", refresh=True)
            principal_arn = identity.get("principal_arn", "")
            prefill = {**prefill, "created_by": principal_arn.rsplit("/", 1)[-1]}

    description = get_experiment_description(service, experiment_id)
    print(f"\nExperiment Description\nDescription: {description.get('description', metadata['name'])}")
    print(f"Potential Impact: {description.get('impact', 'Review the configured fault impact.')}")
    print(f"Expected Behavior: {description.get('expected_behavior', 'Verify workload recovery after cleanup.')}")

    variables = collect_inputs(metadata, prefill=prefill)
    if service == "chaos_mesh" and variables and is_workload_experiment(experiment_id):
        print("\nDry Run\nPreview what this experiment would do - no changes will be made.")
        variables["dry_run"] = "true" if prompt("Run as DRY RUN (preview only)? (Y/N)").strip().lower() == "y" else "false"
    if service == "fis" and variables:
        prepare_component_fis_variables(variables)

    build_experiment(service, metadata, variables)

    print(f"\n✓ {metadata['name']} added to Campaign")

    input("\nPress Enter...")
