import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from chaosforge.providers.azure.components.aks import discovery as azure_discovery


def _completed(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def discovery():
    return azure_discovery.AzureAKSDiscovery()


def test_kubectl_uses_dispatcher_result_without_shelling_out():
    dispatched = _completed(stdout="from-dispatcher\n")

    with patch("chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl", return_value=dispatched), \
         patch.object(azure_discovery.subprocess, "run") as run:
        result = azure_discovery._kubectl("get", "pods", context="ctx")

    assert result is dispatched
    run.assert_not_called()


def test_kubectl_falls_back_to_subprocess_when_dispatcher_errors():
    fallback = _completed(stdout="from-subprocess\n")

    with patch("chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl", side_effect=RuntimeError("boom")), \
         patch("chaosforge.providers.azure.components.aks.kubernetes.subprocess.run", return_value=fallback) as run:
        result = azure_discovery._kubectl("get", "pods", context="ctx")

    assert result.stdout == fallback.stdout
    run.assert_called_once_with(
        ["kubectl", "get", "pods", "--context", "ctx"],
        capture_output=True,
        text=True,
        timeout=None,
    )


def test_kubectl_json_returns_parsed_payload_and_passes_context():
    payload = {"items": [{"metadata": {"name": "pod-a"}}]}

    with patch.object(
        azure_discovery,
        "_kubectl",
        return_value=_completed(stdout=json.dumps(payload)),
    ) as kubectl:
        result = azure_discovery._kubectl_json(["kubectl", "get", "pods", "-n", "app"], context="ctx")

    assert result == payload
    kubectl.assert_called_once_with("get", "pods", "-n", "app", "-o", "json", context="ctx")


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (_completed(returncode=1, stderr="forbidden"), None),
        (_completed(stdout="{not-json"), None),
    ],
)
def test_kubectl_json_returns_none_on_failure_or_bad_json(completed, expected):
    with patch.object(azure_discovery, "_kubectl", return_value=completed):
        assert azure_discovery._kubectl_json(["kubectl", "get", "pods"], context="ctx") is expected


def test_list_contexts_filters_to_aks_contexts_when_az_names_available(discovery):
    with patch("chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts", return_value=[
        "team-prod-aks",
        "arn:aws:eks:us-east-1:123:cluster/dev",
        "gke_project_us-central1_cluster",
        "legacy-ctx",
    ]), patch.object(
        azure_discovery.subprocess,
        "run",
        return_value=_completed(stdout="prod-aks\n"),
    ):
        result = discovery.list_contexts()

    assert result == ["team-prod-aks"]


def test_list_contexts_handles_unreadable_kubeconfig_without_kubectl(discovery):
    with patch("chaosforge.providers.azure.components.aks.kubernetes.list_kube_contexts", side_effect=Exception("bad kubeconfig")), \
         patch.object(
             azure_discovery.subprocess,
             "run",
             return_value=_completed(returncode=1, stderr="az unavailable"),
         ) as run:
        result = discovery.list_contexts()

    assert result == []
    assert all(call.args[0][0] != "kubectl" for call in run.call_args_list)


def test_list_namespaces_filters_system_namespaces(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        return_value=_completed(stdout="default kube-system app-ns chaos-testing kube-public kube-node-lease\n"),
    ):
        result = discovery.list_namespaces("ctx")

    assert result == ["default", "app-ns"]
    assert discovery.last_error is None


def test_list_namespaces_preserves_query_error(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        return_value=_completed(returncode=1, stderr="forbidden: cannot list namespaces"),
    ):
        result = discovery.list_namespaces("missing-context")

    assert result == []
    assert discovery.last_error == (
        "Could not list namespaces using Kubernetes context 'missing-context': "
        "forbidden: cannot list namespaces"
    )


def test_list_deployments_returns_names_or_empty_on_error(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        side_effect=[
            _completed(stdout="api\nworker\n"),
            _completed(returncode=1, stderr="boom"),
        ],
    ):
        assert discovery.list_deployments("ctx", "app-ns") == ["api", "worker"]
        assert discovery.list_deployments("ctx", "app-ns") == []


def test_list_containers_and_pod_containers_return_split_names(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        side_effect=[
            _completed(stdout="api\nsidecar\n"),
            _completed(stdout="main\nmetrics\n"),
        ],
    ):
        assert discovery.list_containers("ctx", "app-ns", "api") == ["api", "sidecar"]
        assert discovery.list_pod_containers("ctx", "app-ns", "api-123") == ["main", "metrics"]


def test_get_label_selector_reads_first_match_label_and_falls_back(discovery):
    deployment = {"spec": {"selector": {"matchLabels": {"component": "api", "tier": "web"}}}}

    with patch.object(
        azure_discovery,
        "_kubectl",
        side_effect=[
            _completed(stdout=json.dumps(deployment)),
            _completed(stdout="{not-json"),
            _completed(returncode=1, stderr="missing"),
        ],
    ):
        assert discovery.get_label_selector("ctx", "app-ns", "api") == ("component", "api")
        assert discovery.get_label_selector("ctx", "app-ns", "api") == ("app", "api")
        assert discovery.get_label_selector("ctx", "app-ns", "api") == ("app", "api")


def test_get_pod_count_counts_nonblank_lines_and_handles_error(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        side_effect=[
            _completed(stdout="pod-a\n\npod-b\n"),
            _completed(returncode=1, stderr="boom"),
        ],
    ):
        assert discovery.get_pod_count("ctx", "app-ns", "app", "api") == 2
        assert discovery.get_pod_count("ctx", "app-ns", "app", "api") == 0


def test_list_pods_returns_running_pod_names(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        return_value=_completed(stdout="api-1\napi-2\n"),
    ):
        assert discovery.list_pods("ctx", "app-ns") == ["api-1", "api-2"]


def test_get_pod_label_prefers_app_then_first_label_then_pod_name(discovery):
    app_labeled = {"metadata": {"labels": {"app": "api", "tier": "web"}}}
    fallback_labeled = {"metadata": {"labels": {"component": "worker"}}}

    with patch.object(
        azure_discovery,
        "_kubectl",
        side_effect=[
            _completed(stdout=json.dumps(app_labeled)),
            _completed(stdout=json.dumps(fallback_labeled)),
            _completed(returncode=1, stderr="not found"),
        ],
    ):
        assert discovery.get_pod_label("ctx", "app-ns", "api-1") == ("app", "api")
        assert discovery.get_pod_label("ctx", "app-ns", "worker-1") == ("component", "worker")
        assert discovery.get_pod_label("ctx", "app-ns", "orphan-1") == ("app", "orphan-1")


def test_list_nodes_excludes_control_plane_and_master_nodes(discovery):
    output = (
        "worker-a\t[]\n"
        "cp-a\t[node-role.kubernetes.io/control-plane:NoSchedule]\n"
        "master-a\t[node-role.kubernetes.io/master:NoSchedule]\n"
        "worker-b\t\n"
    )

    with patch.object(azure_discovery, "_kubectl", return_value=_completed(stdout=output)):
        assert discovery.list_nodes("ctx") == ["worker-a", "worker-b"]


def test_list_zones_returns_sorted_unique_values(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        return_value=_completed(stdout="eastus-2\n\neastus-1\neastus-2\n"),
    ):
        assert discovery.list_zones("ctx") == ["eastus-1", "eastus-2"]


def test_list_nodes_in_zone_returns_nodes_or_empty(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        side_effect=[
            _completed(stdout="node-a\nnode-b\n"),
            _completed(returncode=1, stderr="boom"),
        ],
    ):
        assert discovery.list_nodes_in_zone("ctx", "eastus-1") == ["node-a", "node-b"]
        assert discovery.list_nodes_in_zone("ctx", "eastus-1") == []


def test_get_vmss_instance_for_node_parses_provider_id_and_handles_bad_values(discovery):
    with patch.object(
        azure_discovery,
        "_kubectl",
        side_effect=[
            _completed(
                stdout=(
                    "azure:///subscriptions/sub/resourceGroups/rg/providers/"
                    "Microsoft.Compute/virtualMachineScaleSets/aks-pool-123-vmss/"
                    "virtualMachines/7"
                )
            ),
            _completed(stdout="azure:///subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"),
            _completed(returncode=1, stderr="boom"),
        ],
    ):
        assert discovery.get_vmss_instance_for_node("ctx", "node-a", "sub", "rg") == ("aks-pool-123-vmss", "7")
        assert discovery.get_vmss_instance_for_node("ctx", "node-b", "sub", "rg") == (None, None)
        assert discovery.get_vmss_instance_for_node("ctx", "node-c", "sub", "rg") == (None, None)


def test_get_owned_pod_names_uses_owner_references(discovery):
    rs_json = {
        "items": [
            {
                "metadata": {
                    "name": "api-rs-1",
                    "ownerReferences": [{"kind": "Deployment", "name": "api"}],
                }
            },
            {
                "metadata": {
                    "name": "other-rs",
                    "ownerReferences": [{"kind": "Deployment", "name": "other"}],
                }
            },
        ]
    }
    pod_json = {
        "items": [
            {
                "metadata": {
                    "name": "api-abc",
                    "ownerReferences": [{"kind": "ReplicaSet", "name": "api-rs-1"}],
                }
            },
            {
                "metadata": {
                    "name": "api-def",
                    "ownerReferences": [{"kind": "ReplicaSet", "name": "api-rs-1"}],
                }
            },
            {
                "metadata": {
                    "name": "other-abc",
                    "ownerReferences": [{"kind": "ReplicaSet", "name": "other-rs"}],
                }
            },
        ]
    }

    with patch.object(azure_discovery, "_kubectl_json", side_effect=[rs_json, pod_json]):
        assert discovery.get_owned_pod_names("ctx", "app-ns", "api") == ["api-abc", "api-def"]


def test_get_owned_pod_names_returns_empty_when_no_owned_replica_sets(discovery):
    with patch.object(azure_discovery, "_kubectl_json", return_value={"items": []}):
        assert discovery.get_owned_pod_names("ctx", "app-ns", "api") == []


def test_get_deployment_for_pod_walks_pod_to_rs_to_deployment(discovery):
    pod_json = {
        "metadata": {
            "ownerReferences": [{"kind": "ReplicaSet", "name": "api-rs-1"}],
        }
    }
    rs_json = {
        "metadata": {
            "ownerReferences": [{"kind": "Deployment", "name": "api"}],
        }
    }

    with patch.object(azure_discovery, "_kubectl_json", side_effect=[pod_json, rs_json]):
        assert discovery.get_deployment_for_pod("ctx", "app-ns", "api-123") == "api"


def test_get_deployment_for_pod_returns_none_when_not_deployment_managed(discovery):
    pod_json = {"metadata": {"ownerReferences": [{"kind": "Job", "name": "batch"}]}}

    with patch.object(azure_discovery, "_kubectl_json", return_value=pod_json):
        assert discovery.get_deployment_for_pod("ctx", "app-ns", "job-pod") is None


def test_get_safe_label_selector_adds_template_labels_and_active_pod_hash(discovery):
    dep_json = {
        "spec": {
            "selector": {"matchLabels": {"app": "api"}},
            "template": {
                "metadata": {
                    "labels": {
                        "app": "api",
                        "app.kubernetes.io/role": "gateway",
                        "checksum/config": "skip-me",
                    }
                }
            },
        }
    }
    rs_json = {
        "items": [
            {
                "metadata": {
                    "name": "api-rs-old",
                    "creationTimestamp": "2026-01-01T00:00:00Z",
                    "labels": {"pod-template-hash": "oldhash"},
                    "ownerReferences": [{"kind": "Deployment", "name": "api"}],
                },
                "spec": {"replicas": 0},
            },
            {
                "metadata": {
                    "name": "api-rs-new",
                    "creationTimestamp": "2026-01-02T00:00:00Z",
                    "labels": {"pod-template-hash": "newhash"},
                    "ownerReferences": [{"kind": "Deployment", "name": "api"}],
                },
                "spec": {"replicas": 2},
            },
        ]
    }

    with patch.object(azure_discovery, "_kubectl_json", side_effect=[dep_json, rs_json]):
        selector = discovery.get_safe_label_selector("ctx", "app-ns", "api")

    assert selector == {
        "app": "api",
        "app.kubernetes.io/role": "gateway",
        "pod-template-hash": "newhash",
    }


@pytest.mark.parametrize("dep_json", [None, {"spec": {"selector": {"matchLabels": {}}}}])
def test_get_safe_label_selector_returns_none_without_match_labels(discovery, dep_json):
    with patch.object(azure_discovery, "_kubectl_json", return_value=dep_json):
        assert discovery.get_safe_label_selector("ctx", "app-ns", "api") is None
