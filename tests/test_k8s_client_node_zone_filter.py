"""
Regression test for a real bug found via a live cluster + user report:
selecting an availability zone in "Zone-Level Node Failure" showed ALL
cluster nodes instead of only the nodes actually in that zone.

Root cause: chaosforge.providers.azure.components.aks.kubernetes._dispatch_get()'s "nodes" branch called
v1.list_node() with no label_selector at all — unlike the pods/
replicasets/services branches, which all correctly forward
label_selector=parsed["selector"]. So `kubectl get nodes -l
topology.kubernetes.io/zone=<zone> -o jsonpath=...` (used by
AzureAKSDiscovery.list_nodes_in_zone) silently ignored the zone filter and
returned every node in the cluster via the Python-client dispatch path,
even though the dispatcher itself reported success (so the real kubectl
subprocess fallback — which filters correctly — was never used).

Confirmed live: `kubectl get nodes -l topology.kubernetes.io/zone=eastus-3`
correctly returned only 2 real zone-3 nodes, while the platform's own
list_nodes_in_zone() returned all 8 cluster nodes before this fix.
"""

from unittest.mock import MagicMock, patch

from chaosforge.providers.azure.components.aks import kubernetes as k8s_client


def _fake_node(name, zone):
    return {
        "metadata": {"name": name, "labels": {"topology.kubernetes.io/zone": zone}},
    }


def test_get_nodes_with_label_selector_only_returns_matching_nodes():
    zone3_node = _fake_node("aks-default3-abc-vmss000006", "eastus-3")

    mock_v1 = MagicMock()
    mock_v1.list_node.return_value = MagicMock()

    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=mock_v1), \
         patch.object(
             k8s_client.client.ApiClient, "sanitize_for_serialization",
             return_value={"items": [zone3_node]},
         ):
        result = k8s_client._dispatch_get(
            "nodes",
            ["-l", "topology.kubernetes.io/zone=eastus-3", "-o",
             "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}"],
            "ctx",
        )

    assert result is not None
    # The label selector must actually be forwarded to the Kubernetes API —
    # this is the exact call that was previously missing label_selector=...
    mock_v1.list_node.assert_called_once_with(
        label_selector="topology.kubernetes.io/zone=eastus-3",
        field_selector=None,
    )


def test_get_nodes_without_selector_still_lists_all_nodes():
    """No selector -> label_selector=None, same as `kubectl get nodes` with
    no -l flag — must not regress plain node listing."""
    mock_v1 = MagicMock()
    mock_v1.list_node.return_value = MagicMock()

    with patch.object(k8s_client, "_get_api_client", return_value=MagicMock()), \
         patch.object(k8s_client.client, "CoreV1Api", return_value=mock_v1), \
         patch.object(
             k8s_client.client.ApiClient, "sanitize_for_serialization",
             return_value={"items": []},
         ):
        k8s_client._dispatch_get("nodes", [], "ctx")

    mock_v1.list_node.assert_called_once_with(label_selector=None, field_selector=None)
