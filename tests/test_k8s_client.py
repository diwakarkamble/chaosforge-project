import json
from unittest.mock import MagicMock, patch

from chaosforge.providers.azure.components.aks import kubernetes as k8s_client


def _api_client_with_serialized(serialized):
    api_client = MagicMock()
    api_client.sanitize_for_serialization.return_value = serialized
    return api_client


def test_dispatch_get_nodes_with_label_selector_only_returns_matching_nodes():
    zone3_node = {
        "metadata": {
            "name": "aks-default3-abc-vmss000006",
            "labels": {"topology.kubernetes.io/zone": "eastus-3"},
        },
    }
    api_client = _api_client_with_serialized({"items": [zone3_node]})
    mock_v1 = MagicMock()
    mock_v1.list_node.return_value = MagicMock()

    with patch.object(k8s_client, "_get_api_client", return_value=api_client), patch.object(
        k8s_client.client, "CoreV1Api", return_value=mock_v1,
    ):
        result = k8s_client._dispatch_get(
            "nodes",
            [
                "-l",
                "topology.kubernetes.io/zone=eastus-3",
                "-o",
                'jsonpath={range .items[*]}{.metadata.name}{"\\n"}{end}',
            ],
            "ctx",
        )

    assert result is not None
    assert result.returncode == 0
    mock_v1.list_node.assert_called_once_with(
        label_selector="topology.kubernetes.io/zone=eastus-3",
        field_selector=None,
    )


def test_dispatch_get_nodes_without_selector_still_lists_all_nodes():
    api_client = _api_client_with_serialized({"items": []})
    mock_v1 = MagicMock()
    mock_v1.list_node.return_value = MagicMock()

    with patch.object(k8s_client, "_get_api_client", return_value=api_client), patch.object(
        k8s_client.client, "CoreV1Api", return_value=mock_v1,
    ):
        result = k8s_client._dispatch_get("nodes", [], "ctx")

    assert result is not None
    assert result.returncode == 0
    mock_v1.list_node.assert_called_once_with(label_selector=None, field_selector=None)


def test_dispatch_get_pod_by_name_without_namespace_returns_none():
    # _get_api_client() is called unconditionally at the top of
    # _dispatch_get() before the per-resource name/namespace guard runs, so
    # it IS invoked here even though the pod branch immediately bails out
    # with None afterward (signalling the caller to fall back to kubectl).
    with patch.object(k8s_client, "_get_api_client") as get_api_client:
        result = k8s_client._dispatch_get("pod", ["api-pod"], "ctx")

    assert result is None
    get_api_client.assert_called_once_with("ctx")


# ── _get_api_client caching ─────────────────────────────────────────────────

def test_get_api_client_caches_per_context():
    k8s_client._client_cache.clear()
    fake_cfg = MagicMock()
    fake_api_client = MagicMock()
    with patch.object(k8s_client.client, "Configuration", return_value=fake_cfg), \
         patch.object(k8s_client.config, "load_kube_config") as load_cfg, \
         patch.object(k8s_client.client, "ApiClient", return_value=fake_api_client):
        first = k8s_client._get_api_client("ctx-a")
        second = k8s_client._get_api_client("ctx-a")

    assert first is second
    load_cfg.assert_called_once_with(context="ctx-a", client_configuration=fake_cfg)
    k8s_client._client_cache.clear()


# ── get_pods / get_deployment ────────────────────────────────────────────────

def test_get_pods_returns_items_on_success():
    api_client = _api_client_with_serialized({"items": [{"metadata": {"name": "p1"}}]})
    mock_v1 = MagicMock()
    mock_v1.list_namespaced_pod.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=mock_v1):
        items, err = k8s_client.get_pods("ctx", "ns", "app=x", "status.phase=Running")

    assert err is None
    assert items == [{"metadata": {"name": "p1"}}]
    mock_v1.list_namespaced_pod.assert_called_once_with(
        namespace="ns", label_selector="app=x", field_selector="status.phase=Running",
    )


def test_get_pods_returns_error_on_api_exception():
    mock_v1 = MagicMock()
    mock_v1.list_namespaced_pod.side_effect = k8s_client.ApiException(reason="boom")
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=mock_v1):
        items, err = k8s_client.get_pods("ctx", "ns")

    assert items is None
    assert "boom" in err


def test_get_pods_returns_error_on_generic_exception():
    mock_v1 = MagicMock()
    mock_v1.list_namespaced_pod.side_effect = RuntimeError("network down")
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=mock_v1):
        items, err = k8s_client.get_pods("ctx", "ns")

    assert items is None
    assert "network down" in err


def test_get_deployment_returns_dict_on_success():
    api_client = _api_client_with_serialized({"metadata": {"name": "dep"}})
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        dep, err = k8s_client.get_deployment("ctx", "ns", "dep")

    assert err is None
    assert dep == {"metadata": {"name": "dep"}}


def test_get_deployment_returns_not_found_on_404():
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = k8s_client.ApiException(status=404)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        dep, err = k8s_client.get_deployment("ctx", "ns", "missing")

    assert dep is None
    assert err == "not found"


def test_get_deployment_returns_error_on_other_api_exception():
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = k8s_client.ApiException(status=500, reason="oops")
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        dep, err = k8s_client.get_deployment("ctx", "ns", "dep")

    assert dep is None
    assert "oops" in err


def test_get_deployment_returns_error_on_generic_exception():
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = RuntimeError("bad")
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        dep, err = k8s_client.get_deployment("ctx", "ns", "dep")

    assert dep is None
    assert "bad" in err


# ── kubeconfig path / context helpers ────────────────────────────────────────

def test_kubeconfig_path_uses_kubeconfig_env_first_entry(monkeypatch):
    monkeypatch.setenv("KUBECONFIG", "/tmp/a/config:/tmp/b/config")
    assert k8s_client._kubeconfig_path() == "/tmp/a/config"


def test_kubeconfig_path_falls_back_to_home_dir(monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    path = k8s_client._kubeconfig_path()
    assert path.endswith(".kube/config")


def test_list_kube_contexts_returns_names():
    with patch.object(
        k8s_client.config, "list_kube_config_contexts",
        return_value=([{"name": "ctx-a"}, {"name": "ctx-b"}], {"name": "ctx-a"}),
    ):
        assert k8s_client.list_kube_contexts() == ["ctx-a", "ctx-b"]


def test_list_kube_contexts_returns_empty_on_failure():
    with patch.object(
        k8s_client.config, "list_kube_config_contexts", side_effect=RuntimeError("no file"),
    ):
        assert k8s_client.list_kube_contexts() == []


def test_delete_kube_context_removes_matching_entry(tmp_path):
    cfg_file = tmp_path / "config"
    cfg_file.write_text(
        "contexts:\n- name: ctx-a\n- name: ctx-b\ncurrent-context: ctx-a\n"
    )
    with patch.object(k8s_client, "_kubeconfig_path", return_value=str(cfg_file)):
        assert k8s_client.delete_kube_context("ctx-a") is True

    import yaml
    data = yaml.safe_load(cfg_file.read_text())
    assert data["contexts"] == [{"name": "ctx-b"}]
    assert data["current-context"] == ""


def test_delete_kube_context_returns_false_when_context_missing(tmp_path):
    cfg_file = tmp_path / "config"
    cfg_file.write_text("contexts:\n- name: ctx-a\n")
    with patch.object(k8s_client, "_kubeconfig_path", return_value=str(cfg_file)):
        assert k8s_client.delete_kube_context("ctx-zzz") is False


def test_delete_kube_context_returns_false_when_file_unreadable():
    with patch.object(k8s_client, "_kubeconfig_path", return_value="/no/such/file"):
        assert k8s_client.delete_kube_context("ctx-a") is False


def test_set_current_kube_context_switches_to_existing_context(tmp_path):
    cfg_file = tmp_path / "config"
    cfg_file.write_text("contexts:\n- name: ctx-a\n- name: ctx-b\ncurrent-context: ctx-a\n")
    with patch.object(k8s_client, "_kubeconfig_path", return_value=str(cfg_file)):
        assert k8s_client.set_current_kube_context("ctx-b") is True

    import yaml
    data = yaml.safe_load(cfg_file.read_text())
    assert data["current-context"] == "ctx-b"


def test_set_current_kube_context_returns_false_for_unknown_context(tmp_path):
    cfg_file = tmp_path / "config"
    cfg_file.write_text("contexts:\n- name: ctx-a\n")
    with patch.object(k8s_client, "_kubeconfig_path", return_value=str(cfg_file)):
        assert k8s_client.set_current_kube_context("ctx-zzz") is False


def test_set_current_kube_context_returns_false_when_file_unreadable():
    with patch.object(k8s_client, "_kubeconfig_path", return_value="/no/such/file"):
        assert k8s_client.set_current_kube_context("ctx-a") is False


# ── dispatch_kubectl verb routing ────────────────────────────────────────────

def test_dispatch_kubectl_returns_none_for_empty_args():
    assert k8s_client.dispatch_kubectl([], "ctx") is None


def test_dispatch_kubectl_returns_none_for_unrecognized_verb():
    assert k8s_client.dispatch_kubectl(("frobnicate", "pods"), "ctx") is None


def test_dispatch_kubectl_routes_get_to_dispatch_get():
    with patch.object(k8s_client, "_dispatch_get", return_value=k8s_client._ok("x")) as m:
        result = k8s_client.dispatch_kubectl(("get", "pods", "-n", "ns"), "ctx")
    m.assert_called_once_with("pods", ["-n", "ns"], "ctx")
    assert result.stdout == "x"


def test_dispatch_kubectl_routes_delete_to_dispatch_delete():
    with patch.object(k8s_client, "_dispatch_delete", return_value=k8s_client._ok()) as m:
        k8s_client.dispatch_kubectl(("delete", "pod", "foo"), "ctx")
    m.assert_called_once_with("pod", ["foo"], "ctx")


def test_dispatch_kubectl_routes_exec_to_dispatch_exec():
    with patch.object(k8s_client, "_dispatch_exec", return_value=k8s_client._ok()) as m:
        k8s_client.dispatch_kubectl(("exec", "pod", "--", "ls"), "ctx")
    m.assert_called_once_with(["pod", "--", "ls"], "ctx")


def test_dispatch_kubectl_routes_top_to_dispatch_top():
    with patch.object(k8s_client, "_dispatch_top", return_value=k8s_client._ok()) as m:
        k8s_client.dispatch_kubectl(("top", "pods"), "ctx")
    m.assert_called_once_with(["pods"], "ctx")


# ── _dispatch_delete ─────────────────────────────────────────────────────────

def test_dispatch_delete_pod_by_name():
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_delete("pod", ["api-pod", "-n", "ns"], "ctx")

    assert result.returncode == 0
    v1.delete_namespaced_pod.assert_called_once_with("api-pod", "ns")


def test_dispatch_delete_returns_none_without_namespace():
    assert k8s_client._dispatch_delete("pod", ["api-pod"], "ctx") is None


def test_dispatch_delete_returns_none_for_unrecognized_resource():
    assert k8s_client._dispatch_delete("secret", ["foo", "-n", "ns"], "ctx") is None


def test_dispatch_delete_chaos_crd_by_name():
    custom = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_delete("networkchaos", ["exp1", "-n", "chaos-testing"], "ctx")

    assert result.returncode == 0
    custom.delete_namespaced_custom_object.assert_called_once()


def test_dispatch_delete_chaos_crd_collection_with_all_flag():
    custom = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_delete("networkchaos", ["--all", "-n", "chaos-testing"], "ctx")

    assert result.returncode == 0
    custom.delete_collection_namespaced_custom_object.assert_called_once()


def test_dispatch_delete_returns_ok_on_404_with_ignore_not_found():
    custom = MagicMock()
    custom.delete_namespaced_custom_object.side_effect = k8s_client.ApiException(status=404)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_delete(
            "networkchaos", ["exp1", "-n", "ns", "--ignore-not-found"], "ctx",
        )
    assert result.returncode == 0


def test_dispatch_delete_returns_fail_on_404_without_ignore_not_found():
    custom = MagicMock()
    custom.delete_namespaced_custom_object.side_effect = k8s_client.ApiException(status=404)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_delete("networkchaos", ["exp1", "-n", "ns"], "ctx")
    assert result.returncode == 1


# ── _dispatch_exec ───────────────────────────────────────────────────────────

def test_dispatch_exec_runs_command_and_returns_output():
    ws = MagicMock()
    ws.read_stdout.return_value = "hello\n"
    ws.read_stderr.return_value = ""
    ws.returncode = 0
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s_client, "_ws_stream", return_value=ws):
        result = k8s_client._dispatch_exec(
            ["pod-a", "-n", "ns", "--", "echo", "hi"], "ctx",
        )
    assert result.returncode == 0
    assert result.stdout == "hello\n"


def test_dispatch_exec_returns_none_for_unrecognized_shape():
    assert k8s_client._dispatch_exec(["pod-a"], "ctx") is None


def test_dispatch_exec_returns_fail_on_api_exception():
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s_client, "_ws_stream", side_effect=k8s_client.ApiException(reason="nope")):
        result = k8s_client._dispatch_exec(["pod-a", "-n", "ns", "--", "ls"], "ctx")
    assert result.returncode == 1


# ── _dispatch_patch ──────────────────────────────────────────────────────────

def test_dispatch_patch_deployment_json_patch():
    apps_v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        result = k8s_client._dispatch_patch(
            "deployment",
            ["dep-a", "-n", "ns", "--type=json", '-p=[{"op":"replace","path":"/x","value":1}]'],
            "ctx",
        )
    assert result.returncode == 0
    apps_v1.patch_namespaced_deployment.assert_called_once()


def test_dispatch_patch_node_does_not_require_namespace():
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_patch(
            "node", ["node-a", "--type=json", '-p=[{"op":"replace","path":"/x","value":1}]'], "ctx",
        )
    assert result.returncode == 0
    v1.patch_node.assert_called_once()


def test_dispatch_patch_returns_none_for_non_json_patch_type():
    assert k8s_client._dispatch_patch(
        "deployment", ["dep-a", "-n", "ns", "--type=merge", "-p={}"], "ctx",
    ) is None


def test_dispatch_patch_returns_fail_on_404():
    apps_v1 = MagicMock()
    apps_v1.patch_namespaced_deployment.side_effect = k8s_client.ApiException(status=404)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        result = k8s_client._dispatch_patch(
            "deployment", ["dep-a", "-n", "ns", "--type=json", "-p=[]"], "ctx",
        )
    assert result.returncode == 1
    assert result.stderr == "not found"


# ── _dispatch_label ──────────────────────────────────────────────────────────

def test_dispatch_label_namespace_add_label():
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_label("namespace", ["ns-a", "chaos-mesh.org/inject=enabled"], "ctx")
    assert result.returncode == 0
    v1.patch_namespace.assert_called_once_with(
        "ns-a", {"metadata": {"labels": {"chaos-mesh.org/inject": "enabled"}}},
    )


def test_dispatch_label_namespace_remove_label():
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_label("namespace", ["ns-a", "chaos-mesh.org/inject-"], "ctx")
    assert result.returncode == 0
    v1.patch_namespace.assert_called_once_with(
        "ns-a", {"metadata": {"labels": {"chaos-mesh.org/inject": None}}},
    )


def test_dispatch_label_returns_none_for_non_namespace_resource():
    assert k8s_client._dispatch_label("pod", ["p", "a=b"], "ctx") is None


# ── _dispatch_taint ──────────────────────────────────────────────────────────

def test_dispatch_taint_adds_new_taint():
    node = MagicMock()
    node.spec.taints = []
    v1 = MagicMock()
    v1.read_node.return_value = node
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_taint(["nodes", "node-a", "chaos=test:NoExecute"], "ctx")
    assert result.returncode == 0
    v1.patch_node.assert_called_once()


def test_dispatch_taint_removes_matching_taint():
    existing = MagicMock(key="chaos", value="test", effect="NoExecute")
    node = MagicMock()
    node.spec.taints = [existing]
    v1 = MagicMock()
    v1.read_node.return_value = node
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_taint(["nodes", "node-a", "chaos=test:NoExecute-"], "ctx")
    assert result.returncode == 0
    patched_taints = v1.patch_node.call_args.args[1]["spec"]["taints"]
    assert patched_taints == []


def test_dispatch_taint_returns_none_for_bad_shape():
    assert k8s_client._dispatch_taint(["nodes"], "ctx") is None


# ── _dispatch_cordon / uncordon ──────────────────────────────────────────────

def test_dispatch_cordon_marks_unschedulable():
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_cordon(False, ["node-a"], "ctx")
    assert result.returncode == 0
    v1.patch_node.assert_called_once_with("node-a", {"spec": {"unschedulable": True}})


def test_dispatch_uncordon_marks_schedulable():
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_cordon(True, ["node-a"], "ctx")
    assert result.returncode == 0
    v1.patch_node.assert_called_once_with("node-a", {"spec": {"unschedulable": False}})


def test_dispatch_cordon_returns_none_for_bad_shape():
    assert k8s_client._dispatch_cordon(False, ["node-a", "extra"], "ctx") is None


# ── _dispatch_rollout ────────────────────────────────────────────────────────

def test_dispatch_rollout_restart_patches_annotation():
    apps_v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        result = k8s_client._dispatch_rollout(
            "restart", ["deployment/dep-a", "-n", "ns"], "ctx",
        )
    assert result.returncode == 0
    apps_v1.patch_namespaced_deployment.assert_called_once()


def test_dispatch_rollout_status_returns_ok_when_fully_rolled_out():
    dep = MagicMock()
    dep.spec.replicas = 2
    dep.status.updated_replicas = 2
    dep.status.replicas = 2
    dep.status.available_replicas = 2
    dep.status.observed_generation = 1
    dep.metadata.generation = 1
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.return_value = dep
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "AppsV1Api", return_value=apps_v1):
        result = k8s_client._dispatch_rollout(
            "status", ["deployment/dep-a", "-n", "ns", "--timeout=30s"], "ctx",
        )
    assert result.returncode == 0
    assert "successfully rolled out" in result.stdout


def test_dispatch_rollout_returns_none_without_namespace():
    assert k8s_client._dispatch_rollout("restart", ["deployment/dep-a"], "ctx") is None


def test_dispatch_rollout_returns_none_for_non_deployment_target():
    assert k8s_client._dispatch_rollout("restart", ["pod/foo", "-n", "ns"], "ctx") is None


# ── _dispatch_create ─────────────────────────────────────────────────────────

def test_dispatch_create_namespace():
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_create("namespace", ["ns-a"], "ctx")
    assert result.returncode == 0
    v1.create_namespace.assert_called_once()


def test_dispatch_create_namespace_already_exists():
    v1 = MagicMock()
    v1.create_namespace.side_effect = k8s_client.ApiException(status=409)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_create("namespace", ["ns-a"], "ctx")
    assert result.returncode == 1
    assert result.stderr == "already exists"


def test_dispatch_create_returns_none_for_unrecognized_resource():
    assert k8s_client._dispatch_create("pod", ["foo"], "ctx") is None


# ── _dispatch_apply ──────────────────────────────────────────────────────────

def test_dispatch_apply_creates_pod_manifest(tmp_path):
    manifest = {"kind": "Pod", "metadata": {"name": "p1", "namespace": "ns"}}
    path = tmp_path / "pod.json"
    path.write_text(json.dumps(manifest))
    v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_apply(["-f", str(path)], "ctx")
    assert result.returncode == 0
    v1.create_namespaced_pod.assert_called_once_with("ns", manifest)


def test_dispatch_apply_replaces_pod_on_conflict(tmp_path):
    manifest = {"kind": "Pod", "metadata": {"name": "p1", "namespace": "ns"}}
    path = tmp_path / "pod.json"
    path.write_text(json.dumps(manifest))
    v1 = MagicMock()
    v1.create_namespaced_pod.side_effect = k8s_client.ApiException(status=409)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_apply(["-f", str(path)], "ctx")
    assert result.returncode == 0
    v1.replace_namespaced_pod.assert_called_once_with("p1", "ns", manifest)


def test_dispatch_apply_creates_chaos_crd_manifest(tmp_path):
    manifest = {"kind": "PodChaos", "metadata": {"name": "pc1", "namespace": "chaos-testing"}}
    path = tmp_path / "podchaos.json"
    path.write_text(json.dumps(manifest))
    custom = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_apply(["-f", str(path)], "ctx")
    assert result.returncode == 0
    custom.create_namespaced_custom_object.assert_called_once()


def test_dispatch_apply_returns_none_for_unrecognized_kind(tmp_path):
    manifest = {"kind": "ConfigMap", "metadata": {"name": "cm", "namespace": "ns"}}
    path = tmp_path / "cm.json"
    path.write_text(json.dumps(manifest))
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()):
        assert k8s_client._dispatch_apply(["-f", str(path)], "ctx") is None


def test_dispatch_apply_returns_none_for_unreadable_file():
    assert k8s_client._dispatch_apply(["-f", "/no/such/file.json"], "ctx") is None


def test_dispatch_apply_returns_none_for_bad_shape():
    assert k8s_client._dispatch_apply(["-k", "somedir"], "ctx") is None


# ── formatting helpers ───────────────────────────────────────────────────────

def test_fmt_cpu_millicores():
    assert k8s_client._fmt_cpu_millicores(0.105) == "105m"


def test_fmt_mem_mi():
    assert k8s_client._fmt_mem_mi(134217728) == "128Mi"


# ── _dispatch_top ────────────────────────────────────────────────────────────

def test_dispatch_top_pods_returns_formatted_lines():
    custom = MagicMock()
    custom.list_namespaced_custom_object.return_value = {
        "items": [{
            "metadata": {"name": "pod-a"},
            "containers": [{"name": "app", "usage": {"cpu": "100m", "memory": "128Mi"}}],
        }]
    }
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_top(["pods", "-n", "ns"], "ctx")
    assert result.returncode == 0
    assert "pod-a" in result.stdout


def test_dispatch_top_pods_returns_none_without_namespace():
    assert k8s_client._dispatch_top(["pods"], "ctx") is None


def test_dispatch_top_nodes_returns_formatted_lines():
    node = MagicMock()
    node.metadata.name = "node-a"
    node.status.allocatable = {"cpu": "4", "memory": "8Gi"}
    v1 = MagicMock()
    v1.list_node.return_value = MagicMock(items=[node])
    custom = MagicMock()
    custom.list_cluster_custom_object.return_value = {
        "items": [{"metadata": {"name": "node-a"}, "usage": {"cpu": "500m", "memory": "1Gi"}}]
    }
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_top(["nodes"], "ctx")
    assert result.returncode == 0
    assert "node-a" in result.stdout


def test_dispatch_top_returns_none_for_unrecognized_resource():
    assert k8s_client._dispatch_top(["services"], "ctx") is None


def test_dispatch_top_returns_fail_on_api_exception():
    custom = MagicMock()
    custom.list_namespaced_custom_object.side_effect = k8s_client.ApiException(reason="down")
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_top(["pods", "-n", "ns"], "ctx")
    assert result.returncode == 1


# ── _dispatch_config ─────────────────────────────────────────────────────────

def test_dispatch_config_use_context_success():
    with patch.object(k8s_client, "set_current_kube_context", return_value=True):
        result = k8s_client._dispatch_config(["use-context", "ctx-a"], "ctx")
    assert result.returncode == 0


def test_dispatch_config_use_context_failure():
    with patch.object(k8s_client, "set_current_kube_context", return_value=False):
        result = k8s_client._dispatch_config(["use-context", "ctx-zzz"], "ctx")
    assert result.returncode == 1


def test_dispatch_config_returns_none_for_other_subcommands():
    assert k8s_client._dispatch_config(["get-contexts"], "ctx") is None


# ── _dispatch_drain ──────────────────────────────────────────────────────────

def _make_pod(name, namespace="ns", phase="Running", owner_kind=None):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.status.phase = phase
    pod.metadata.owner_references = (
        [MagicMock(kind=owner_kind)] if owner_kind else []
    )
    return pod


def test_dispatch_drain_evicts_non_daemonset_pods_and_waits_for_termination():
    pod = _make_pod("app-pod")
    v1 = MagicMock()
    v1.list_pod_for_all_namespaces.return_value = MagicMock(items=[pod])
    v1.read_namespaced_pod.side_effect = k8s_client.ApiException(status=404)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_drain(
            ["node-a", "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--timeout=5s"],
            "ctx",
        )
    assert result.returncode == 0
    assert "drained" in result.stdout
    v1.patch_node.assert_called_once_with("node-a", {"spec": {"unschedulable": True}})


def test_dispatch_drain_skips_daemonset_and_completed_pods():
    ds_pod = _make_pod("ds-pod", owner_kind="DaemonSet")
    done_pod = _make_pod("done-pod", phase="Succeeded")
    v1 = MagicMock()
    v1.list_pod_for_all_namespaces.return_value = MagicMock(items=[ds_pod, done_pod])
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_drain(
            ["node-a", "--ignore-daemonsets", "--delete-emptydir-data", "--force"], "ctx",
        )
    assert result.returncode == 0
    v1.create_namespaced_pod_eviction.assert_not_called()


def test_dispatch_drain_returns_none_without_required_flag_combination():
    assert k8s_client._dispatch_drain(["node-a", "--force"], "ctx") is None


def test_dispatch_drain_returns_none_for_unrecognized_flag():
    assert k8s_client._dispatch_drain(
        ["node-a", "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--bogus"], "ctx",
    ) is None


def test_drain_evict_pod_returns_true_on_success():
    core_v1 = MagicMock()
    pod = _make_pod("p")
    ok, reason = k8s_client._drain_evict_pod(core_v1, pod, None)
    assert ok is True
    assert reason == ""


def test_drain_evict_pod_returns_true_when_already_gone():
    core_v1 = MagicMock()
    core_v1.create_namespaced_pod_eviction.side_effect = k8s_client.ApiException(status=404)
    pod = _make_pod("p")
    ok, reason = k8s_client._drain_evict_pod(core_v1, pod, None)
    assert ok is True


def test_drain_evict_pod_returns_false_when_pdb_blocked():
    core_v1 = MagicMock()
    core_v1.create_namespaced_pod_eviction.side_effect = k8s_client.ApiException(status=429)
    pod = _make_pod("p")
    ok, reason = k8s_client._drain_evict_pod(core_v1, pod, None)
    assert ok is False
    assert "PodDisruptionBudget" in reason


# ── _dispatch_get: services/endpoints/pdb/events/namespace/crd/chaos-kinds ──

def test_dispatch_get_service_by_name():
    api_client = _api_client_with_serialized({"metadata": {"name": "svc-a"}})
    v1 = MagicMock()
    v1.read_namespaced_service.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_get("service", ["svc-a", "-n", "ns"], "ctx")
    assert result is not None
    assert result.returncode == 0


def test_dispatch_get_service_list_requires_namespace():
    assert k8s_client._dispatch_get("services", [], "ctx") is None


def test_dispatch_get_endpoints_requires_name_and_namespace():
    assert k8s_client._dispatch_get("endpoints", ["ep-a"], "ctx") is None


def test_dispatch_get_endpoints_success():
    api_client = _api_client_with_serialized({"subsets": []})
    v1 = MagicMock()
    v1.read_namespaced_endpoints.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_get("endpoints", ["ep-a", "-n", "ns"], "ctx")
    assert result.returncode == 0


def test_dispatch_get_pdb_list():
    api_client = _api_client_with_serialized({"items": []})
    policy_v1 = MagicMock()
    policy_v1.list_namespaced_pod_disruption_budget.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s_client.client, "PolicyV1Api", return_value=policy_v1):
        result = k8s_client._dispatch_get("pdb", ["-n", "ns"], "ctx")
    assert result.returncode == 0


def test_dispatch_get_events_list():
    api_client = _api_client_with_serialized({"items": []})
    v1 = MagicMock()
    v1.list_namespaced_event.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_get("events", ["-n", "ns"], "ctx")
    assert result.returncode == 0


def test_dispatch_get_namespace_by_name():
    api_client = _api_client_with_serialized({"metadata": {"name": "ns-a"}})
    v1 = MagicMock()
    v1.read_namespace.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_get("namespace", ["ns-a"], "ctx")
    assert result.returncode == 0


def test_dispatch_get_namespace_list():
    api_client = _api_client_with_serialized({"items": []})
    v1 = MagicMock()
    v1.list_namespace.return_value = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=api_client), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_get("namespaces", [], "ctx")
    assert result.returncode == 0


def test_dispatch_get_crd_existence_check_found():
    ext_v1 = MagicMock()
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s_client.client, "ApiextensionsV1Api", return_value=ext_v1):
        result = k8s_client._dispatch_get("crd", ["networkchaoses.chaos-mesh.org"], "ctx")
    assert result.returncode == 0


def test_dispatch_get_crd_existence_check_not_found():
    ext_v1 = MagicMock()
    ext_v1.read_custom_resource_definition.side_effect = k8s_client.ApiException(status=404)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s_client.client, "ApiextensionsV1Api", return_value=ext_v1):
        result = k8s_client._dispatch_get("crd", ["missing.example.com"], "ctx")
    assert result.returncode == 1


def test_dispatch_get_chaos_kind_by_name():
    custom = MagicMock()
    custom.get_namespaced_custom_object.return_value = {"metadata": {"name": "nc1"}}
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_get("networkchaos", ["nc1", "-n", "chaos-testing"], "ctx")
    assert result.returncode == 0


def test_dispatch_get_chaos_kind_all_namespaces():
    custom = MagicMock()
    custom.list_cluster_custom_object.return_value = {"items": []}
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CustomObjectsApi", return_value=custom):
        result = k8s_client._dispatch_get("networkchaos", ["--all-namespaces"], "ctx")
    assert result.returncode == 0


def test_dispatch_get_returns_fail_on_404_for_unnamed_resource():
    v1 = MagicMock()
    v1.read_namespace.side_effect = k8s_client.ApiException(status=404)
    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=v1):
        result = k8s_client._dispatch_get("namespace", ["missing-ns"], "ctx")
    assert result.returncode == 1
    assert result.stderr == "not found"
