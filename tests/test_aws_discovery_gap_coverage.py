from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.providers.aws.discovery import AWSDiscovery


@pytest.fixture(autouse=True)
def quiet_ui(monkeypatch):
    context = MagicMock()
    context.__enter__.return_value = None
    context.__exit__.return_value = None
    monkeypatch.setattr("chaosforge.providers.aws.discovery.spinner", lambda _message: context)
    monkeypatch.setattr("chaosforge.providers.aws.discovery.info", lambda _message: None)


def install_kubernetes_api_mocks(monkeypatch):
    core = object()
    apps = object()
    custom = object()
    monkeypatch.setattr("chaosforge.providers.aws.discovery.client.CoreV1Api", lambda: core)
    monkeypatch.setattr("chaosforge.providers.aws.discovery.client.AppsV1Api", lambda: apps)
    monkeypatch.setattr("chaosforge.providers.aws.discovery.client.CustomObjectsApi", lambda: custom)
    return core, apps, custom


def test_configure_eks_client_creates_and_loads_temporary_kubeconfig(monkeypatch):
    discovery = AWSDiscovery("eu-west-1")
    list_contexts = MagicMock(
        side_effect=[
            RuntimeError("no default config"),
            ([{"name": "generated", "context": {"cluster": "team/demo"}}], None),
        ]
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts", list_contexts
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.tempfile.mkstemp",
        lambda **_kwargs: (17, "/tmp/generated-kubeconfig"),
    )
    close = MagicMock()
    run = MagicMock()
    load = MagicMock()
    monkeypatch.setattr("chaosforge.providers.aws.discovery.os.close", close)
    monkeypatch.setattr("chaosforge.providers.aws.discovery.subprocess.run", run)
    monkeypatch.setattr("chaosforge.providers.aws.discovery.config.load_kube_config", load)
    apis = install_kubernetes_api_mocks(monkeypatch)

    discovery._configure_eks_kubernetes_client("demo")

    close.assert_called_once_with(17)
    run.assert_called_once_with(
        [
            "aws",
            "eks",
            "update-kubeconfig",
            "--name",
            "demo",
            "--region",
            "eu-west-1",
            "--kubeconfig",
            "/tmp/generated-kubeconfig",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    load.assert_called_once_with(config_file="/tmp/generated-kubeconfig", context="generated")
    assert discovery.eks_kubeconfig_temporary is True
    assert discovery.eks_kubeconfig_path == "/tmp/generated-kubeconfig"
    assert (discovery.k8s_core_api, discovery.k8s_apps_api, discovery.k8s_custom_api) == apis


def test_configure_eks_client_removes_temp_file_when_context_is_missing(monkeypatch):
    discovery = AWSDiscovery("eu-west-1")
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        MagicMock(side_effect=[([], None), ([], None)]),
    )
    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.tempfile.mkstemp",
        lambda **_kwargs: (18, "/tmp/bad-kubeconfig"),
    )
    monkeypatch.setattr("chaosforge.providers.aws.discovery.os.close", lambda _fd: None)
    monkeypatch.setattr("chaosforge.providers.aws.discovery.subprocess.run", lambda *_a, **_k: None)
    remove = MagicMock(side_effect=OSError("already gone"))
    monkeypatch.setattr("chaosforge.providers.aws.discovery.os.remove", remove)

    with pytest.raises(RuntimeError, match="Unable to find kubeconfig context"):
        discovery._configure_eks_kubernetes_client("missing")

    remove.assert_called_once_with("/tmp/bad-kubeconfig")


def test_ecs_discovery_maps_clusters_services_tasks_and_arns(monkeypatch):
    ecs = MagicMock()
    ecs.list_clusters.return_value = {"clusterArns": ["cluster-arn"]}
    ecs.describe_clusters.return_value = {
        "clusters": [{"clusterName": "cluster", "clusterArn": "cluster-arn"}]
    }
    ecs.list_services.return_value = {"serviceArns": ["ec2-service", "fargate-service"]}
    ecs.describe_services.return_value = {
        "services": [
            {"launchType": "EC2"},
            {
                "launchType": "FARGATE",
                "serviceName": "api",
                "serviceArn": "service-arn",
                "desiredCount": 3,
                "runningCount": 2,
                "taskDefinition": "task-def",
            },
        ]
    }
    ecs.list_tasks.return_value = {"taskArns": ["arn:task/123456789012345"]}
    ecs.describe_tasks.return_value = {
        "tasks": [{"taskArn": "arn:task/123456789012345", "lastStatus": "RUNNING"}]
    }
    monkeypatch.setattr("chaosforge.providers.aws.discovery.boto3.client", lambda *_a, **_k: ecs)
    discovery = AWSDiscovery("eu-west-1")

    assert discovery.list_ecs_clusters() == [{"name": "cluster", "arn": "cluster-arn"}]
    assert discovery.list_ecs_services("cluster") == [
        {
            "name": "api",
            "arn": "service-arn",
            "cluster": "cluster",
            "desired_count": 3,
            "running_count": 2,
            "task_definition": "task-def",
        }
    ]
    assert discovery.list_ecs_tasks("cluster", "api") == [
        {
            "name": "123456789012",
            "task_arn": "arn:task/123456789012345",
            "cluster": "cluster",
            "service": "api",
            "status": "RUNNING",
        }
    ]
    assert discovery.get_ecs_task_arns("cluster", "api") == ["arn:task/123456789012345"]


def test_eks_cluster_discovery_describes_each_cluster(monkeypatch):
    eks = MagicMock()
    eks.list_clusters.return_value = {"clusters": ["blue", "green"]}
    eks.describe_cluster.side_effect = [
        {"cluster": {"arn": "blue-arn", "status": "ACTIVE", "version": "1.30"}},
        {"cluster": {"arn": "green-arn", "status": "CREATING", "version": "1.29"}},
    ]
    monkeypatch.setattr("chaosforge.providers.aws.discovery.boto3.client", lambda *_a, **_k: eks)

    assert AWSDiscovery("eu-west-1").list_eks_clusters() == [
        {"name": "blue", "arn": "blue-arn", "status": "ACTIVE", "version": "1.30"},
        {
            "name": "green",
            "arn": "green-arn",
            "status": "CREATING",
            "version": "1.29",
        },
    ]


def test_eks_node_discovery_reports_missing_config_and_context(monkeypatch):
    discovery = AWSDiscovery("eu-west-1")
    from kubernetes.config.config_exception import ConfigException

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        MagicMock(side_effect=ConfigException("missing")),
    )
    with pytest.raises(LookupError, match="Kubernetes configuration was not found"):
        discovery.list_eks_nodes("demo")

    monkeypatch.setattr(
        "chaosforge.providers.aws.discovery.config.list_kube_config_contexts",
        lambda: ([{"name": "other", "context": {"cluster": "other"}}], None),
    )
    with pytest.raises(LookupError, match="No Kubernetes context found"):
        discovery.list_eks_nodes("demo")


def test_kubernetes_resource_discovery_maps_all_supported_objects(monkeypatch):
    discovery = AWSDiscovery("eu-west-1")
    configure = MagicMock()
    monkeypatch.setattr(discovery, "_configure_eks_kubernetes_client", configure)
    core = MagicMock()
    apps = MagicMock()
    custom = MagicMock()
    discovery.k8s_core_api = core
    discovery.k8s_apps_api = apps
    discovery.k8s_custom_api = custom
    core.list_namespace.return_value.items = [SimpleNamespace(metadata=SimpleNamespace(name="ns"))]
    apps.list_namespaced_deployment.return_value.items = [
        SimpleNamespace(metadata=SimpleNamespace(name="api"), spec=SimpleNamespace(replicas=None))
    ]
    core.list_namespaced_pod.return_value.items = [
        SimpleNamespace(metadata=SimpleNamespace(name="pod", owner_references=None), status=None),
        SimpleNamespace(
            metadata=SimpleNamespace(
                name="owned",
                owner_references=[
                    SimpleNamespace(kind="StatefulSet", name="wrong"),
                    SimpleNamespace(kind="Deployment", name="api"),
                ],
            ),
            status=SimpleNamespace(phase="Running"),
        ),
    ]
    core.read_namespaced_pod.return_value = SimpleNamespace(
        spec=SimpleNamespace(volumes=[SimpleNamespace(name="data")])
    )
    custom.list_cluster_custom_object.return_value = {
        "items": [
            {"metadata": {"name": "machine", "namespace": "machines"}},
            {"metadata": {"name": "default-machine"}},
        ]
    }

    assert discovery.list_eks_namespaces("demo") == [{"name": "ns", "cluster": "demo"}]
    assert discovery.list_eks_deployments("demo", "ns") == [
        {"name": "api", "namespace": "ns", "cluster": "demo", "replicas": 0}
    ]
    assert discovery.list_eks_pods("demo", "ns")[0]["status"] == "Unknown"
    assert discovery.find_eks_pods_by_owner("demo", "ns", "Deployment", "api") == [
        {
            "name": "owned",
            "namespace": "ns",
            "cluster": "demo",
            "status": "Running",
            "owner_kind": "Deployment",
            "owner_name": "api",
        }
    ]
    assert discovery.list_eks_volumes("demo", "ns", "owned") == [
        {"name": "data", "id": "data", "cluster": "demo", "namespace": "ns", "pod": "owned"}
    ]
    assert discovery.list_chaos_physical_machines("demo") == [
        {"name": "machine", "id": "machine", "namespace": "machines", "cluster": "demo"},
        {
            "name": "default-machine",
            "id": "default-machine",
            "namespace": "default",
            "cluster": "demo",
        },
    ]


def test_elb_targets_skip_entries_without_target_id(monkeypatch):
    elb = MagicMock()
    elb.describe_target_health.return_value = {
        "TargetHealthDescriptions": [{"Target": {}, "TargetHealth": {"State": "unused"}}]
    }
    monkeypatch.setattr("chaosforge.providers.aws.discovery.boto3.client", lambda *_a, **_k: elb)

    assert AWSDiscovery("eu-west-1").list_elb_targets("tg") == []


def test_route_discovery_formats_every_target_type(monkeypatch):
    routes = [
        {"DestinationIpv6CidrBlock": "::/0", "TransitGatewayId": "tgw-1"},
        {"DestinationCidrBlock": "10.1.0.0/16", "VpcPeeringConnectionId": "pcx-1"},
        {"DestinationCidrBlock": "10.2.0.0/16", "NetworkInterfaceId": "eni-1"},
        {"DestinationCidrBlock": "10.3.0.0/16", "InstanceId": "i-1"},
        {"DestinationPrefixListId": "pl-destination", "VpcEndpointId": "vpce-1"},
    ]
    ec2 = MagicMock()
    ec2.describe_route_tables.return_value = {"RouteTables": [{"Routes": routes}]}
    monkeypatch.setattr("chaosforge.providers.aws.discovery.boto3.client", lambda *_a, **_k: ec2)

    names = [item["name"] for item in AWSDiscovery("eu-west-1").list_routes("rt-1")]

    assert names == [
        "::/0 → TGW : tgw-1",
        "10.1.0.0/16 → Peering : pcx-1",
        "10.2.0.0/16 → ENI : eni-1",
        "10.3.0.0/16 → EC2 : i-1",
        "pl-destination → Endpoint : vpce-1",
    ]
