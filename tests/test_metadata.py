from unittest.mock import patch

from chaosforge.application.metadata import (
    get_experiment,
    get_experiments,
    load_service_metadata,
)


@patch("chaosforge.application.metadata.ExperimentCatalog.load_service")
def test_load_service_metadata(mock_load):
    metadata = {"experiments": []}
    mock_load.return_value = metadata

    result = load_service_metadata("lambda")

    assert result == metadata


@patch("chaosforge.application.metadata.ExperimentCatalog.load_service")
def test_load_service_metadata_not_found(mock_load):
    mock_load.return_value = None
    result = load_service_metadata("lambda")

    assert result is None


@patch("chaosforge.application.metadata.load_service_metadata")
def test_get_experiments(mock_load):

    mock_load.return_value = {"experiments": [{"id": "one"}, {"id": "two"}]}

    result = get_experiments("lambda")

    assert len(result) == 2


@patch("chaosforge.application.metadata.load_service_metadata")
def test_get_experiments_no_metadata(mock_load):

    mock_load.return_value = None

    result = get_experiments("lambda")

    assert result == []


@patch("chaosforge.application.metadata.load_service_metadata")
def test_get_aks_experiments_keep_clock_skew_names_without_offsets(mock_load):
    mock_load.return_value = {
        "experiments": [
            {"id": "aks-clock-skew-forward", "name": "Clock Skew Forward"},
            {"id": "aks-clock-skew-backward", "name": "Clock Skew Backward"},
            {"id": "aks-pod-kill", "name": "Pod Kill"},
        ]
    }

    result = get_experiments("aks")

    names = {experiment["id"]: experiment["name"] for experiment in result}
    assert names["aks-clock-skew-forward"] == "Clock Skew Forward"
    assert names["aks-clock-skew-backward"] == "Clock Skew Backward"
    assert names["aks-pod-kill"] == "Pod Kill"


@patch("chaosforge.application.metadata.get_experiments")
def test_get_experiment(mock_get):

    mock_get.return_value = [{"id": "timeout"}]

    result = get_experiment("lambda", "timeout")

    assert result["id"] == "timeout"


def test_internal_fis_wrapper_is_hidden_from_lists_but_resolvable(monkeypatch):
    metadata = {
        "experiments": [
            {"id": "fis-create-experiment", "internal": True},
            {"id": "fis-start-template"},
        ]
    }
    monkeypatch.setattr("chaosforge.application.metadata.load_service_metadata", lambda _: metadata)

    assert get_experiments("fis") == [{"id": "fis-start-template"}]
    assert get_experiment("fis", "fis-create-experiment") == {
        "id": "fis-create-experiment",
        "internal": True,
    }


@patch("chaosforge.application.metadata.get_experiments")
def test_get_experiment_not_found(mock_get):

    mock_get.return_value = [{"id": "timeout"}]

    result = get_experiment("lambda", "memory")

    assert result is None


def test_eks_pod_kill_uses_aks_style_target_contract():
    experiment = get_experiment("chaos_mesh", "chaos-mesh-pod-kill")
    inputs = {field["name"]: field for field in experiment["inputs"]}

    assert inputs["target_mode"]["options"][1]["value"] == "pod"
    assert inputs["deployment"]["visible_when"] == {"target_mode": "deployment"}
    assert inputs["pod"]["visible_when"] == {"target_mode": "pod"}
    assert inputs["duration"]["default"] == "PT60S"
    assert inputs["duration"]["type"] == "iso8601_duration"
    assert inputs["duration"]["min"] == 10
    assert inputs["duration"]["max"] == 1800


def test_aks_catalog_is_azure_chaos_studio_not_chaos_toolkit():
    from chaosforge.application.campaigns.factory import create_experiment

    metadata = get_experiment("aks", "aks-pod-kill")
    experiment = create_experiment(
        "aks", metadata, {"aks_context": "cluster", "namespace": "apps"}
    )

    assert experiment.engine == "Azure Chaos Studio"
    assert metadata.get("engine") is None
