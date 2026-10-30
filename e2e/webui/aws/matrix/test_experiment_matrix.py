import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"

EXPERIMENTS = [
    # Native EKS
    ("eks", "eks-node-drain", "Node Drain"),
    ("eks", "eks-node-cordon", "Node Cordon"),
    ("eks", "eks-replica-reduction", "Replica Reduction"),
    ("eks", "eks-container-restart", "Container Restart"),

    # Chaos Mesh
    ("chaos_mesh", "chaos-mesh-pod-failure", "Pod Failure"),
    ("chaos_mesh", "chaos-mesh-pod-kill", "Pod Kill"),
    ("chaos_mesh", "chaos-mesh-container-kill", "Container Kill"),
    ("chaos_mesh", "chaos-mesh-network-delay", "Network Delay"),
    ("chaos_mesh", "chaos-mesh-network-loss", "Network Loss"),
    ("chaos_mesh", "chaos-mesh-network-duplicate", "Network Duplicate"),
    ("chaos_mesh", "chaos-mesh-network-corrupt", "Network Corrupt"),
    ("chaos_mesh", "chaos-mesh-network-reorder", "Network Reorder"),
    ("chaos_mesh", "chaos-mesh-network-partition", "Network Partition"),
    ("chaos_mesh", "chaos-mesh-network-bandwidth", "Network Bandwidth"),
    ("chaos_mesh", "chaos-mesh-cpu-stress", "CPU Stress"),
    ("chaos_mesh", "chaos-mesh-memory-stress", "Memory Stress"),
    ("chaos_mesh", "chaos-mesh-dns-error", "DNS Error"),
    ("chaos_mesh", "chaos-mesh-dns-random", "DNS Random"),
    ("chaos_mesh", "chaos-mesh-http-abort", "HTTP Abort"),
    ("chaos_mesh", "chaos-mesh-http-delay", "HTTP Delay"),
    ("chaos_mesh", "chaos-mesh-http-replace", "HTTP Replace"),
    ("chaos_mesh", "chaos-mesh-http-patch", "HTTP Patch"),
    ("chaos_mesh", "chaos-mesh-io-latency", "IO Latency"),
    ("chaos_mesh", "chaos-mesh-io-fault", "IO Fault"),
    ("chaos_mesh", "chaos-mesh-io-attr-override", "IO Attr Override"),
    ("chaos_mesh", "chaos-mesh-io-mistake", "IO Mistake"),
    ("chaos_mesh", "chaos-mesh-time", "Time"),
    ("chaos_mesh", "chaos-mesh-kernel", "Kernel"),
    ("chaos_mesh", "chaos-mesh-aws", "AWS"),
    ("chaos_mesh", "chaos-mesh-jvm", "JVM"),
    ("chaos_mesh", "chaos-mesh-block", "Block"),
    ("chaos_mesh", "chaos-mesh-physical-machine", "Physical Machine"),
    ("chaos_mesh", "chaos-mesh-workflow", "Workflow"),
    ("chaos_mesh", "chaos-mesh-schedule", "Schedule"),
    ("chaos_mesh", "chaos-mesh-status-check", "Status Check"),
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize(
    "engine,experiment_id,expected_text",
    EXPERIMENTS,
)
def test_experiment_page_loads(
    browser,
    engine,
    experiment_id,
    expected_text,
):
    page = browser.new_page()

    try:
        url = (
            f"{BASE_URL}/experiment/"
            f"{engine}/{experiment_id}"
        )

        response = goto_successfully(page,url, wait_until="networkidle")
        assert_no_application_error(page)

        assert response is not None
        assert response.ok, f"HTTP {response.status} for {url}"

        body = page.locator("body").inner_text()

        assert "Experiment Description" in body, (
            f"Experiment page content missing for {url}"
        )

        assert "Add Experiment" in body, (
            f"Add Experiment button missing for {url}"
        )

    finally:
        page.close()
