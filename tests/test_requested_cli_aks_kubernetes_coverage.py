"""Coverage for isolated CLI and Kubernetes edge paths; no cloud calls are made."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.interfaces.cli import main as cli
from chaosforge.interfaces.cli.interactive import azure_aks_service as aks
from chaosforge.interfaces.cli.interactive import input_engine, resource_selector
from chaosforge.models import Campaign, Experiment
from chaosforge.providers.azure.components.aks import kubernetes as k8s


@pytest.fixture
def quiet_cli(monkeypatch):
    for name in (
        "clear_screen", "print_banner", "dashboard", "title", "menu", "pause",
        "error", "info", "success", "warning",
    ):
        monkeypatch.setattr(cli, name, MagicMock())
    monkeypatch.setattr(cli, "console", MagicMock())


def _experiment(status="Pending"):
    item = Experiment(
        id="exp", service="lambda", name="Experiment", json_file="exp.json", variables={}
    )
    item.status = status
    return item


def test_main_remaining_validation_confirmation_and_screen_paths(monkeypatch, capsys):
    campaign = Campaign(experiments=[_experiment()])
    campaign.experiments[0].variables["aws_region"] = "eu-west-1"
    validation = {
        "valid": True,
        "experiments": [{
            "experiment_id": "exp", "service": "lambda", "name": "Experiment",
            "errors": [], "warnings": [],
        }],
    }
    discovery = MagicMock()
    discovery.verify_aws_credentials.return_value = {
        "account_id": "123456789012", "region": "eu-west-1"
    }
    monkeypatch.setattr(cli, "load_yaml", lambda _: {"cloud": {"provider": "aws"}})
    monkeypatch.setattr(cli, "YAMLValidator", lambda: SimpleNamespace(validate=lambda _: {"valid": True}))
    monkeypatch.setattr(cli, "build_campaign", lambda _: campaign)
    monkeypatch.setattr(
        cli, "ExperimentValidationService",
        lambda: SimpleNamespace(validate_campaign=lambda _: validation),
    )
    monkeypatch.setattr(cli, "AWSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(cli, "success", MagicMock())
    assert cli.load_and_validate_yaml_campaign("campaign.yaml") is campaign
    output = capsys.readouterr().out
    assert "Experiment : exp" in output
    assert "Account : 123456789012" in output

    discovery.verify_aws_credentials.side_effect = RuntimeError("expired token")
    monkeypatch.setattr(cli, "error", MagicMock())
    assert cli.load_and_validate_yaml_campaign("campaign.yaml") is None
    assert "expired token" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda _: "No")
    assert cli.confirm_campaign_execution() is False
    system = MagicMock()
    monkeypatch.setattr(cli.os, "system", system)
    cli.clear_screen()
    system.assert_called_once_with("cls" if os.name == "nt" else "clear")


def test_main_empty_cancel_error_and_mutation_branches(monkeypatch, quiet_cli):
    monkeypatch.setattr(cli, "list_all", MagicMock(return_value=[]))
    cli.view_campaign()
    cli.remove_experiment()
    cli.clear_campaign()
    cli.execute_campaign()
    cli.save_campaign()
    assert cli.pause.call_count == 5

    entries = [_experiment()]
    monkeypatch.setattr(cli, "list_all", MagicMock(return_value=entries))
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="0"))
    remove = MagicMock()
    monkeypatch.setattr(cli, "remove", remove)
    cli.view_campaign()
    cli.remove_experiment()
    remove.assert_not_called()

    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="bad"))
    monkeypatch.setattr(cli, "remove", MagicMock(side_effect=IndexError()))
    cli.remove_experiment()
    cli.error.assert_called_with("Invalid Selection.")

    clear = MagicMock()
    monkeypatch.setattr(cli, "clear", clear)
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="y"))
    cli.clear_campaign()
    clear.assert_called_once_with()
    cli.success.assert_called_with("Campaign cleared successfully.")

    monkeypatch.setattr(cli, "prompt", MagicMock(return_value=""))
    export = MagicMock()
    monkeypatch.setattr(cli, "export_campaign_yaml", export)
    cli.save_campaign()
    export.assert_called_once_with()


def test_main_execute_choices_retry_edit_and_load_failures(monkeypatch, quiet_cli):
    failed = _experiment("FAILED")
    monkeypatch.setattr(cli, "list_all", MagicMock(return_value=[failed]))
    monkeypatch.setattr(cli, "confirm_permission_review", MagicMock(return_value=True))
    monkeypatch.setattr(
        "chaosforge.application.metadata.load_service_metadata",
        lambda _: {"display_name": "Lambda"},
    )
    execute = MagicMock()
    report = MagicMock()
    monkeypatch.setattr(cli, "execute_lifecycle_campaign", execute)
    monkeypatch.setattr(cli, "generate_report", report)

    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="0"))
    cli.execute_campaign()
    execute.assert_not_called()

    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="invalid"))
    cli.execute_campaign()
    cli.error.assert_called_with("Invalid Choice")

    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="2"))
    monkeypatch.setattr(cli, "build_selected_campaign", MagicMock(return_value=None))
    cli.execute_campaign()
    execute.assert_not_called()

    actions = MagicMock(side_effect=["retry", "edit", None])
    monkeypatch.setattr(
        "chaosforge.interfaces.cli.interactive.campaign_result.show_campaign_result_menu", actions
    )
    monkeypatch.setattr(cli, "prompt", MagicMock(return_value="1"))
    monkeypatch.setattr(cli, "edit_failed_campaign", MagicMock())
    monkeypatch.setattr(
        cli, "build_failed_campaign", MagicMock(return_value=Campaign(experiments=[failed]))
    )
    cli.execute_campaign()
    assert execute.call_count == 2
    assert report.call_count == 2
    cli.edit_failed_campaign.assert_called_once_with(cli.campaign)

    monkeypatch.setattr(cli, "list_saved_campaigns", MagicMock(return_value=[]))
    cli.load_campaign()
    monkeypatch.setattr(
        cli, "list_saved_campaigns", MagicMock(return_value=[{"name": "Saved", "experiments": 1}])
    )
    monkeypatch.setattr(cli, "prompt", MagicMock(side_effect=["0", "bad", "1", "1"]))
    cli.load_campaign()
    cli.load_campaign()
    monkeypatch.setattr(cli, "load_saved_campaign", MagicMock(side_effect=FileNotFoundError()))
    cli.load_campaign()
    monkeypatch.setattr(cli, "load_saved_campaign", MagicMock(side_effect=ValueError("corrupt")))
    cli.load_campaign()
    cli.error.assert_called_with("Failed to load campaign: corrupt")


def test_main_plan_edit_empty_and_argument_dispatch(monkeypatch, quiet_cli):
    assert cli.edit_failed_campaign(Campaign(experiments=[_experiment("COMPLETED")])) is None
    planned_campaign = Campaign(name="Plan")
    result = SimpleNamespace(executable=True)
    monkeypatch.setattr(cli, "load_and_validate_yaml_campaign", lambda _: planned_campaign)
    monkeypatch.setattr(cli, "PlanService", lambda: SimpleNamespace(plan_campaign=lambda _: result))
    display = MagicMock()
    monkeypatch.setattr(cli, "display_campaign_plan", display)
    assert cli.plan_yaml_campaign("plan.yaml") == 0
    display.assert_called_once_with(planned_campaign, result)
    result.executable = False
    assert cli.plan_yaml_campaign("plan.yaml") == 1

    for command, target in (
        ("validate", "validate_yaml_campaign"),
        ("plan", "plan_yaml_campaign"),
        ("run", "execute_yaml_campaign"),
    ):
        handler = MagicMock(return_value=7)
        monkeypatch.setattr(cli, target, handler)
        monkeypatch.setattr(sys, "argv", ["chaosforge", command, "file.yaml"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 7
        handler.assert_called_once_with("file.yaml")

    monkeypatch.setattr(cli, "execute_yaml_campaign", MagicMock())
    monkeypatch.setattr(sys, "argv", ["chaosforge", "--yaml", "legacy.yaml"])
    cli.main()
    cli.execute_yaml_campaign.assert_called_once_with("legacy.yaml")

    monkeypatch.setattr(cli, "interactive_main", MagicMock())
    monkeypatch.setattr(sys, "argv", ["chaosforge"])
    cli.main()
    cli.interactive_main.assert_called_once_with()


@pytest.mark.parametrize("command", ["validate", "plan", "run"])
def test_main_commands_require_file(monkeypatch, command):
    monkeypatch.setattr(sys, "argv", ["chaosforge", command])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


@pytest.fixture
def aks_ui(monkeypatch):
    for name in ("title", "info", "warning", "error", "pause"):
        monkeypatch.setattr(aks, name, MagicMock())
    monkeypatch.setattr(aks, "console", MagicMock())


def test_aks_dead_ends_and_empty_choice_navigation(monkeypatch, aks_ui):
    discovery = MagicMock()
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(aks.context, "aks_kube_context", None)
    with pytest.raises(aks.BackToMainMenu):
        aks._collect_aks_inputs({"name": "x", "inputs": [{"name": "aks_context", "type": "azure_aks_cluster"}]})

    monkeypatch.setattr(aks.context, "aks_kube_context", "ctx")
    monkeypatch.setattr(aks.context, "azure_subscription", "sub")
    monkeypatch.setattr(aks.context, "azure_resource_group", "rg")
    monkeypatch.setattr(aks.context, "aks_cluster_name", "cluster")
    for field_type, method in (("azure_aks_node", "list_nodes"), ("azure_aks_zone", "list_zones")):
        getattr(discovery, method).return_value = []
        with pytest.raises(aks.BackToMainMenu):
            aks._collect_aks_inputs({
                "name": "x", "inputs": [
                    {"name": "aks_context", "type": "azure_aks_cluster"},
                    {"name": "target", "type": field_type},
                ],
            })

    discovery.list_namespaces.return_value = []
    discovery.last_error = None
    with pytest.raises(aks.BackToMainMenu):
        aks._collect_aks_inputs({
            "name": "x", "inputs": [
                {"name": "aks_context", "type": "azure_aks_cluster"},
                {"name": "namespace", "type": "azure_aks_namespace"},
            ],
        })

    monkeypatch.setattr(aks, "prompt", MagicMock(side_effect=["bad", "1"]))
    with pytest.raises(aks._BackStep):
        aks._empty_result_choice("none")
    aks.error.assert_called_with("Invalid selection")
    monkeypatch.setattr(aks, "prompt", MagicMock(return_value="m"))
    with pytest.raises(aks.BackToMainMenu):
        aks._empty_result_choice("none")


def test_aks_time_integer_text_and_container_validation(monkeypatch, aks_ui):
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock())
    prompts = iter(["wrong", "", "bad", "6", "4", "", "n"])
    monkeypatch.setattr(aks, "prompt", lambda *_: next(prompts))
    result = aks._collect_aks_inputs({
        "id": "aks-clock-skew-forward",
        "name": "Clock",
        "inputs": [
            {"name": "offset", "label": "Offset", "type": "time_offset", "default": "5m"},
            {"name": "count", "label": "Count", "type": "integer", "min": 1, "max": 5},
            {"name": "optional", "label": "Optional", "required": False},
        ],
    })
    assert result == {"offset": "+5m", "count": 4, "optional": "", "dry_run": "false"}
    assert aks.error.call_count == 3

    discovery = MagicMock()
    discovery.list_containers.return_value = []
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock(return_value=discovery))
    monkeypatch.setattr(aks, "prompt", MagicMock(side_effect=["manual", "y"]))
    result = aks._collect_aks_inputs({
        "name": "Container", "inputs": [
            {"name": "container_name", "type": "azure_aks_container"},
        ],
    })
    assert result["container_name"] == "manual"
    assert result["dry_run"] == "true"


def test_aks_back_at_first_input_and_main_menu_from_fields(monkeypatch, aks_ui):
    monkeypatch.setattr(aks, "AzureAKSDiscovery", MagicMock())
    monkeypatch.setattr(aks, "prompt", MagicMock(return_value="0"))
    assert aks._collect_aks_inputs({
        "name": "Integer", "inputs": [{"name": "count", "label": "Count", "type": "integer"}]
    }) is None

    for field in (
        {"name": "offset", "label": "Offset", "type": "time_offset", "default": "5m"},
        {"name": "count", "label": "Count", "type": "integer"},
        {"name": "text", "label": "Text"},
    ):
        monkeypatch.setattr(aks, "prompt", MagicMock(return_value="m"))
        with pytest.raises(aks.BackToMainMenu):
            aks._collect_aks_inputs({"id": "aks-clock-skew-forward", "name": "x", "inputs": [field]})


def test_resource_selector_asg_and_uncovered_child_routes(monkeypatch):
    selector = object.__new__(resource_selector.ResourceSelector)
    selector.discovery = MagicMock(region="us-east-1")
    autoscaling = MagicMock()
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"Instances": [
            {"LifecycleState": "Pending", "HealthStatus": "Healthy", "InstanceId": "i-old"},
            {"LifecycleState": "InService", "HealthStatus": "Healthy", "InstanceId": "i-good"},
        ]}]
    }
    monkeypatch.setattr("boto3.client", MagicMock(return_value=autoscaling))
    selector.discovery.list_available_ec2_ebs_volumes.return_value = [{"name": "data", "id": "vol-1"}]
    assert selector.list_available_ebs_volumes_for_asg("") == []
    autoscaling.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": []}
    assert selector.list_available_ebs_volumes_for_asg("asg") == []
    autoscaling.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [{"Instances": []}]}
    assert selector.list_available_ebs_volumes_for_asg("asg") == []
    autoscaling.describe_auto_scaling_groups.return_value["AutoScalingGroups"][0]["Instances"] = [
        {"LifecycleState": "InService", "HealthStatus": "Healthy", "InstanceId": "i-good"}
    ]
    assert selector.list_available_ebs_volumes_for_asg("asg")[0]["id"] == "vol-1"
    selector.discovery.list_available_ec2_ebs_volumes.assert_called_with("i-good")

    monkeypatch.setattr(resource_selector, "title", MagicMock())
    monkeypatch.setattr(resource_selector, "menu", MagicMock())
    monkeypatch.setattr(selector, "_select_resource", MagicMock(side_effect=lambda rows, _: rows[0]))
    assert selector.select_available_ebs_volume_for_asg("asg")["id"] == "vol-1"

    cases = [
        ("ec2", "ebs-volume", "list_ec2_ebs_volumes", "parent"),
        ("ec2", "ebs-volume-available", "list_available_ec2_ebs_volumes", "parent"),
        ("eks", "chaos-physical-machine", "list_chaos_physical_machines", "cluster"),
        ("eks-pod", "eks-volume", "list_eks_volumes", ("cluster", "ns", "pod")),
    ]
    for parent_type, child_type, method, parent in cases:
        getattr(selector.discovery, method).return_value = [{"name": child_type}]
        selected = selector.select_child(parent_type, parent, child_type)
        assert selected["name"] == child_type


def test_input_engine_asg_and_child_resource_enrichment(monkeypatch):
    selector = MagicMock()
    selector.select_available_ebs_volume_for_asg.return_value = {
        "id": "vol-1", "device_name": "/dev/xvdf"
    }
    monkeypatch.setattr(input_engine, "ResourceSelector", MagicMock(return_value=selector))
    monkeypatch.setattr(input_engine, "title", MagicMock())
    metadata = {"name": "ASG volume", "inputs": [
        {"name": "asg", "label": "ASG", "type": "aws_resource", "resource_type": "autoscaling-group", "return": "id"},
        {"name": "volume", "label": "Volume", "type": "aws_resource", "resource_type": "ebs-volume-asg-available", "parent": "asg", "return": "id"},
    ]}
    selector.select.return_value = {"id": "asg-1"}
    result = input_engine.collect_inputs(metadata)
    assert result["volume"] == "vol-1"
    assert result["device_name"] == "/dev/xvdf"
    selector.select_available_ebs_volume_for_asg.assert_called_once_with("asg-1")

    selector.reset_mock()
    selector.select.side_effect = [{"name": "cluster"}, {"name": "namespace"}, {"name": "pod"}]
    selector.select_child.side_effect = [
        {"name": "deployment", "replicas": 3},
        {"name": "volume"},
    ]
    metadata = {"name": "EKS", "inputs": [
        {"name": "eks_cluster", "label": "Cluster", "type": "aws_resource", "resource_type": "eks"},
        {"name": "namespace", "label": "Namespace", "type": "aws_resource", "resource_type": "eks-namespace"},
        {"name": "deployment", "label": "Deployment", "type": "aws_resource", "resource_type": "eks-deployment", "parent": "namespace"},
        {"name": "pod", "label": "Pod", "type": "aws_resource", "resource_type": "eks-pod"},
        {"name": "volume", "label": "Volume", "type": "aws_resource", "resource_type": "eks-volume", "parent": "pod"},
    ]}
    result = input_engine.collect_inputs(metadata)
    assert result["original_replicas"] == 3
    assert selector.select_child.call_args_list[0].args[1] == ("cluster", "namespace")
    assert selector.select_child.call_args_list[1].args[1] == ("cluster", "namespace", "pod")


def test_kubernetes_remaining_get_guards_and_api_results():
    api = MagicMock()
    api.sanitize_for_serialization.side_effect = lambda value: value
    v1, apps, policy, custom = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    v1.read_namespaced_pod.return_value = {"metadata": {"name": "pod"}}
    v1.read_namespaced_service.return_value = {"metadata": {"name": "svc"}}
    v1.read_namespaced_endpoints.return_value = {"metadata": {"name": "ep"}}
    v1.list_namespaced_event.return_value = {"items": []}
    policy.list_namespaced_pod_disruption_budget.return_value = {"items": []}
    custom.get_namespaced_custom_object.return_value = {"metadata": {"name": "fault"}}
    custom.list_cluster_custom_object.return_value = {"items": []}
    with patch.object(k8s, "_get_api_client", return_value=api), \
         patch.object(k8s.client, "CoreV1Api", return_value=v1), \
         patch.object(k8s.client, "AppsV1Api", return_value=apps), \
         patch.object(k8s.client, "PolicyV1Api", return_value=policy), \
         patch.object(k8s.client, "CustomObjectsApi", return_value=custom):
        assert k8s._dispatch_get("pod", ["pod", "-n", "ns", "-o", "json"], "ctx").returncode == 0
        assert k8s._dispatch_get("deployment", ["dep"], "ctx") is None
        assert k8s._dispatch_get("replicaset", [], "ctx") is None
        assert k8s._dispatch_get("service", ["svc", "-n", "ns"], "ctx").returncode == 0
        assert k8s._dispatch_get("service", [], "ctx") is None
        assert k8s._dispatch_get("endpoints", ["ep", "-n", "ns"], "ctx").returncode == 0
        assert k8s._dispatch_get("pdb", [], "ctx") is None
        assert k8s._dispatch_get("pdb", ["-n", "ns"], "ctx").returncode == 0
        assert k8s._dispatch_get("events", [], "ctx") is None
        assert k8s._dispatch_get("events", ["-n", "ns"], "ctx").returncode == 0
        assert k8s._dispatch_get("podchaos", ["fault"], "ctx") is None
        assert k8s._dispatch_get("podchaos", ["fault", "-n", "ns"], "ctx").returncode == 0
        assert k8s._dispatch_get("podchaos", ["--all-namespaces"], "ctx").returncode == 0
        assert k8s._dispatch_get("secret", [], "ctx") is None


def test_kubernetes_mutation_guards_and_error_outcomes():
    with pytest.raises(k8s._JsonPathUnsupported):
        k8s._resolve_path_steps("items[")
    with pytest.raises(k8s._JsonPathUnsupported):
        k8s._apply_index([[]], "unsupported")
    assert k8s._custom_columns_get("", [], False) is None

    assert k8s._dispatch_delete("secret", [], "ctx") is None
    assert k8s._dispatch_delete("pod", ["pod"], "ctx") is None
    assert k8s._dispatch_patch("node", ["n", "extra", "--type=json", "-p=[]"], "ctx") is None
    assert k8s._dispatch_patch("node", ["n", "-p=[]"], "ctx") is None
    assert k8s._dispatch_patch("deployment", ["d", "--type=json", "-p=[]"], "ctx") is None
    assert k8s._dispatch_taint(["nodes", "n"], "ctx") is None
    assert k8s._dispatch_taint(["nodes", "n", "a=x:NoSchedule", "b=y:NoExecute"], "ctx") is None
    assert k8s._dispatch_rollout("restart", ["pod/x"], "ctx") is None
    assert k8s._dispatch_rollout("restart", ["deployment/x", "--bad"], "ctx") is None
    assert k8s._dispatch_rollout("restart", ["deployment/x"], "ctx") is None

    api, v1, apps = MagicMock(), MagicMock(), MagicMock()
    with patch.object(k8s, "_get_api_client", return_value=api), \
         patch.object(k8s.client, "CoreV1Api", return_value=v1), \
         patch.object(k8s.client, "AppsV1Api", return_value=apps):
        assert k8s._dispatch_patch("node", ["n", "--type=json", "-p=[]"], "ctx").returncode == 0
        assert k8s._dispatch_patch("deployment", ["d", "-n", "ns", "--type=json", "-p=[]"], "ctx").returncode == 0

    v1.patch_namespace.side_effect = k8s.ApiException(status=500, reason="denied")
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(k8s.client, "CoreV1Api", return_value=v1):
        result = k8s._dispatch_label("namespace", ["ns", "key=value"], "ctx")
    assert result.stderr == "denied"

    node = SimpleNamespace(spec=SimpleNamespace(taints=[]))
    v1 = MagicMock()
    v1.read_node.return_value = node
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(k8s.client, "CoreV1Api", return_value=v1):
        assert k8s._dispatch_taint(["nodes", "n", "dedicated=batch:NoSchedule"], "ctx").returncode == 0
    assert v1.patch_node.call_args.args[1]["spec"]["taints"][0]["value"] == "batch"


def test_kubernetes_rollout_apply_top_drain_and_context_errors(tmp_path):
    apps = MagicMock()
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "AppsV1Api", return_value=apps
    ):
        assert k8s._dispatch_rollout(
            "restart", ["deployment/api", "-n", "default", "--timeout=bad"], "ctx"
        ).returncode == 0
    apps.patch_namespaced_deployment.assert_called_once()

    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text('{"kind": "Pod", "metadata": {"name": "pod"}}')
    assert k8s._dispatch_apply(["-f", str(bad_manifest)], "ctx") is None
    manifest = tmp_path / "pod.json"
    manifest.write_text('{"kind":"Pod","metadata":{"name":"pod","namespace":"ns"}}')
    v1 = MagicMock()
    v1.create_namespaced_pod.side_effect = k8s.ApiException(status=409)
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        assert k8s._dispatch_apply(["-f", str(manifest)], "ctx").returncode == 0
    v1.replace_namespaced_pod.assert_called_once()

    assert k8s._dispatch_top(["pods", "-l", "app=x"], "ctx") is None
    assert k8s._dispatch_top(["nodes", "-l", "app=x"], "ctx") is None
    assert k8s._dispatch_top(["node"], "ctx") is None
    custom = MagicMock()
    custom.list_namespaced_custom_object.side_effect = k8s.ApiException(reason="metrics missing")
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "CustomObjectsApi", return_value=custom
    ):
        assert "metrics missing" in k8s._dispatch_top(["pods", "-n", "ns"], "ctx").stderr

    pod = SimpleNamespace(metadata=SimpleNamespace(name="p", namespace="ns"))
    core = MagicMock()
    core.create_namespaced_pod_eviction.side_effect = k8s.ApiException(status=500, reason="denied")
    assert k8s._drain_evict_pod(core, pod, None) == (False, "denied")

    core = MagicMock()
    core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[SimpleNamespace(
        status=SimpleNamespace(phase="Running"),
        metadata=SimpleNamespace(name="p", namespace="ns", owner_references=[]),
    )])
    core.read_namespaced_pod.side_effect = [None, k8s.ApiException(status=404)]
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "CoreV1Api", return_value=core
    ), patch.object(k8s, "_drain_evict_pod", return_value=(True, "")), patch(
        "time.monotonic", side_effect=[0, 0, 0, 0, 0, 2]
    ), patch("time.sleep"):
        result = k8s._dispatch_drain(
            ["node", "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--timeout=5s"],
            "ctx",
        )
    assert result.stdout == "node/node drained\n"
    assert core.patch_node.called

    with patch.object(k8s, "_get_api_client", side_effect=k8s.ApiException(reason="config denied")):
        result = k8s._dispatch_drain(
            ["node", "--ignore-daemonsets", "--delete-emptydir-data", "--force"], "ctx"
        )
    assert result.stderr == "config denied"


def test_kubernetes_cache_kubeconfig_and_dispatch_edges(monkeypatch):
    k8s._client_cache.clear()
    cached = MagicMock()
    k8s._client_cache["ctx"] = cached
    assert k8s._get_api_client("ctx") is cached

    monkeypatch.setenv("KUBECONFIG", "/first:/second")
    assert k8s._kubeconfig_path() == "/first"
    monkeypatch.delenv("KUBECONFIG")
    assert k8s._kubeconfig_path().endswith("/.kube/config")
    with patch.object(k8s.config, "list_kube_config_contexts", side_effect=OSError()):
        assert k8s.list_kube_contexts() == []

    data = "contexts:\n- name: other\ncurrent-context: other\n"
    with patch.object(k8s, "_kubeconfig_path", return_value="config"), patch(
        "builtins.open", mock_open(read_data=data)
    ):
        assert k8s.delete_kube_context("missing") is False
        assert k8s.set_current_kube_context("missing") is False

    assert k8s.dispatch_kubectl((), "ctx") is None
    assert k8s.dispatch_kubectl(("unknown",), "ctx") is None
    with patch.object(k8s, "_dispatch_get", return_value=k8s._ok("pods")) as dispatched:
        assert k8s.dispatch_kubectl(("get", "pods"), "ctx").stdout == "pods"
    dispatched.assert_called_once_with("pods", [], "ctx")


def test_kubernetes_remaining_api_failures_are_reported_or_fall_back():
    api = MagicMock()
    assert k8s._dispatch_delete("pod", ["-n", "ns"], "ctx") is None

    custom = MagicMock()
    custom.delete_namespaced_custom_object.side_effect = k8s.ApiException(
        status=403, reason="delete denied"
    )
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(
        k8s.client, "CustomObjectsApi", return_value=custom
    ):
        result = k8s._dispatch_delete("podchaos", ["fault", "-n", "ns"], "ctx")
    assert result.returncode == 1
    assert result.stderr == "delete denied"

    v1 = MagicMock()
    v1.patch_node.side_effect = RuntimeError("transport")
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        assert k8s._dispatch_patch(
            "node", ["node", "--type=json", "-p=[]"], "ctx"
        ) is None

    v1 = MagicMock()
    v1.patch_namespace.side_effect = RuntimeError("transport")
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        assert k8s._dispatch_label("namespace", ["ns", "key-"], "ctx") is None

    v1 = MagicMock()
    v1.read_node.side_effect = k8s.ApiException(status=500, reason="taint denied")
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        result = k8s._dispatch_taint(["nodes", "node", "key:NoSchedule"], "ctx")
    assert result.returncode == 1
    assert result.stderr == "taint denied"

    v1 = MagicMock()
    v1.patch_node.side_effect = k8s.ApiException(status=404)
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        assert k8s._dispatch_cordon(False, ["node"], "ctx").stderr == "not found"

    v1.patch_node.side_effect = k8s.ApiException(status=500, reason="cordon denied")
    with patch.object(k8s, "_get_api_client", return_value=api), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        assert k8s._dispatch_cordon(False, ["node"], "ctx").stderr == "cordon denied"


def test_kubernetes_rollout_waits_until_deployment_is_ready():
    pending = SimpleNamespace(
        spec=SimpleNamespace(replicas=2),
        status=SimpleNamespace(
            updated_replicas=1,
            replicas=1,
            available_replicas=1,
            observed_generation=1,
        ),
        metadata=SimpleNamespace(generation=2),
    )
    ready = SimpleNamespace(
        spec=SimpleNamespace(replicas=2),
        status=SimpleNamespace(
            updated_replicas=2,
            replicas=2,
            available_replicas=2,
            observed_generation=2,
        ),
        metadata=SimpleNamespace(generation=2),
    )
    apps = MagicMock()
    apps.read_namespaced_deployment.side_effect = [pending, ready]
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "AppsV1Api", return_value=apps
    ), patch("time.time", side_effect=[0, 1, 2]), patch("time.sleep") as sleep:
        result = k8s._dispatch_rollout(
            "status", ["deployment/api", "-n", "default", "--timeout=10s"], "ctx"
        )
    assert result.returncode == 0
    assert "successfully rolled out" in result.stdout
    sleep.assert_called_once_with(2)
