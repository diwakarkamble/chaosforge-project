import json
from pathlib import Path

METADATA = (
    Path(__file__).resolve().parent
    / "chaosforge"
    / "engines"
    / "chaos_mesh"
    / "experiments"
    / "metadata.json"
)


POD_TARGETED = {
    "chaos-mesh-network-delay",
    "chaos-mesh-network-loss",
    "chaos-mesh-network-duplicate",
    "chaos-mesh-network-corrupt",
    "chaos-mesh-network-reorder",
    "chaos-mesh-network-partition",
    "chaos-mesh-network-bandwidth",
    "chaos-mesh-cpu-stress",
    "chaos-mesh-memory-stress",
    "chaos-mesh-dns-error",
    "chaos-mesh-dns-random",
    "chaos-mesh-http-abort",
    "chaos-mesh-http-delay",
    "chaos-mesh-http-replace",
    "chaos-mesh-http-patch",
    "chaos-mesh-io-latency",
    "chaos-mesh-io-fault",
    "chaos-mesh-io-attr-override",
    "chaos-mesh-io-mistake",
    "chaos-mesh-time",
    "chaos-mesh-kernel",
    "chaos-mesh-jvm",
    "chaos-mesh-block",
}


def replace_input(inputs, name, new_input):
    """Replace an input by name while preserving its position."""
    for index, item in enumerate(inputs):
        if item.get("name") == name:
            inputs[index] = new_input
            return True

    return False


def add_input_after(inputs, after_name, new_input):
    """Add an input after a specific existing input if it doesn't exist."""
    if any(item.get("name") == new_input.get("name") for item in inputs):
        return

    for index, item in enumerate(inputs):
        if item.get("name") == after_name:
            inputs.insert(index + 1, new_input)
            return

    inputs.append(new_input)


with METADATA.open("r", encoding="utf-8") as f:
    data = json.load(f)


changed = []


for experiment in data["experiments"]:
    experiment_id = experiment.get("id")
    inputs = experiment.get("inputs", [])

    # ---------------------------------------------------------
    # POD-TARGETED EXPERIMENTS
    # ---------------------------------------------------------
    if experiment_id in POD_TARGETED:

        # AWS Region
        replace_input(
            inputs,
            "aws_region",
            {
                "name": "aws_region",
                "label": "AWS Region",
                "type": "text",
                "required": True,
                "default": "eu-central-1",
            },
        )

        # If aws_region doesn't exist, add it at the beginning.
        if not any(i.get("name") == "aws_region" for i in inputs):
            inputs.insert(
                0,
                {
                    "name": "aws_region",
                    "label": "AWS Region",
                    "type": "text",
                    "required": True,
                    "default": "eu-central-1",
                },
            )

        # EKS Cluster
        if not any(i.get("name") == "eks_cluster" for i in inputs):
            add_input_after(
                inputs,
                "aws_region",
                {
                    "name": "eks_cluster",
                    "label": "EKS Cluster",
                    "type": "aws_resource",
                    "resource_type": "eks",
                    "return": "name",
                    "required": True,
                },
            )

        # Namespace
        replace_input(
            inputs,
            "namespace",
            {
                "name": "namespace",
                "label": "Kubernetes Namespace",
                "type": "aws_resource",
                "resource_type": "eks-namespace",
                "parent": "eks_cluster",
                "return": "name",
                "required": True,
            },
        )

        # Pod
        replace_input(
            inputs,
            "pod",
            {
                "name": "pod",
                "label": "Target Pod",
                "type": "aws_resource",
                "resource_type": "eks-pod",
                "parent": "namespace",
                "return": "name",
                "required": False,
            },
        )

        changed.append(experiment_id)

    # ---------------------------------------------------------
    # PHYSICAL MACHINE
    # ---------------------------------------------------------
    elif experiment_id == "chaos-mesh-physical-machine":

        # AWS Region
        if not any(i.get("name") == "aws_region" for i in inputs):
            inputs.insert(
                0,
                {
                    "name": "aws_region",
                    "label": "AWS Region",
                    "type": "text",
                    "required": True,
                    "default": "eu-central-1",
                },
            )

        # EKS Cluster
        if not any(i.get("name") == "eks_cluster" for i in inputs):
            add_input_after(
                inputs,
                "aws_region",
                {
                    "name": "eks_cluster",
                    "label": "EKS Cluster",
                    "type": "aws_resource",
                    "resource_type": "eks",
                    "return": "name",
                    "required": True,
                },
            )

        # Node
        replace_input(
            inputs,
            "node",
            {
                "name": "node",
                "label": "Target Node",
                "type": "aws_resource",
                "resource_type": "eks-node",
                "parent": "eks_cluster",
                "return": "name",
                "required": True,
            },
        )

        changed.append(experiment_id)

    # ---------------------------------------------------------
    # AWS CHAOS
    # ---------------------------------------------------------
    elif experiment_id == "chaos-mesh-aws":

        # Keep namespace as plain text because it is the
        # namespace of the AWSChaos CR itself.
        # AWS target is EC2, not an EKS workload.

        changed.append(experiment_id)


# Write UTF-8 WITHOUT BOM.
json_text = json.dumps(
    data,
    indent=4,
    ensure_ascii=False,
)

METADATA.write_text(
    json_text,
    encoding="utf-8",
)

print("Updated experiments:")
for item in changed:
    print(f"  ✓ {item}")

print()
print(f"Total updated: {len(changed)}")
print(f"Metadata: {METADATA}")
