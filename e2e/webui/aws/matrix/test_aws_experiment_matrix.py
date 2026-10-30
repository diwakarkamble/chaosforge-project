import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"


AWS_EXPERIMENTS = [
    # API Gateway
    "/experiment/apigateway/apigateway-stage-throttling",
    "/experiment/apigateway/apigateway-stage-cache",
    "/experiment/apigateway/apigateway-stage-cache-ttl",
    "/experiment/apigateway/apigateway-access-logging",
    "/experiment/apigateway/apigateway-xray",
    "/experiment/apigateway/apigateway-stage-variables",

    # DynamoDB
    "/experiment/dynamodb/dynamodb-capacity",
    "/experiment/dynamodb/dynamodb-pitr",
    "/experiment/dynamodb/dynamodb-stream",
    "/experiment/dynamodb/dynamodb-ttl",
    "/experiment/fis/fis-create-experiment?fis_service_id=dynamodb&fis_experiment_id=pause-global-table-replication",

    # EC2
    "/experiment/ec2/ec2-ebs-volume-detach",
    "/experiment/ec2/ec2-ebs-volume-attach",
    "/experiment/ec2/ec2-ebs-volume-detach-asg",
    "/experiment/ec2/ec2-ebs-volume-attach-asg",
    "/experiment/ec2/ec2-incremental-instance-stop",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=stop-instances",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=reboot-instances",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=terminate-instances",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=spot-instance-interruption",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=insufficient-instance-capacity-error",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=asg-insufficient-instance-capacity-error",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=ebs-pause-volume-io",
    "/experiment/fis/fis-create-experiment?fis_service_id=ec2&fis_experiment_id=ebs-volume-io-latency",

    # ECS
    "/experiment/ecs/ecs-desired-task-count",
    "/experiment/ecs/ecs-force-deployment",
    "/experiment/ecs/ecs-cpu-modification",
    "/experiment/ecs/ecs-memory-modification",
    "/experiment/ecs/ecs-task-definition-rollback",
    "/experiment/fis/fis-create-experiment?fis_service_id=ecs&fis_experiment_id=stop-task",
    "/experiment/fis/fis-create-experiment?fis_service_id=ecs&fis_experiment_id=cpu-stress",
    "/experiment/fis/fis-create-experiment?fis_service_id=ecs&fis_experiment_id=io-stress",
    "/experiment/fis/fis-create-experiment?fis_service_id=ecs&fis_experiment_id=network-latency",
    "/experiment/fis/fis-create-experiment?fis_service_id=ecs&fis_experiment_id=packet-loss",

    # EKS - Native
    "/experiment/eks/eks-node-drain",
    "/experiment/eks/eks-node-cordon",
    "/experiment/eks/eks-replica-reduction",
    "/experiment/eks/eks-container-restart",

    # EKS - Chaos Mesh
    "/experiment/chaos_mesh/chaos-mesh-pod-failure",
    "/experiment/chaos_mesh/chaos-mesh-pod-kill",
    "/experiment/chaos_mesh/chaos-mesh-container-kill",
    "/experiment/chaos_mesh/chaos-mesh-network-delay",
    "/experiment/chaos_mesh/chaos-mesh-network-loss",
    "/experiment/chaos_mesh/chaos-mesh-network-duplicate",
    "/experiment/chaos_mesh/chaos-mesh-network-corrupt",
    "/experiment/chaos_mesh/chaos-mesh-network-reorder",
    "/experiment/chaos_mesh/chaos-mesh-network-partition",
    "/experiment/chaos_mesh/chaos-mesh-network-bandwidth",
    "/experiment/chaos_mesh/chaos-mesh-cpu-stress",
    "/experiment/chaos_mesh/chaos-mesh-memory-stress",
    "/experiment/chaos_mesh/chaos-mesh-dns-error",
    "/experiment/chaos_mesh/chaos-mesh-dns-random",
    "/experiment/chaos_mesh/chaos-mesh-http-abort",
    "/experiment/chaos_mesh/chaos-mesh-http-delay",
    "/experiment/chaos_mesh/chaos-mesh-http-replace",
    "/experiment/chaos_mesh/chaos-mesh-http-patch",
    "/experiment/chaos_mesh/chaos-mesh-io-latency",
    "/experiment/chaos_mesh/chaos-mesh-io-fault",
    "/experiment/chaos_mesh/chaos-mesh-io-attr-override",
    "/experiment/chaos_mesh/chaos-mesh-io-mistake",
    "/experiment/chaos_mesh/chaos-mesh-time",
    "/experiment/chaos_mesh/chaos-mesh-kernel",
    "/experiment/chaos_mesh/chaos-mesh-aws",
    "/experiment/chaos_mesh/chaos-mesh-jvm",
    "/experiment/chaos_mesh/chaos-mesh-block",
    "/experiment/chaos_mesh/chaos-mesh-physical-machine",
    "/experiment/chaos_mesh/chaos-mesh-workflow",
    "/experiment/chaos_mesh/chaos-mesh-schedule",
    "/experiment/chaos_mesh/chaos-mesh-status-check",

    # EKS - FIS
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=inject-kubernetes-custom-resource",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=pod-cpu-stress",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=pod-delete",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=pod-io-stress",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=pod-memory-stress",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=pod-network-blackhole-port",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=pod-network-latency",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=pod-network-packet-loss",
    "/experiment/fis/fis-create-experiment?fis_service_id=eks&fis_experiment_id=terminate-nodegroup-instances",

    # ElastiCache
    "/experiment/elasticache/elasticache-security-group",
    "/experiment/elasticache/elasticache-snapshot-retention",
    "/experiment/elasticache/elasticache-reboot",
    "/experiment/elasticache/elasticache-usage-limit",
    "/experiment/elasticache/elasticache-daily-snapshot",
    "/experiment/fis/fis-create-experiment?fis_service_id=elasticache&fis_experiment_id=interrupt-az-power",

    # ELB
    "/experiment/elb/elb-target-deregistration",
    "/experiment/elb/elb-cross-zone",
    "/experiment/elb/elb-target-group",
    "/experiment/elb/elb-health-check",
    "/experiment/elb/elb-load-balancer",
    "/experiment/elb/elb-listener",
    "/experiment/elb/elb-deregistration-delay",
    "/experiment/fis/fis-create-experiment?fis_service_id=elb&fis_experiment_id=zonal-autoshift",

    # Kinesis - FIS only
    "/experiment/fis/fis-create-experiment?fis_service_id=kinesis&fis_experiment_id=kinesis-provisioned-throughput-exception",
    "/experiment/fis/fis-create-experiment?fis_service_id=kinesis&fis_experiment_id=kinesis-expired-iterator-exception",
    "/experiment/fis/fis-create-experiment?fis_service_id=kinesis&fis_experiment_id=kinesis-api-internal-error",
    "/experiment/fis/fis-create-experiment?fis_service_id=kinesis&fis_experiment_id=kinesis-api-throttle-error",
    "/experiment/fis/fis-create-experiment?fis_service_id=kinesis&fis_experiment_id=kinesis-api-unavailable-error",

    # Lambda
    "/experiment/lambda/lambda-memory",
    "/experiment/lambda/lambda-timeout",
    "/experiment/lambda/lambda-concurrency",
    "/experiment/lambda/lambda-provisioned-concurrency",
    "/experiment/lambda/lambda-retry",
    "/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id=invocation-delay",
    "/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id=invocation-error",
    "/experiment/fis/fis-create-experiment?fis_service_id=lambda&fis_experiment_id=http-response",

    # RDS
    "/experiment/rds/rds-instance-class",
    "/experiment/rds/rds-backup-retention",
    "/experiment/rds/rds-auto-minor-version-upgrade",
    "/experiment/rds/rds-deletion-protection",
    "/experiment/rds/rds-storage-autoscaling",
    "/experiment/rds/rds-iops",
    "/experiment/fis/fis-create-experiment?fis_service_id=rds&fis_experiment_id=reboot-instance",
    "/experiment/fis/fis-create-experiment?fis_service_id=rds&fis_experiment_id=failover-db-cluster",

    # S3
    "/experiment/s3/s3-versioning",
    "/experiment/s3/s3-encryption",
    "/experiment/s3/s3-public-access",
    "/experiment/s3/s3-lifecycle",
    "/experiment/s3/s3-bucket-policy",
    "/experiment/fis/fis-create-experiment?fis_service_id=s3&fis_experiment_id=pause-replication",

    # SNS
    "/experiment/sns/sns-publish-message",
    "/experiment/sns/sns-topic-policy",
    "/experiment/sns/sns-subscription-filter",
    "/experiment/sns/sns-delete-subscription",
    "/experiment/sns/sns-delivery-policy",

    # VPC
    "/experiment/vpc/vpc-security-group",
    "/experiment/vpc/vpc-route-table",
    "/experiment/vpc/vpc-network-acl",
    "/experiment/vpc/vpc-internet-gateway",

    # FIS service
    "/experiment/fis/fis-create-experiment",
    "/experiment/fis/fis-start-template",
    "/experiment/fis/fis-stop-experiment",
    "/experiment/fis/fis-delete-template",
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("experiment_url", AWS_EXPERIMENTS)
def test_aws_experiment_page(browser, experiment_url):
    page = browser.new_page()

    try:
        url = BASE_URL + experiment_url

        response = goto_successfully(page,url, wait_until="networkidle")
        assert_no_application_error(page)

        assert response is not None
        assert response.ok, (
            f"HTTP {response.status} for {url}"
        )

        body = page.locator("body").inner_text()

        assert "Experiment Description" in body, (
            f"Missing Experiment Description: {url}"
        )

        assert "Add Experiment" in body, (
            f"Missing Add Experiment button: {url}"
        )

    finally:
        page.close()
