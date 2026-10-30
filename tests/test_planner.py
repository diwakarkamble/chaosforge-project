from types import SimpleNamespace
from unittest.mock import Mock, patch

from chaosforge.application.services.planning import PlanService
from chaosforge.models.planning import PlanResult


def make_experiment(
    experiment_id="lambda-memory",
    service="lambda",
    name="Lambda Memory Change",
    variables=None,
    engine="Chaos Toolkit",
):
    return SimpleNamespace(
        id=experiment_id,
        service=service,
        name=name,
        json_file="experiment.json",
        variables=variables or {},
        engine=engine,
    )


def make_metadata(
    *,
    resource_inputs=None,
    iam=None,
    definition=None,
):
    experiment_definition = {
        "id": "lambda-memory",
        "name": "Lambda Memory Change",
        "inputs": resource_inputs or [],
        "iam": iam or {},
    }

    if definition:
        experiment_definition.update(definition)

    return {
        "experiments": [experiment_definition],
    }


def make_discovery():
    discovery = Mock()

    discovery.discover.return_value = [
        {
            "id": "cluster-1",
            "name": "cluster-1",
            "type": "eks",
        },
        {
            "id": "lambda-a",
            "name": "lambda-a",
            "arn": "arn:aws:lambda:eu-central-1:123:function:lambda-a",
            "type": "lambda",
        },
        {
            "id": "lambda-b",
            "name": "lambda-b",
            "arn": "arn:aws:lambda:eu-central-1:123:function:lambda-b",
            "type": "lambda",
        },
    ]

    discovery.discover.side_effect = lambda resource_type: (
        [
            {
                "id": "cluster-1",
                "name": "cluster-1",
                "type": "eks",
            }
        ]
        if resource_type == "eks"
        else [
            {
                "id": "lambda-a",
                "name": "lambda-a",
                "arn": "arn:aws:lambda:eu-central-1:123:function:lambda-a",
                "type": "lambda",
            },
            {
                "id": "lambda-b",
                "name": "lambda-b",
                "arn": "arn:aws:lambda:eu-central-1:123:function:lambda-b",
                "type": "lambda",
            },
        ]
    )

    discovery.list_eks_nodes.return_value = [
        {
            "id": "node-1",
            "name": "node-1",
            "type": "eks-node",
        },
        {
            "id": "node-2",
            "name": "node-2",
            "type": "eks-node",
        },
    ]

    discovery.list_eks_namespaces.return_value = [
        {
            "id": "default",
            "name": "default",
            "type": "eks-namespace",
        },
        {
            "id": "payments",
            "name": "payments",
            "type": "eks-namespace",
        },
    ]

    discovery.list_eks_deployments.return_value = [
        {
            "id": "payments-api",
            "name": "payments-api",
            "type": "eks-deployment",
        },
        {
            "id": "payments-worker",
            "name": "payments-worker",
            "type": "eks-deployment",
        },
    ]

    discovery.list_eks_pods.return_value = [
        {
            "id": "payments-api-abc",
            "name": "payments-api-abc",
            "type": "eks-pod",
        },
        {
            "id": "payments-api-def",
            "name": "payments-api-def",
            "type": "eks-pod",
        },
    ]

    return discovery


def plan(experiment, metadata, discovery):
    with patch("chaosforge.application.services.planning.load_metadata", return_value=metadata):
        service = PlanService(
            discovery_factory=lambda region: discovery
        )
        return service.plan_experiment(experiment)


def test_plan_result_defaults_are_conservative():
    result = PlanResult()

    assert result.executable is True
    assert result.impact["traffic"]["status"] == "UNKNOWN"
    assert result.impact["customer_impact"]["status"] == "UNKNOWN"
    assert result.duration["status"] == "UNKNOWN"
    assert result.recovery["behavior"] == "UNKNOWN"


def test_plan_result_becomes_non_executable_when_blocker_is_added():
    result = PlanResult()
    result.blockers.append("Target was not found.")

    result.finalize()

    assert result.executable is False


def test_lambda_target_is_resolved_by_name():
    discovery = make_discovery()

    experiment = make_experiment(
        variables={
            "aws_region": "eu-central-1",
            "lambda_name": "lambda-a",
            "wait_seconds": 30,
        }
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "lambda_name",
                "type": "aws_resource",
                "resource_type": "lambda",
                "return": "name",
            }
        ],
        iam={
            "read": ["lambda:GetFunction"],
            "modify": ["lambda:UpdateFunctionConfiguration"],
        },
    )

    result = plan(experiment, metadata, discovery)

    assert result.executable is True
    assert len(result.targets) == 1
    assert result.targets[0]["name"] == "lambda-a"
    assert result.duration["estimated_seconds"] == 30

    discovery.discover.assert_called_once_with("lambda")


def test_missing_lambda_target_creates_blocker():
    discovery = make_discovery()

    experiment = make_experiment(
        variables={
            "aws_region": "eu-central-1",
            "lambda_name": "does-not-exist",
        }
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "lambda_name",
                "type": "aws_resource",
                "resource_type": "lambda",
                "return": "name",
            }
        ]
    )

    result = plan(experiment, metadata, discovery)

    assert result.executable is False
    assert result.blockers
    assert any(
        "does-not-exist" in blocker
        for blocker in result.blockers
    )


def test_eks_node_child_target_is_resolved():
    discovery = make_discovery()

    experiment = make_experiment(
        experiment_id="eks-node-cordon",
        service="eks",
        name="EKS Node Cordon",
        variables={
            "aws_region": "eu-central-1",
            "eks_cluster": "cluster-1",
            "node_name": "node-1",
            "wait_seconds": 30,
        },
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "eks_cluster",
                "type": "aws_resource",
                "resource_type": "eks",
                "return": "name",
            },
            {
                "name": "node_name",
                "type": "aws_resource",
                "resource_type": "eks-node",
                "parent": "eks_cluster",
                "return": "name",
            },
        ],
        definition={
            "id": "eks-node-cordon",
            "name": "EKS Node Cordon",
        },
    )

    result = plan(experiment, metadata, discovery)

    assert result.executable is True
    assert any(
        target["name"] == "node-1"
        for target in result.targets
    )

    discovery.list_eks_nodes.assert_called_once_with("cluster-1")


def test_eks_namespace_deployment_child_target_is_resolved():
    discovery = make_discovery()

    experiment = make_experiment(
        experiment_id="eks-replica-reduction",
        service="eks",
        name="EKS Replica Reduction",
        variables={
            "aws_region": "eu-central-1",
            "eks_cluster": "cluster-1",
            "namespace": "payments",
            "deployment_name": "payments-api",
            "reduced_replicas": 1,
            "wait_seconds": 30,
        },
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "eks_cluster",
                "type": "aws_resource",
                "resource_type": "eks",
                "return": "name",
            },
            {
                "name": "namespace",
                "type": "aws_resource",
                "resource_type": "eks-namespace",
                "parent": "eks_cluster",
                "return": "name",
            },
            {
                "name": "deployment_name",
                "type": "aws_resource",
                "resource_type": "eks-deployment",
                "parent": "namespace",
                "return": "name",
            },
        ],
        definition={
            "id": "eks-replica-reduction",
            "name": "EKS Replica Reduction",
        },
    )

    result = plan(experiment, metadata, discovery)

    assert result.executable is True
    assert any(
        target["name"] == "payments-api"
        for target in result.targets
    )

    discovery.list_eks_deployments.assert_called_once_with(
        "cluster-1",
        "payments",
    )


def test_eks_pod_child_target_is_resolved():
    discovery = make_discovery()

    experiment = make_experiment(
        experiment_id="eks-container-restart",
        service="eks",
        name="EKS Container Restart",
        variables={
            "aws_region": "eu-central-1",
            "eks_cluster": "cluster-1",
            "namespace": "payments",
            "pod_name": "payments-api-abc",
            "wait_seconds": 30,
        },
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "eks_cluster",
                "type": "aws_resource",
                "resource_type": "eks",
                "return": "name",
            },
            {
                "name": "namespace",
                "type": "aws_resource",
                "resource_type": "eks-namespace",
                "parent": "eks_cluster",
                "return": "name",
            },
            {
                "name": "pod_name",
                "type": "aws_resource",
                "resource_type": "eks-pod",
                "parent": "namespace",
                "return": "name",
            },
        ],
        definition={
            "id": "eks-container-restart",
            "name": "EKS Container Restart",
        },
    )

    result = plan(experiment, metadata, discovery)

    assert result.executable is True
    assert any(
        target["name"] == "payments-api-abc"
        for target in result.targets
    )

    discovery.list_eks_pods.assert_called_once_with(
        "cluster-1",
        "payments",
    )


def test_permissions_are_collected_from_metadata():
    discovery = make_discovery()

    experiment = make_experiment(
        variables={
            "aws_region": "eu-central-1",
            "lambda_name": "lambda-a",
        }
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "lambda_name",
                "type": "aws_resource",
                "resource_type": "lambda",
                "return": "name",
            }
        ],
        iam={
            "read": [
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
            ],
            "modify": [
                "lambda:UpdateFunctionConfiguration",
            ],
            "delete": [
                "lambda:DeleteFunction",
            ],
        },
    )

    result = plan(experiment, metadata, discovery)

    actions = {
        permission["action"]
        for permission in result.permissions
    }

    assert "lambda:GetFunction" in actions
    assert "lambda:GetFunctionConfiguration" in actions
    assert "lambda:UpdateFunctionConfiguration" in actions
    assert "lambda:DeleteFunction" in actions


def test_duration_uses_timeout_when_wait_seconds_is_not_present():
    discovery = make_discovery()

    experiment = make_experiment(
        experiment_id="eks-node-drain",
        service="eks",
        name="EKS Node Drain",
        variables={
            "aws_region": "eu-central-1",
            "eks_cluster": "cluster-1",
            "node_name": "node-1",
            "timeout": 120,
        },
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "eks_cluster",
                "type": "aws_resource",
                "resource_type": "eks",
                "return": "name",
            },
            {
                "name": "node_name",
                "type": "aws_resource",
                "resource_type": "eks-node",
                "parent": "eks_cluster",
                "return": "name",
            },
        ],
        definition={
            "id": "eks-node-drain",
            "name": "EKS Node Drain",
        },
    )

    result = plan(experiment, metadata, discovery)

    assert result.duration["estimated_seconds"] == 120


def test_experiment_without_resource_inputs_gets_pseudo_target():
    discovery = make_discovery()

    experiment = make_experiment(
        experiment_id="network-latency",
        service="vpc",
        name="Network Latency",
        variables={
            "aws_region": "eu-central-1",
            "wait_seconds": 60,
        },
    )

    metadata = make_metadata(
        resource_inputs=[],
        definition={
            "id": "network-latency",
            "name": "Network Latency",
        },
    )

    result = plan(experiment, metadata, discovery)

    assert result.executable is True
    assert result.targets
    assert result.targets[0]["resource_id"] == "network-latency"
    assert result.targets[0]["resource_type"] == "experiment"


def test_traffic_and_customer_impact_remain_unknown_without_telemetry():
    discovery = make_discovery()

    experiment = make_experiment(
        variables={
            "aws_region": "eu-central-1",
            "lambda_name": "lambda-a",
        }
    )

    metadata = make_metadata(
        resource_inputs=[
            {
                "name": "lambda_name",
                "type": "aws_resource",
                "resource_type": "lambda",
                "return": "name",
            }
        ]
    )

    result = plan(experiment, metadata, discovery)

    assert result.impact["traffic"]["status"] == "UNKNOWN"
    assert result.impact["customer_impact"]["status"] == "UNKNOWN"


def test_plan_result_serializes_to_dict():
    result = PlanResult()

    payload = result.to_dict()

    assert isinstance(payload, dict)
    assert "experiments" in payload
    assert "targets" in payload
    assert "impact" in payload
    assert "permissions" in payload
    assert "capabilities" in payload
    assert "duration" in payload
    assert "recovery" in payload
    assert "warnings" in payload
    assert "blockers" in payload

def test_chaos_mesh_plan_reports_ready_preflight():
    discovery = make_discovery()

    experiment = make_experiment(
        experiment_id="chaos-mesh-pod-kill",
        service="chaos_mesh",
        name="Chaos Mesh Pod Kill",
        variables={
            "aws_region": "eu-central-1",
            "eks_cluster": "cluster-1",
            "namespace": "payments",
            "pod": "payments-api-abc",
        },
        engine="Chaos Mesh",
    )

    metadata = make_metadata(
        definition={
            "id": "chaos-mesh-pod-kill",
            "name": "Chaos Mesh Pod Kill",
            "inputs": [
                {
                    "name": "eks_cluster",
                    "type": "aws_resource",
                    "resource_type": "eks",
                },
                {
                    "name": "namespace",
                    "type": "aws_resource",
                    "resource_type": "eks-namespace",
                    "parent": "eks_cluster",
                },
                {
                    "name": "pod",
                    "type": "aws_resource",
                    "resource_type": "eks-pod",
                    "parent": "namespace",
                },
            ],
            "chaos_mesh": {
                "kind": "PodChaos",
                "action": "pod-kill",
            },
        }
    )

    preflight = Mock()
    preflight.check.return_value = SimpleNamespace(
        status="READY",
        executable=True,
        checks=[
            {
                "name": "Kubernetes API",
                "status": "READY",
            },
            {
                "name": "PodChaos CRD",
                "status": "READY",
            },
            {
                "name": "Chaos Controller Manager",
                "status": "READY",
            },
            {
                "name": "Chaos Daemon",
                "status": "READY",
            },
        ],
        blockers=[],
        warnings=[],
    )

    with patch(
        "chaosforge.application.services.planning.load_metadata",
        return_value=metadata,
    ):
        service = PlanService(
            discovery_factory=lambda region: discovery,
            chaos_mesh_preflight_factory=lambda discovery: preflight,
        )

        result = service.plan_experiment(experiment)

    assert result.executable is True
    assert result.blockers == []

    experiment_plan = result.experiments[0]

    assert experiment_plan["status"] == "PLANNED"
    assert experiment_plan["chaos_mesh_preflight"]["status"] == "READY"
    assert experiment_plan["chaos_mesh_preflight"]["kind"] == "PodChaos"
    assert experiment_plan["chaos_mesh_preflight"]["cluster"] == "cluster-1"

    preflight.check.assert_called_once_with(
        cluster="cluster-1",
        kind="PodChaos",
        namespace="payments",
    )


def test_chaos_mesh_plan_blocks_when_preflight_fails():
    discovery = make_discovery()

    experiment = make_experiment(
        experiment_id="chaos-mesh-pod-kill",
        service="chaos_mesh",
        name="Chaos Mesh Pod Kill",
        variables={
            "aws_region": "eu-central-1",
            "eks_cluster": "cluster-1",
            "namespace": "payments",
            "pod": "payments-api-abc",
        },
        engine="Chaos Mesh",
    )

    metadata = make_metadata(
        definition={
            "id": "chaos-mesh-pod-kill",
            "name": "Chaos Mesh Pod Kill",
            "inputs": [
                {
                    "name": "eks_cluster",
                    "type": "aws_resource",
                    "resource_type": "eks",
                },
                {
                    "name": "namespace",
                    "type": "aws_resource",
                    "resource_type": "eks-namespace",
                    "parent": "eks_cluster",
                },
                {
                    "name": "pod",
                    "type": "aws_resource",
                    "resource_type": "eks-pod",
                    "parent": "namespace",
                },
            ],
            "chaos_mesh": {
                "kind": "PodChaos",
                "action": "pod-kill",
            },
        }
    )

    preflight = Mock()
    preflight.check.return_value = SimpleNamespace(
        status="BLOCKED",
        executable=False,
        checks=[
            {
                "name": "PodChaos CRD",
                "status": "READY",
            },
            {
                "name": "Chaos Controller Manager",
                "status": "FAILED",
            },
        ],
        blockers=[
            "Chaos Mesh Controller Manager is not ready.",
        ],
        warnings=[],
    )

    with patch(
        "chaosforge.application.services.planning.load_metadata",
        return_value=metadata,
    ):
        service = PlanService(
            discovery_factory=lambda region: discovery,
            chaos_mesh_preflight_factory=lambda discovery: preflight,
        )

        result = service.plan_experiment(experiment)

    assert result.executable is False
    assert any(
        "Controller Manager is not ready" in blocker
        for blocker in result.blockers
    )

    experiment_plan = result.experiments[0]

    assert experiment_plan["status"] == "BLOCKED"
    assert experiment_plan["chaos_mesh_preflight"]["status"] == "BLOCKED"
    assert experiment_plan["chaos_mesh_preflight"]["blockers"] == [
        "Chaos Mesh Controller Manager is not ready.",
    ]
