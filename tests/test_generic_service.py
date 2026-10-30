from unittest.mock import patch

from chaosforge.application.services.generic import add_generic


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.get_experiment")
def test_experiment_not_found(mock_get, mock_print, mock_input):

    mock_get.return_value = None

    add_generic("lambda", "lambda-timeout")

    mock_print.assert_called()
    mock_input.assert_called_once()


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.build_experiment")
@patch("chaosforge.application.services.generic.collect_inputs")
@patch("chaosforge.application.services.generic.get_experiment_description")
@patch("chaosforge.application.services.generic.get_experiment")
def test_add_generic(mock_get, mock_description, mock_collect, mock_build, mock_print, mock_input):

    metadata = {"name": "Lambda Timeout"}

    mock_get.return_value = metadata
    mock_description.return_value = {
        "description": "description",
        "impact": "impact",
        "expected_behavior": "expected",
    }

    mock_collect.return_value = {"lambda_name": "demo"}

    add_generic("lambda", "lambda-timeout")

    mock_collect.assert_called_once()

    mock_build.assert_called_once()
    output = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Experiment Description" in output
    assert "Potential Impact: impact" in output
    assert "Expected Behavior: expected" in output


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.build_experiment")
@patch("chaosforge.application.services.generic.collect_inputs")
@patch("chaosforge.application.services.generic.get_experiment")
def test_metadata_not_modified(
    mock_get, mock_collect, mock_build, mock_print, mock_input
):

    metadata = {"name": "Original"}

    mock_get.return_value = metadata

    mock_collect.return_value = {}

    add_generic("lambda", "lambda-timeout")

    assert metadata["name"] == "Original"


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.build_experiment")
@patch("chaosforge.application.services.generic.collect_inputs")
@patch("chaosforge.application.services.generic.FISCatalog")
@patch("chaosforge.application.services.generic.get_experiment")
def test_fis_name_update(
    mock_get, mock_catalog, mock_collect, mock_build, mock_print, mock_input
):

    metadata = {"name": "Old"}

    mock_get.return_value = metadata

    mock_collect.return_value = {}

    catalog = mock_catalog.return_value

    catalog.get_experiment.return_value = {"name": "Delay Injection"}

    add_generic("fis", "fis-start", {"service_id": "lambda", "experiment_id": "delay"})

    args = mock_build.call_args[0]

    metadata_used = args[1]

    assert metadata_used["name"] == "Delay Injection (AWS FIS)"


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.build_experiment")
@patch("chaosforge.application.services.generic.collect_inputs")
@patch("chaosforge.application.services.generic.FISCatalog")
@patch("chaosforge.application.services.generic.get_experiment")
def test_fis_catalog_returns_none(
    mock_get, mock_catalog, mock_collect, mock_build, mock_print, mock_input
):

    metadata = {"name": "Old"}

    mock_get.return_value = metadata

    mock_collect.return_value = {}

    catalog = mock_catalog.return_value

    catalog.get_experiment.return_value = None

    add_generic("fis", "fis-start", {"service_id": "lambda", "experiment_id": "delay"})

    mock_build.assert_called_once()


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.build_experiment")
@patch("chaosforge.application.services.generic.collect_inputs")
@patch("chaosforge.application.services.generic.get_experiment")
def test_prefill_passed(mock_get, mock_collect, mock_build, mock_print, mock_input):

    metadata = {"name": "Lambda"}

    mock_get.return_value = metadata

    mock_collect.return_value = {}

    prefill = {"service_id": "lambda"}

    add_generic("lambda", "lambda-timeout", prefill)

    _, kwargs = mock_collect.call_args

    assert kwargs["prefill"] == prefill


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.build_experiment")
@patch("chaosforge.application.services.generic.collect_inputs")
@patch("chaosforge.application.services.generic.get_experiment")
def test_variables_passed(mock_get, mock_collect, mock_build, mock_print, mock_input):

    metadata = {"name": "Lambda"}

    variables = {"timeout": 30}

    mock_get.return_value = metadata

    mock_collect.return_value = variables

    add_generic("lambda", "lambda-timeout")

    args = mock_build.call_args[0]

    assert args[2] == variables
    assert "30" not in "\n".join(
        " ".join(map(str, call.args)) for call in mock_print.call_args_list
    )


@patch("builtins.input")
@patch("builtins.print")
@patch("chaosforge.application.services.generic.build_experiment")
@patch("chaosforge.application.services.generic.prompt", return_value="Y")
@patch("chaosforge.application.services.generic.collect_inputs")
@patch("chaosforge.application.services.generic.get_experiment")
def test_chaos_mesh_workload_can_be_added_as_dry_run(
    mock_get,
    mock_collect,
    mock_prompt,
    mock_build,
    _mock_print,
    _mock_input,
):
    metadata = {"name": "Network Delay"}
    variables = {"namespace": "default"}
    mock_get.return_value = metadata
    mock_collect.return_value = variables

    add_generic("chaos_mesh", "chaos-mesh-network-delay")

    mock_prompt.assert_called_once_with("Run as DRY RUN (preview only)? (Y/N)")
    assert variables["dry_run"] == "true"
    mock_build.assert_called_once_with("chaos_mesh", metadata, variables)
