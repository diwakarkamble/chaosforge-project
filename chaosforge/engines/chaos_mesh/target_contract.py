"""Shared workload target contract for direct EKS Chaos Mesh experiments."""

WORKLOAD_EXPERIMENTS = frozenset(
    {
        "chaos-mesh-pod-failure", "chaos-mesh-pod-kill", "chaos-mesh-container-kill",
        "chaos-mesh-network-delay", "chaos-mesh-network-loss", "chaos-mesh-network-duplicate",
        "chaos-mesh-network-corrupt", "chaos-mesh-network-reorder", "chaos-mesh-network-partition",
        "chaos-mesh-network-bandwidth", "chaos-mesh-cpu-stress", "chaos-mesh-memory-stress",
        "chaos-mesh-dns-error", "chaos-mesh-dns-random", "chaos-mesh-http-abort",
        "chaos-mesh-http-delay", "chaos-mesh-http-replace", "chaos-mesh-http-patch",
        "chaos-mesh-io-latency", "chaos-mesh-io-fault", "chaos-mesh-io-attr-override",
        "chaos-mesh-io-mistake", "chaos-mesh-time", "chaos-mesh-kernel",
        "chaos-mesh-jvm", "chaos-mesh-block",
    }
)

AKS_PARITY_INPUTS = {
    "chaos-mesh-container-kill": [
        {
            "name": "container_name", "label": "Container", "type": "aws_resource",
            "resource_type": "eks-container", "parent": "namespace", "return": "name",
            "required": True,
        },
    ],
    "chaos-mesh-network-delay": [
        {"name": "jitter", "label": "Jitter (e.g. 100ms, 50ms, 0ms)", "type": "text", "required": False, "default": "100ms"},
        {"name": "correlation", "label": "Correlation % (0-100)", "type": "integer", "required": False, "default": 50, "min": 0, "max": 100},
    ],
    "chaos-mesh-network-loss": [
        {"name": "correlation", "label": "Correlation % (0-100)", "type": "integer", "required": False, "default": 50, "min": 0, "max": 100},
    ],
    "chaos-mesh-network-duplicate": [
        {"name": "correlation", "label": "Correlation % (0-100)", "type": "integer", "required": False, "default": 25, "min": 0, "max": 100},
    ],
    "chaos-mesh-network-corrupt": [
        {"name": "correlation", "label": "Correlation % (0-100)", "type": "integer", "required": False, "default": 25, "min": 0, "max": 100},
    ],
    "chaos-mesh-dns-error": [
        {"name": "dns_pattern", "label": "DNS Pattern to Fail", "type": "text", "required": True, "default": "*"},
    ],
    "chaos-mesh-http-abort": [
        {"name": "http_port", "label": "HTTP Port", "type": "integer", "required": False, "default": 80, "min": 1, "max": 65535},
    ],
    "chaos-mesh-http-delay": [
        {"name": "http_port", "label": "HTTP Port", "type": "integer", "required": False, "default": 80, "min": 1, "max": 65535},
        {"name": "http_delay", "label": "HTTP Delay (e.g. 5s)", "type": "text", "required": False, "default": "5s"},
    ],
    "chaos-mesh-io-latency": [
        {"name": "io_percent", "label": "Percent of I/O Ops Affected (1-100)", "type": "integer", "required": False, "default": 50, "min": 1, "max": 100},
    ],
    "chaos-mesh-io-fault": [
        {"name": "io_errno", "label": "Errno to Inject (5=EIO)", "type": "integer", "required": False, "default": 5, "min": 1, "max": 133},
        {"name": "io_percent", "label": "Percent of I/O Ops Affected (1-100)", "type": "integer", "required": False, "default": 50, "min": 1, "max": 100},
    ],
    "chaos-mesh-time": [
        {"name": "time_offset", "label": "Time Offset (e.g. +5m, -5m)", "type": "text", "required": False, "default": "+5m"},
    ],
}


def is_workload_experiment(experiment_id):
    return experiment_id in WORKLOAD_EXPERIMENTS


def bind_workload_target_contract(experiment):
    """Give all direct workload faults the AKS-style deployment-or-pod target flow."""
    if not is_workload_experiment(experiment.get("id")):
        return experiment
    inputs = experiment.get("inputs", [])
    if experiment.get("id") == "chaos-mesh-container-kill":
        inputs = [field for field in inputs if field.get("name") != "container_names"]
    names = {field["name"] for field in inputs}
    if "target_mode" not in names:
        namespace_index = next(
            index for index, field in enumerate(inputs) if field["name"] == "namespace"
        )
        target_fields = [
        {
            "name": "target_mode", "label": "Target Mode", "type": "select",
            "required": True, "default": "pod",
            "options": [
                {"value": "deployment", "label": "By Deployment - target pods via deployment label selector"},
                {"value": "pod", "label": "By Pod - target a single specific pod directly"},
            ],
        },
        {
            "name": "deployment", "label": "Deployment", "type": "aws_resource",
            "resource_type": "eks-deployment", "parent": "namespace", "return": "name",
            "required": False, "visible_when": {"target_mode": "deployment"},
        },
        ]
        pod = next((field for field in inputs if field["name"] == "pod"), None)
        if pod is None:
            pod = {
            "name": "pod", "label": "Pod", "type": "aws_resource",
            "resource_type": "eks-pod", "parent": "namespace", "return": "name",
            "required": False,
            }
        pod.update({"label": "Pod", "visible_when": {"target_mode": "pod"}})
        inputs = [field for field in inputs if field["name"] != "pod"]
        inputs[namespace_index + 1:namespace_index + 1] = target_fields + [pod]
    for field in inputs:
        if field["name"] == "mode":
            field.update({"label": "Chaos Mode", "type": "chaos_mode", "visible_when": {"target_mode": "deployment"}})
        if field["name"] == "duration":
            field.update({"label": "Fault Duration (ISO 8601)", "type": "iso8601_duration", "default": "PT60S"})
    if not any(field["name"] == "mode" for field in inputs):
        inputs.append(
            {
                "name": "mode", "label": "Chaos Mode", "type": "chaos_mode",
                "required": True, "default": "one", "visible_when": {"target_mode": "deployment"},
            }
        )
    if not any(field["name"] == "duration" for field in inputs):
        inputs.append(
            {
                "name": "duration", "label": "Fault Duration (ISO 8601)", "type": "iso8601_duration",
                "required": True, "default": "PT60S",
            }
        )
    names = {field["name"] for field in inputs}
    if "chaos_value" not in names:
        inputs.append(
            {
                "name": "chaos_value", "label": "Mode Value", "type": "text",
                "required": False, "default": "", "visible_when": {"target_mode": "deployment"},
            }
        )
    for field in AKS_PARITY_INPUTS.get(experiment["id"], []):
        if field["name"] not in names:
            inputs.append(dict(field))
    experiment["inputs"] = inputs
    return experiment
