from chaosforge.providers.azure.components.aks import kubernetes as k8s_client

POD = {
    "metadata": {
        "name": "api-pod",
        "labels": {"app": "api", "tier": "backend"},
    },
    "spec": {
        "containers": [
            {"name": "api", "image": "api:v1"},
            {"name": "sidecar", "image": "sidecar:v1"},
        ],
    },
    "status": {
        "phase": "Running",
        "conditions": [
            {"type": "Ready", "status": "True"},
            {"type": "Initialized", "status": "True"},
        ],
    },
}

POD_LIST = {"items": [POD, {"metadata": {"name": "worker-pod"}, "status": {"phase": "Pending"}}]}


def test_jsonpath_plain_dotted_path_returns_scalar_value():
    assert k8s_client._jsonpath_get("{.metadata.name}", POD) == "api-pod"


def test_jsonpath_array_index_returns_selected_value():
    assert k8s_client._jsonpath_get("{.spec.containers[1].image}", POD) == "sidecar:v1"


def test_jsonpath_range_template_renders_multiple_items_with_literals():
    expr = '{range .items[*]}{.metadata.name}{"\\n"}{end}'
    assert k8s_client._jsonpath_get(expr, POD_LIST) == "api-pod\nworker-pod\n"
