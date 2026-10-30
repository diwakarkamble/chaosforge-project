from types import SimpleNamespace
from unittest.mock import Mock, patch

from chaosforge.application.campaigns.yaml_builder import build_campaign
from chaosforge.application.services.planning import PlanService


def test_chaos_mesh_yaml_to_plan_end_to_end():
    data = {
        "campaign": {
            "name": "chaos-mesh-e2e-plan",
        },
        "cloud": {
            "provider": "aws",
        },
        "experiments": [
            {
                "service": "chaos_mesh",
                "experiment": "chaos-mesh-pod-kill",
                "variables": {
                    "aws_region": "eu-central-1",
                    "eks_cluster": "cluster-1",
                    "namespace": "payments",
                    "pod": "payments-api-abc",
                },
            }
        ],
    }

    campaign = build_campaign(data)

    assert len(campaign.experiments) == 1

    experiment = campaign.experiments[0]

    discovery = Mock()

    discovery.discover.return_value = [
        {
            "id": "cluster-1",
            "name": "cluster-1",
            "type": "eks",
        }
    ]

    discovery.list_eks_namespaces.return_value = [
        {
            "id": "payments",
            "name": "payments",
            "type": "eks-namespace",
        }
    ]

    discovery.list_eks_pods.return_value = [
        {
            "id": "payments-api-abc",
            "name": "payments-api-abc",
            "type": "eks-pod",
        }
    ]

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
        return_value=None,
    ):
        service = PlanService(
            discovery_factory=lambda region: discovery,
            chaos_mesh_preflight_factory=lambda discovery: preflight,
        )

        with patch(
            "chaosforge.application.services.planning.load_metadata",
            wraps=lambda service_name: __import__(
                "chaosforge.application.metadata_loader",
                fromlist=["load_metadata"],
            ).load_metadata(service_name),
        ):
            result = service.plan_experiment(experiment)

    assert result.executable is True
    assert result.blockers == []

    assert len(result.experiments) == 1

    experiment_plan = result.experiments[0]

    assert experiment_plan["id"] == "chaos-mesh-pod-kill"
    assert experiment_plan["service"] == "chaos_mesh"
    assert experiment_plan["engine"] == "Chaos Mesh"
    assert experiment_plan["status"] == "PLANNED"

    preflight_data = experiment_plan["chaos_mesh_preflight"]

    assert preflight_data["status"] == "READY"
    assert preflight_data["kind"] == "PodChaos"
    assert preflight_data["cluster"] == "cluster-1"

    preflight.check.assert_called_once_with(
        cluster="cluster-1",
        kind="PodChaos",
        namespace="payments",
    )


def test_campaign_plan_allows_only_remediable_chaos_mesh_setup_blockers():
    campaign = build_campaign({
        "campaign": {"name": "mesh"},
        "cloud": {"provider": "aws"},
        "experiments": [{
            "service": "chaos_mesh",
            "experiment": "chaos-mesh-pod-kill",
            "variables": {
                "aws_region": "eu-central-1",
                "eks_cluster": "cluster-1",
                "namespace": "payments",
                "pod": "payments-api-abc",
            },
        }],
    })
    discovery = Mock()
    discovery.discover.return_value = [{"id": "cluster-1", "name": "cluster-1"}]
    discovery.list_eks_namespaces.return_value = [{"id": "payments", "name": "payments"}]
    discovery.list_eks_pods.return_value = [{"id": "payments-api-abc", "name": "payments-api-abc"}]
    preflight = Mock()
    preflight.check.return_value = SimpleNamespace(
        status="BLOCKED", executable=False, checks=[], warnings=[],
        blockers=["Required Chaos Mesh CRD is unavailable: podchaos.chaos-mesh.org"],
    )
    service = PlanService(
        discovery_factory=lambda _region: discovery,
        chaos_mesh_preflight_factory=lambda _discovery: preflight,
    )

    allowed = service.plan_campaign(campaign, allow_chaos_mesh_setup=True)
    blocked = service.plan_campaign(campaign)

    assert allowed.executable is True
    assert allowed.experiments[0]["chaos_mesh_preflight"]["status"] == "SETUP_REQUIRED"
    assert blocked.executable is False

    preflight.check.return_value = SimpleNamespace(
        status="BLOCKED", executable=False, checks=[], warnings=[],
        blockers=["Kubernetes API is not available: denied"],
    )
    unsafe = service.plan_campaign(campaign, allow_chaos_mesh_setup=True)
    assert unsafe.executable is False
