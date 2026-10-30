import json
from contextlib import nullcontext
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.common.azure_cli import azure_cli_command
from chaosforge.interfaces.cli.interactive import azure_aks_service as aks_service
from chaosforge.interfaces.cli.interactive import platform_selector as platform
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.azure.components.aks import discovery
from chaosforge.providers.azure.components.aks import kubernetes as k8s


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _restore_session_context():
    names = (
        "azure_subscription",
        "azure_account_name",
        "azure_resource_group",
        "aks_cluster_name",
        "azure_location",
        "aks_kube_context",
    )
    original = {name: getattr(context, name) for name in names}
    yield
    for name, value in original.items():
        setattr(context, name, value)


def test_cache_helpers_and_session_context_cleanup(tmp_path):
    cache = tmp_path / "azure.json"
    data = {"subscription_id": "sub", "cluster_name": "aks"}
    with patch.object(platform, "_AZURE_CACHE_FILE", str(cache)):
        assert platform._load_azure_cache() is None
        platform._save_azure_cache(data)
        assert platform._load_azure_cache() == data
        cache.write_text("not-json")
        assert platform._load_azure_cache() is None

    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.delete_kube_context",
        return_value=True,
    ), patch.object(platform.subprocess, "run") as run:
        platform._remove_kube_context("temporary")
    run.assert_not_called()

    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.delete_kube_context",
        side_effect=RuntimeError("bad config"),
    ), patch.object(platform.subprocess, "run") as run:
        platform._remove_kube_context("temporary")
    run.assert_not_called()


def test_cached_context_loading_requires_complete_identity():
    selector = platform.PlatformSelector()
    context.azure_subscription = None
    with patch(
        "chaosforge.providers.azure.discovery.resolve_subscription_id",
        return_value="sub",
    ), patch.object(
        platform,
        "_load_azure_cache",
        return_value={
            "subscription_id": "sub",
            "account_name": "Engineering",
            "resource_group": "rg",
            "cluster_name": "aks",
            "location": "eastus",
            "kube_context": "aks-context",
        },
    ):
        selector._load_cached_azure_context()

    assert context.azure_subscription == "sub"
    assert context.azure_account_name == "Engineering"
    assert context.azure_resource_group == "rg"
    assert context.aks_cluster_name == "aks"
    assert context.azure_location == "eastus"
    assert context.aks_kube_context == "aks-context"

    context.azure_subscription = "unchanged"
    with patch.object(platform, "_load_azure_cache", return_value={"subscription_id": "sub"}):
        selector._load_cached_azure_context()
    assert context.azure_subscription == "unchanged"


def test_ensure_azure_context_existing_missing_identity_and_successful_refresh():
    selector = platform.PlatformSelector()
    context.aks_kube_context = "cached-context"
    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
        return_value=["cached-context"],
    ), patch.object(platform.subprocess, "run") as run:
        assert selector.ensure_azure_kube_context() is True
    run.assert_not_called()

    context.aks_kube_context = None
    context.azure_subscription = None
    context.azure_resource_group = "rg"
    context.aks_cluster_name = "aks"
    assert selector.ensure_azure_kube_context() is False

    context.azure_subscription = "sub"
    context.azure_account_name = "Engineering"
    context.azure_location = "eastus"
    with patch.object(platform.subprocess, "run", return_value=_result()) as run, patch.object(
        platform, "_save_azure_cache"
    ) as save, patch.object(platform, "info") as info:
        assert selector.ensure_azure_kube_context() is True

    assert context.aks_kube_context == "aks"
    assert run.call_args.args[0][:4] == azure_cli_command(
        "aks", "get-credentials", "--subscription"
    )
    assert save.call_args.args[0]["kube_context"] == "aks"
    assert "credentials refreshed" in info.call_args.args[0].lower()


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError(), "not found"),
        (TimeoutError("slow"), "slow"),
        (_result(returncode=1, stderr="denied"), "denied"),
    ],
)
def test_ensure_azure_context_reports_refresh_failures(failure, message):
    selector = platform.PlatformSelector()
    context.aks_kube_context = "missing"
    context.azure_subscription = "sub"
    context.azure_resource_group = "rg"
    context.aks_cluster_name = "aks"
    run_effect = failure if isinstance(failure, BaseException) else None
    run_result = None if run_effect else failure

    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
        side_effect=RuntimeError("invalid kubeconfig"),
    ), patch.object(
        platform.subprocess, "run", side_effect=run_effect, return_value=run_result
    ), patch.object(platform, "error") as error:
        assert selector.ensure_azure_kube_context() is False
    assert message in error.call_args.args[0].lower()


def test_prompt_azure_details_selects_running_cluster_and_existing_context():
    selector = platform.PlatformSelector()
    clusters = [
        {
            "name": "sleeping-aks",
            "resourceGroup": "rg-old",
            "location": "westus",
            "powerState": {"code": "Stopped"},
        },
        {
            "name": "prod-aks",
            "resourceGroup": "rg-prod",
            "location": "eastus2",
            "powerState": {"code": "Running"},
        },
    ]
    calls = [
        _result(json.dumps({"name": "Engineering"})),
        _result(json.dumps(clusters)),
    ]
    answers = iter(["11111111-2222-3333-4444-555555555555", "bad", "1", "2", "bad", "1"])

    with patch.object(platform, "prompt", side_effect=lambda *_: next(answers)), patch.object(
        platform.subprocess, "run", side_effect=calls
    ) as run, patch(
        "chaosforge.interfaces.cli.interactive.ui.spinner.spinner",
        side_effect=lambda *_: nullcontext(),
    ), patch(
        "chaosforge.interfaces.cli.interactive.ui.tables.menu"
    ) as menu, patch(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
        return_value=["unrelated", "prod-aks-admin"],
    ), patch.object(platform, "_save_azure_cache") as save, patch.object(
        platform, "error"
    ) as error:
        assert selector._prompt_azure_details() is True

    assert run.call_count == 2
    assert menu.call_count >= 3
    assert error.call_count == 3
    assert context.azure_account_name == "Engineering"
    assert context.azure_resource_group == "rg-prod"
    assert context.aks_cluster_name == "prod-aks"
    assert context.azure_location == "eastus2"
    assert context.aks_kube_context == "prod-aks-admin"
    assert save.call_args.args[0]["kube_context"] == "prod-aks-admin"


def test_prompt_azure_details_manual_fallback_fetches_ephemeral_credentials():
    selector = platform.PlatformSelector()
    account = _result(json.dumps({"name": "Sandbox"}))
    list_failed = _result(returncode=1, stderr="listing unavailable\nmore detail")
    cluster = _result(json.dumps({"location": "centralus"}))
    credentials = _result()
    answers = iter(["sub-id", "manual-rg", "manual-aks", "n"])

    with patch.object(platform, "prompt", side_effect=lambda *_: next(answers)), patch.object(
        platform.subprocess,
        "run",
        side_effect=[account, list_failed, cluster, credentials],
    ) as run, patch(
        "chaosforge.interfaces.cli.interactive.ui.spinner.spinner",
        side_effect=lambda *_: nullcontext(),
    ), patch(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
        return_value=[],
    ), patch.object(platform.atexit, "register") as register, patch.object(
        platform, "_save_azure_cache"
    ) as save:
        assert selector._prompt_azure_details() is True

    assert run.call_count == 4
    assert context.azure_resource_group == "manual-rg"
    assert context.aks_cluster_name == "manual-aks"
    assert context.azure_location == "centralus"
    assert context.aks_kube_context == "manual-aks"
    register.assert_called_once_with(platform._remove_kube_context, "manual-aks")
    assert save.call_args.args[0]["kube_context"] is None


@pytest.mark.parametrize(
    ("answers", "runs", "expected"),
    [
        ([""], [], "Subscription ID is required"),
        (["sub"], [FileNotFoundError()], "Azure CLI ('az') not found"),
        (["sub"], [RuntimeError("login broke")], "login broke"),
        (["sub"], [_result(returncode=1, stderr="forbidden\nextra")], "forbidden"),
    ],
)
def test_prompt_azure_details_rejects_subscription_failures(answers, runs, expected):
    selector = platform.PlatformSelector()
    with patch.object(platform, "prompt", side_effect=answers), patch.object(
        platform.subprocess, "run", side_effect=runs
    ), patch(
        "chaosforge.interfaces.cli.interactive.ui.spinner.spinner",
        side_effect=lambda *_: nullcontext(),
    ), patch.object(platform, "error") as error:
        assert selector._prompt_azure_details() is False
    assert expected in error.call_args.args[0]


def test_prompt_azure_details_manual_entry_validates_required_values():
    selector = platform.PlatformSelector()
    account = _result(json.dumps({"name": "Engineering"}))
    no_clusters = _result("[]")
    for answers, expected in [(["sub", ""], "Resource Group"), (["sub", "rg", ""], "Cluster Name")]:
        with patch.object(platform, "prompt", side_effect=answers), patch.object(
            platform.subprocess, "run", side_effect=[account, no_clusters]
        ), patch(
            "chaosforge.interfaces.cli.interactive.ui.spinner.spinner",
            side_effect=lambda *_: nullcontext(),
        ), patch.object(platform, "error") as error:
            assert selector._prompt_azure_details() is False
        assert expected in error.call_args.args[0]


@pytest.mark.parametrize(
    ("side_effect", "message"),
    [
        (FileNotFoundError(), "not found"),
        (RuntimeError("network down"), "network down"),
        (_result(returncode=1, stderr="credential denied"), "credential denied"),
    ],
)
def test_prompt_azure_details_reports_credential_fetch_failures(side_effect, message):
    selector = platform.PlatformSelector()
    responses = [
        _result(json.dumps({"name": "Engineering"})),
        _result(json.dumps([{"name": "aks", "resourceGroup": "rg", "location": "eastus"}])),
    ]
    if not isinstance(side_effect, BaseException):
        responses.append(side_effect)
        effect = responses
    else:
        effect = [*responses, side_effect]

    with patch.object(platform, "prompt", side_effect=["sub", "1"]), patch.object(
        platform.subprocess, "run", side_effect=effect
    ), patch(
        "chaosforge.interfaces.cli.interactive.ui.spinner.spinner",
        side_effect=lambda *_: nullcontext(),
    ), patch(
        "chaosforge.interfaces.cli.interactive.ui.tables.menu"
    ), patch(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
        return_value=[],
    ), patch.object(platform, "error") as error:
        assert selector._prompt_azure_details() is False
    assert message in error.call_args.args[0].lower()


@pytest.mark.parametrize(
    ("experiment_id", "value", "expected"),
    [
        ("aks-clock-skew-forward", "5m", "+5m"),
        ("aks-clock-skew-backward", "5m", "-5m"),
        ("aks-clock-skew-forward", "+10s", "+10s"),
        ("aks-clock-skew-forward", "-10s", None),
        ("aks-clock-skew-backward", "+1h", None),
        ("aks-clock-skew-backward", "0m", None),
    ],
)
def test_time_offset_normalization(experiment_id, value, expected):
    assert aks_service._normalize_time_offset(experiment_id, value) == expected


def test_picker_handles_main_menu_no_match_invalid_input_and_back():
    with patch.object(aks_service, "prompt", return_value="m"), pytest.raises(
        aks_service.BackToMainMenu
    ):
        aks_service._pick("Item", ["alpha"])

    with patch.object(
        aks_service, "prompt", side_effect=["s", "missing", "wrong", "0"]
    ), patch.object(aks_service, "error") as error, pytest.raises(aks_service._BackStep):
        aks_service._pick("Item", ["alpha"])
    assert [call.args[0] for call in error.call_args_list] == [
        "No matches for 'missing'",
        "Invalid selection",
    ]


def test_discovery_additional_error_and_ownership_branches():
    service = discovery.AzureAKSDiscovery()
    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts",
        side_effect=RuntimeError("bad config"),
    ), patch.object(
        discovery.subprocess,
        "run",
        side_effect=[_result(returncode=1), RuntimeError("az unavailable")],
    ):
        assert service.list_contexts() == []

    with patch.object(discovery, "_kubectl", return_value=_result(returncode=1)):
        assert service.list_containers("ctx", "ns", "dep") == []
        assert service.list_pod_containers("ctx", "ns", "pod") == []
        assert service.list_pods("ctx", "ns") == []
        assert service.list_nodes("ctx") == []
        assert service.list_zones("ctx") == []

    with patch.object(discovery, "_kubectl", return_value=_result(stdout="not-json")):
        assert service.get_pod_label("ctx", "ns", "pod") == ("app", "pod")

    with patch.object(discovery, "_kubectl_json", side_effect=[{"items": [{
        "metadata": {
            "name": "rs",
            "ownerReferences": [{"kind": "Deployment", "name": "dep"}],
        }
    }]}, None]):
        assert service.get_owned_pod_names("ctx", "ns", "dep") == []

    with patch.object(discovery, "_kubectl_json", return_value=None):
        assert service.get_deployment_for_pod("ctx", "ns", "pod") is None


def test_kubernetes_remaining_parser_output_and_dispatch_guards():
    assert k8s._jsonpath_get('{range .items[*]}text{.name}{end}', {"items": []}) is None
    assert k8s._jsonpath_get('{range .items[*]}{.name', {"items": []}) is None
    assert k8s._custom_columns_get("NAME:", [], False) is None
    assert k8s._custom_columns_get("", [], False) is None
    assert k8s._custom_columns_get(r"NAME:.labels.app\.name", [{}], False) == "NAME\n<none>"
    assert k8s._apply_output(
        [], False, {"output": "custom-columns=NAME:", "no_headers": False}
    ) is None
    assert k8s._dispatch_get("deployment", ["dep"], "ctx") is None
    assert k8s._dispatch_get("replicaset", [], "ctx") is None
    assert k8s._dispatch_get("service", ["svc"], "ctx") is None
    assert k8s._dispatch_get("endpoints", ["ep", "-n", "ns", "--watch"], "ctx") is None
    assert k8s._dispatch_get("pdb", [], "ctx") is None
    assert k8s._dispatch_get("events", [], "ctx") is None
    assert k8s._dispatch_get("crd", [], "ctx") is None
    assert k8s._dispatch_get("podchaos", ["fault"], "ctx") is None
    assert k8s._dispatch_get("secret", [], "ctx") is None
    assert k8s._dispatch_delete("pod", ["-n", "ns"], "ctx") is None
    assert k8s._dispatch_exec(["pod", "-n", "ns", "--"], "ctx") is None
    assert k8s._dispatch_patch("secret", ["x", "--type=json", "-p=[]"], "ctx") is None
    assert k8s._dispatch_patch("node", [], "ctx") is None
    assert k8s._dispatch_patch("node", ["n", "-p=bad", "--type=json"], "ctx") is None
    assert k8s._dispatch_label("namespace", [], "ctx") is None
    assert k8s._dispatch_label("namespace", ["ns", "a=b", "c=d"], "ctx") is None
    assert k8s._dispatch_taint(["nodes", "node", "invalid"], "ctx") is None
    assert k8s._dispatch_rollout("restart", ["deployment/dep", "-n", "ns", "extra"], "ctx") is None
    assert k8s._dispatch_create("namespace", ["one", "two"], "ctx") is None
    assert k8s._dispatch_apply(["-f", "/missing"], "ctx") is None


def test_kubernetes_api_errors_rollout_timeout_and_drain_timeout():
    with patch.object(k8s, "_get_api_client", side_effect=RuntimeError("config")):
        assert k8s._dispatch_get("pods", ["-n", "ns"], "ctx") is None

    v1 = MagicMock()
    v1.patch_namespace.side_effect = k8s.ApiException(status=404)
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        assert k8s._dispatch_label("namespace", ["ns", "a=b"], "ctx").stderr == "not found"

    dep = SimpleNamespace(
        spec=SimpleNamespace(replicas=2),
        status=SimpleNamespace(
            updated_replicas=1,
            replicas=1,
            available_replicas=1,
            observed_generation=1,
        ),
        metadata=SimpleNamespace(generation=2),
    )
    apps = MagicMock()
    apps.read_namespaced_deployment.return_value = dep
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "AppsV1Api", return_value=apps
    ), patch("time.time", side_effect=[0, 1]):
        result = k8s._dispatch_rollout(
            "status", ["deployment/dep", "-n", "ns", "--timeout=0s"], "ctx"
        )
    assert result.returncode == 1
    assert "timed out" in result.stderr

    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="blocked", namespace="ns", owner_references=[]),
        status=SimpleNamespace(phase="Running"),
    )
    v1 = MagicMock()
    v1.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=[pod])
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ), patch.object(k8s, "_drain_evict_pod", return_value=(False, "PDB")), patch(
        "time.monotonic", side_effect=[0, 0, 2]
    ), patch("time.sleep"):
        result = k8s._dispatch_drain(
            [
                "node",
                "--ignore-daemonsets",
                "--delete-emptydir-data",
                "--force",
                "--timeout=1s",
            ],
            "ctx",
        )
    assert result.returncode == 1
    assert "ns/blocked" in result.stderr


def test_kubernetes_exec_and_create_report_api_errors():
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "CoreV1Api", return_value=MagicMock()
    ), patch.object(k8s, "_ws_stream", return_value=SimpleNamespace(
        run_forever=lambda **_: None,
        read_stdout=lambda **_: "out",
        read_stderr=lambda **_: "err",
        returncode=None,
        close=lambda: None,
    )):
        result = k8s._dispatch_exec(["pod", "-n", "ns", "--", "true"], "ctx")
    assert (result.returncode, result.stdout, result.stderr) == (0, "out", "err")

    v1 = MagicMock()
    v1.create_namespace.side_effect = RuntimeError("transport")
    with patch.object(k8s, "_get_api_client", return_value=MagicMock()), patch.object(
        k8s.client, "CoreV1Api", return_value=v1
    ):
        assert k8s._dispatch_create("namespace", ["ns"], "ctx") is None


def test_kubeconfig_write_failures_after_successful_reads(tmp_path):
    config_file = tmp_path / "config"
    contents = "contexts:\n- name: ctx\ncurrent-context: ctx\n"
    config_file.write_text(contents)

    reader_then_failure = mock_open(read_data=contents)
    reader_then_failure.side_effect = [reader_then_failure.return_value, OSError("read only")]
    with patch.object(k8s, "_kubeconfig_path", return_value=str(config_file)), patch(
        "builtins.open", reader_then_failure
    ):
        assert k8s.delete_kube_context("ctx") is False

    reader_then_failure = mock_open(read_data=contents)
    reader_then_failure.side_effect = [reader_then_failure.return_value, OSError("read only")]
    with patch.object(k8s, "_kubeconfig_path", return_value=str(config_file)), patch(
        "builtins.open", reader_then_failure
    ):
        assert k8s.set_current_kube_context("ctx") is False
