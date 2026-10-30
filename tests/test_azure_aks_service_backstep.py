from unittest.mock import MagicMock, patch

import pytest

from chaosforge.interfaces.cli.interactive.azure_aks_service import (
    BackToMainMenu,
    _BackStep,
    _collect_aks_inputs,
    _empty_result_choice,
    _pick,
    add_aks_experiment,
)
from chaosforge.interfaces.cli.session import context


@pytest.fixture(autouse=True)
def _set_context():
    context.aks_kube_context = "amap-teusshared02-k8s"
    context.azure_subscription = "sub-id"
    context.azure_resource_group = "rg"
    context.aks_cluster_name = "amap-teusshared02-k8s"
    context.azure_location = "eastus"
    yield


def _metadata(inputs, name="AKS Experiment"):
    return {"name": name, "inputs": inputs}


def _make_discovery():
    discovery = MagicMock()
    discovery.list_namespaces.return_value = ["team-a"]
    discovery.list_deployments.return_value = ["api-deployment"]
    discovery.get_label_selector.return_value = ("app", "api")
    discovery.get_pod_count.return_value = 2
    discovery.list_nodes.return_value = ["node-a", "node-b"]
    discovery.list_zones.return_value = ["eastus-1", "eastus-2"]
    discovery.list_nodes_in_zone.return_value = ["node-a", "node-b"]
    discovery.list_pods.return_value = ["api-pod-1", "api-pod-2"]
    discovery.get_pod_label.return_value = ("app", "api-pod-1")
    discovery.get_deployment_for_pod.return_value = "api-deployment"
    discovery.list_containers.return_value = ["api", "sidecar"]
    discovery.list_pod_containers.return_value = ["api"]
    return discovery


def _run_collect(metadata, prompt_answers, discovery=None):
    answers = iter(prompt_answers)
    discovery = discovery or _make_discovery()
    with patch("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", return_value=discovery), patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.prompt",
        side_effect=lambda *a, **k: next(answers),
    ):
        return _collect_aks_inputs(metadata), discovery


def _backstep_metadata():
    return _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace", "required": True},
            {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment", "required": True},
            {"name": "chaos_mode", "label": "Chaos Mode", "type": "chaos_mode", "required": True, "default": "one"},
            {
                "name": "duration",
                "label": "Duration (seconds)",
                "type": "integer",
                "required": True,
                "default": 60,
                "min": 10,
                "max": 1800,
            },
            {"name": "chaos_value", "label": "Mode Value", "type": "text", "required": False, "default": ""},
            {
                "name": "loss_percentage",
                "label": "Packet Loss %",
                "type": "integer",
                "required": False,
                "default": 25,
                "min": 1,
                "max": 100,
            },
            {
                "name": "correlation",
                "label": "Correlation %",
                "type": "integer",
                "required": False,
                "default": 50,
                "min": 0,
                "max": 100,
            },
        ],
        name="Packet Loss",
    )


def test_backstep_on_a_later_field_preserves_the_label_selector():
    variables, _ = _run_collect(
        _backstep_metadata(),
        [
            "1",
            "1",
            "1",
            "1",
            "0",
            "1",
            "60",
            "25",
            "50",
            "n",
        ],
    )

    assert variables["deployment"] == "api-deployment"
    assert variables["label_key"] == "app"
    assert variables["label_val"] == "api"
    assert variables["pod_count"] == 2


def test_chaos_mode_back_returns_to_deployment_selection():
    variables, discovery = _run_collect(
        _backstep_metadata(),
        [
            "1",
            "1",
            "1",
            "0",
            "1",
            "",
            "",
            "25",
            "50",
            "n",
        ],
    )

    assert variables["deployment"] == "api-deployment"
    assert variables["chaos_mode"] == "one"
    assert discovery.list_deployments.call_count == 2
    discovery.list_deployments.assert_called_with("amap-teusshared02-k8s", "team-a")


def test_chaos_mode_back_renders_deployment_before_chaos_mode(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "type": "azure_aks_cluster"},
            {"name": "namespace", "type": "azure_aks_namespace"},
            {"name": "deployment", "type": "azure_aks_deployment"},
            {"name": "chaos_mode", "type": "chaos_mode"},
            {"name": "duration", "label": "Duration", "type": "integer", "default": 60},
        ]
    )
    discovery = _make_discovery()
    selections = iter(
        [
            "team-a",
            "By Deployment  -- target pods via deployment label selector",
            "api-deployment",
            _BackStep(),
            "api-deployment",
            "one  -- randomly pick one pod",
        ]
    )
    picker = MagicMock(side_effect=selections)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", lambda: discovery)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service._pick", picker)
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.prompt",
        MagicMock(side_effect=["", "n"]),
    )

    variables = _collect_aks_inputs(metadata)

    assert variables["deployment"] == "api-deployment"
    assert [call.args[0] for call in picker.call_args_list] == [
        "Select Namespace",
        "Select Target Mode",
        "Select Deployment",
        "Select Chaos Mode",
        "Select Deployment",
        "Select Chaos Mode",
    ]


def test_collect_inputs_for_deployment_target_mode_covers_container_chaos_integer_and_text():
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace", "required": True},
            {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment", "required": True},
            {"name": "container_name", "label": "Container", "type": "azure_aks_container", "required": True},
            {"name": "chaos_mode", "label": "Chaos Mode", "type": "chaos_mode", "required": True},
            {"name": "chaos_value", "label": "Mode Value", "type": "text", "required": False, "default": ""},
            {
                "name": "duration",
                "label": "Duration",
                "type": "integer",
                "required": True,
                "default": 30,
                "min": 10,
                "max": 60,
            },
            {"name": "notes", "label": "Notes", "type": "text", "required": True},
            {"name": "ticket", "label": "Ticket", "type": "text", "required": False, "default": "INC-1"},
        ],
        name="Deployment Mode",
    )
    discovery = _make_discovery()

    variables, _ = _run_collect(
        metadata,
        [
            "1",
            "1",
            "1",
            "2",
            "3",
            "3",
            "2",
            "bad",
            "61",
            "",
            "",
            "investigation",
            "",
            "y",
        ],
        discovery=discovery,
    )

    assert variables["aks_context"] == "amap-teusshared02-k8s"
    assert variables["subscription_id"] == "sub-id"
    assert variables["resource_group"] == "rg"
    assert variables["aks_name"] == "amap-teusshared02-k8s"
    assert variables["location"] == "eastus"
    assert variables["namespace"] == "team-a"
    assert variables["target_mode"] == "deployment"
    assert variables["deployment"] == "api-deployment"
    assert variables["container_name"] == "sidecar"
    assert variables["label_key"] == "app"
    assert variables["label_val"] == "api"
    assert variables["pod_count"] == 2
    assert variables["chaos_mode"] == "fixed"
    assert variables["chaos_value"] == "2"
    assert variables["duration"] == 30
    assert variables["notes"] == "investigation"
    assert variables["ticket"] == "INC-1"
    assert variables["dry_run"] == "true"
    discovery.list_containers.assert_called_once_with("amap-teusshared02-k8s", "team-a", "api-deployment")


def test_chaos_mode_quantity_supports_back_to_target_selection(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace", "required": True},
            {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment", "required": True},
            {"name": "chaos_mode", "label": "Chaos Mode", "type": "chaos_mode", "required": True},
            {"name": "duration", "label": "Duration (seconds)", "type": "integer", "required": True, "default": 60},
        ],
    )
    discovery = _make_discovery()
    choices = iter(["1", "1", "1", "3", "0", "1", "1", "", "n"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", lambda: discovery)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))

    variables = _collect_aks_inputs(metadata)

    assert variables["chaos_mode"] == "one"
    assert variables["duration"] == 60


def test_chaos_mode_back_preserves_namespace_and_reselects_deployment(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace", "required": True},
            {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment", "required": True},
            {"name": "chaos_mode", "label": "Chaos Mode", "type": "chaos_mode", "required": True, "default": "one"},
            {"name": "duration", "label": "Duration (seconds)", "type": "integer", "required": True, "default": 60},
        ],
    )
    discovery = _make_discovery()
    choices = iter(["1", "1", "1", "0", "1", "", "", "n"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", lambda: discovery)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))

    variables = _collect_aks_inputs(metadata)

    assert variables["namespace"] == "team-a"
    assert variables["deployment"] == "api-deployment"
    assert variables["chaos_mode"] == "one"
    assert variables["duration"] == 60
    discovery.list_namespaces.assert_called_once_with("amap-teusshared02-k8s")
    assert discovery.list_deployments.call_count == 2


def test_aks_prompts_show_and_accept_catalog_defaults(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster"},
            {"name": "chaos_mode", "label": "Chaos Mode", "type": "chaos_mode", "default": "one"},
            {"name": "duration", "label": "Duration", "type": "integer", "default": 60},
            {"name": "note", "label": "Note", "type": "text", "default": "planned-test"},
        ],
    )
    printed = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", MagicMock())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.console.print", printed)
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.prompt",
        lambda *_: "",
    )

    variables = _collect_aks_inputs(metadata)

    assert variables["chaos_mode"] == "one"
    assert variables["duration"] == 60
    assert variables["note"] == "planned-test"
    rendered = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
    assert "Default : one" in rendered
    assert "Default : 60" in rendered
    assert "Default : planned-test" in rendered


def test_fixed_chaos_mode_rejects_negative_quantity(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster"},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace"},
            {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment"},
            {"name": "chaos_mode", "label": "Chaos Mode", "type": "chaos_mode"},
        ],
    )
    discovery = _make_discovery()
    choices = iter(["1", "1", "1", "3", "-1", "1", "n"])
    error = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", lambda: discovery)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.error", error)

    variables = _collect_aks_inputs(metadata)

    assert variables["chaos_value"] == "1"
    error.assert_called_once_with("Value must be at least 1")


def test_manual_container_supports_back_and_main_menu(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster"},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace"},
            {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment"},
            {"name": "container_name", "label": "Container", "type": "azure_aks_container"},
        ],
    )
    discovery = _make_discovery()
    discovery.list_containers.return_value = []
    choices = iter(["1", "1", "1", "0", "0", "0"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", lambda: discovery)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))

    assert _collect_aks_inputs(metadata) is None

    choices = iter(["1", "1", "1", "m"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))
    with pytest.raises(BackToMainMenu):
        _collect_aks_inputs(metadata)


def test_generic_text_input_supports_back(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster"},
            {"name": "note", "label": "Note", "type": "text", "required": True},
        ],
    )
    choices = iter(["0"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", MagicMock())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))

    assert _collect_aks_inputs(metadata) is None


def test_aks_input_prompts_display_and_accept_falsy_defaults(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster"},
            {"name": "correlation", "label": "Correlation %", "type": "integer", "default": 0},
            {"name": "note", "label": "Note", "type": "text", "required": False, "default": ""},
        ],
    )
    printed = MagicMock()
    choices = iter(["", "", "n"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", MagicMock())
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.console.print", printed)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))

    variables = _collect_aks_inputs(metadata)

    assert variables["correlation"] == 0
    assert any(
        call.args and "Default : 0" in str(call.args[0])
        for call in printed.call_args_list
    )


def test_collect_inputs_for_pod_target_mode_uses_pod_container_and_auto_sets_chaos_mode():
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace", "required": True},
            {"name": "deployment", "label": "Deployment", "type": "azure_aks_deployment", "required": True},
            {"name": "container_name", "label": "Container", "type": "azure_aks_container", "required": True},
            {"name": "chaos_mode", "label": "Chaos Mode", "type": "chaos_mode", "required": True},
            {"name": "chaos_value", "label": "Mode Value", "type": "text", "required": False, "default": ""},
            {"name": "description", "label": "Description", "type": "text", "required": False},
        ],
        name="Pod Mode",
    )
    discovery = _make_discovery()

    variables, _ = _run_collect(
        metadata,
        ["1", "2", "1", "", "n"],
        discovery=discovery,
    )

    assert variables["namespace"] == "team-a"
    assert variables["deployment"] == "api-pod-1"
    assert variables["target_mode"] == "pod"
    assert variables["owning_deployment"] == "api-deployment"
    assert variables["label_key"] == "app"
    assert variables["label_val"] == "api-pod-1"
    assert variables["pod_count"] == 1
    assert variables["container_name"] == "api"
    assert variables["chaos_mode"] == "one"
    assert variables["chaos_value"] == ""
    assert variables["description"] == ""
    assert variables["dry_run"] == "false"
    discovery.list_pod_containers.assert_called_once_with("amap-teusshared02-k8s", "team-a", "api-pod-1")


def test_duration_back_for_deployment_target_preserves_selected_container(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "type": "azure_aks_cluster"},
            {"name": "namespace", "type": "azure_aks_namespace"},
            {"name": "deployment", "type": "azure_aks_deployment"},
            {"name": "container_name", "type": "azure_aks_container"},
            {"name": "chaos_mode", "type": "chaos_mode", "default": "one"},
            {"name": "duration", "label": "Duration", "type": "integer", "default": 60},
        ]
    )
    discovery = _make_discovery()
    choices = iter(["1", "1", "1", "1", "", "0", "", "60", "n"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", lambda: discovery)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))

    variables = _collect_aks_inputs(metadata)

    assert variables["container_name"] == "api"
    assert variables["duration"] == 60
    discovery.list_containers.assert_called_once_with("amap-teusshared02-k8s", "team-a", "api-deployment")


def test_pod_target_back_from_duration_returns_to_container_selection(monkeypatch):
    metadata = _metadata(
        [
            {"name": "aks_context", "type": "azure_aks_cluster"},
            {"name": "namespace", "type": "azure_aks_namespace"},
            {"name": "deployment", "type": "azure_aks_deployment"},
            {"name": "container_name", "type": "azure_aks_container"},
            {"name": "chaos_mode", "type": "chaos_mode", "default": "one"},
            {"name": "duration", "label": "Duration", "type": "integer", "default": 60},
        ]
    )
    discovery = _make_discovery()
    choices = iter(["1", "2", "1", "0", "", "60", "n"])
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery", lambda: discovery)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", lambda *_: next(choices))

    variables = _collect_aks_inputs(metadata)

    assert variables["container_name"] == "api"
    assert variables["duration"] == 60
    assert discovery.list_pod_containers.call_count == 2


def test_collect_inputs_for_node_selection():
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "target_node", "label": "Node", "type": "azure_aks_node", "required": True},
            {"name": "reason", "label": "Reason", "type": "text", "required": True},
        ],
        name="Node Drain",
    )

    variables, discovery = _run_collect(metadata, ["2", "planned-maintenance", "n"])

    assert variables["target_node"] == "node-b"
    assert variables["reason"] == "planned-maintenance"
    discovery.list_nodes.assert_called_once_with("amap-teusshared02-k8s")


def test_collect_inputs_for_zone_selection_sets_target_nodes():
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "zone", "label": "Zone", "type": "azure_aks_zone", "required": True},
            {
                "name": "duration",
                "label": "Duration",
                "type": "integer",
                "required": True,
                "default": 20,
                "min": 5,
                "max": 30,
            },
        ],
        name="Zone Failure",
    )

    variables, discovery = _run_collect(metadata, ["1", "15", "n"])

    assert variables["zone"] == "eastus-1"
    assert variables["target_node"] == "node-a,node-b"
    assert variables["duration"] == 15
    discovery.list_zones.assert_called_once_with("amap-teusshared02-k8s")
    discovery.list_nodes_in_zone.assert_called_once_with("amap-teusshared02-k8s", "eastus-1")


def test_empty_result_choice_supports_retry_and_main_menu():
    with patch("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", side_effect=["1"]):
        with pytest.raises(_BackStep):
            _empty_result_choice("Nothing found")

    with patch("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", side_effect=["bad", "0"]), patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.error"
    ) as mock_error:
        with pytest.raises(BackToMainMenu):
            _empty_result_choice("Nothing found")
    mock_error.assert_called_once_with("Invalid selection")


def test_namespace_discovery_error_is_not_reported_as_empty_cluster():
    metadata = _metadata(
        [
            {"name": "aks_context", "label": "AKS Cluster", "type": "azure_aks_cluster", "required": True},
            {"name": "namespace", "label": "Namespace", "type": "azure_aks_namespace", "required": True},
        ]
    )
    discovery = _make_discovery()
    discovery.list_namespaces.return_value = []
    discovery.last_error = "Could not list namespaces: forbidden"

    with patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.AzureAKSDiscovery",
        return_value=discovery,
    ), patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.warning"
    ) as warning, patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.pause"
    ), pytest.raises(BackToMainMenu):
        _collect_aks_inputs(metadata)

    message = warning.call_args.args[0]
    assert "Namespace discovery failed" in message
    assert "forbidden" in message
    assert "no namespaces" not in message.lower()


def test_pick_supports_search_and_back_from_filtered_results():
    with patch("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", side_effect=["s", "beta", "0", "2"]):
        assert _pick("Select Item", ["alpha", "beta", "gamma"]) == "beta"


def test_picker_back_clears_search_before_returning_to_the_prior_step():
    with patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.prompt",
        side_effect=["s", "beta", "0", "0"],
    ), pytest.raises(_BackStep):
        _pick("Select Item", ["alpha", "beta", "gamma"])


def test_picker_search_is_case_insensitive():
    with patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.prompt",
        side_effect=["S", "BETA", "1"],
    ):
        assert _pick("Select Item", ["alpha", "beta", "gamma"]) == "beta"


def test_picker_styles_back_and_search_as_selectable_options(monkeypatch):
    printed = MagicMock()
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.console.print", printed)
    monkeypatch.setattr("chaosforge.interfaces.cli.interactive.azure_aks_service.prompt", MagicMock(return_value="1"))

    assert _pick("Select Item", ["alpha"]) == "alpha"

    printed.assert_any_call(
        "  [cyan]0.[/cyan] Back  [bright_black]|[/bright_black]  [cyan]s.[/cyan] Search"
    )


def test_add_aks_experiment_handles_missing_metadata():
    with patch("chaosforge.interfaces.cli.interactive.azure_aks_service.get_experiment", return_value=None), patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.error"
    ) as mock_error, patch("chaosforge.interfaces.cli.interactive.azure_aks_service.pause") as mock_pause:
        add_aks_experiment("missing-exp")

    mock_error.assert_called_once_with("Experiment 'missing-exp' not found.")
    mock_pause.assert_called_once()


def test_add_aks_experiment_returns_when_collection_is_cancelled():
    metadata = _metadata([], name="Cancelled")
    with patch("chaosforge.interfaces.cli.interactive.azure_aks_service.get_experiment", return_value=metadata), patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service._collect_aks_inputs",
        return_value=None,
    ), patch("chaosforge.interfaces.cli.interactive.azure_aks_service.build_experiment") as mock_build:
        add_aks_experiment("cancelled")

    mock_build.assert_not_called()


def test_add_aks_experiment_builds_campaign_on_success():
    metadata = _metadata([], name="Node Drain")
    variables = {"target_node": "node-a"}
    with patch("chaosforge.interfaces.cli.interactive.azure_aks_service.get_experiment", return_value=metadata), patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service._collect_aks_inputs",
        return_value=variables,
    ), patch("chaosforge.interfaces.cli.interactive.azure_aks_service.build_experiment") as mock_build, patch(
        "chaosforge.interfaces.cli.interactive.azure_aks_service.success"
    ) as mock_success, patch("chaosforge.interfaces.cli.interactive.azure_aks_service.pause") as mock_pause:
        add_aks_experiment("node-drain")

    mock_build.assert_called_once_with("aks", metadata, variables)
    mock_success.assert_called_once_with("Node Drain added to Campaign")
    mock_pause.assert_called_once()
