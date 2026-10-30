import os

import pytest
from playwright.sync_api import expect, sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000")
AWS_REGION = os.getenv("CHAOSFORGE_TEST_AWS_REGION")
EKS_CLUSTER = os.getenv("CHAOSFORGE_TEST_EKS_CLUSTER")
EKS_NAMESPACE = os.getenv("CHAOSFORGE_TEST_EKS_NAMESPACE")


def require_test_config():
    missing = [name for name, value in {
        "CHAOSFORGE_TEST_AWS_REGION": AWS_REGION,
        "CHAOSFORGE_TEST_EKS_CLUSTER": EKS_CLUSTER,
        "CHAOSFORGE_TEST_EKS_NAMESPACE": EKS_NAMESPACE,
    }.items() if not value]
    if missing:
        pytest.skip("Set required test configuration: " + ", ".join(missing))

CHAOS_MESH_POD_EXPERIMENTS = [
    "/experiment/chaos_mesh/chaos-mesh-pod-failure",
    "/experiment/chaos_mesh/chaos-mesh-pod-kill",
    "/experiment/chaos_mesh/chaos-mesh-container-kill",
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def select_real_option(page, selector):
    locator = page.locator(selector)

    assert locator.count() == 1

    options = locator.locator("option")

    expect(options).to_have_count(
        2,
        timeout=10000,
    )

    for i in range(options.count()):
        option = options.nth(i)
        value = option.get_attribute("value")
        text = option.inner_text().strip()

        if value and value.strip():
            locator.select_option(value)
            return text

    pytest.fail(f"No usable option found for {selector}")


@pytest.mark.parametrize(
    "experiment_url",
    CHAOS_MESH_POD_EXPERIMENTS,
)
def test_chaos_mesh_pod_resource_discovery(
    browser,
    experiment_url,
):
    require_test_config()
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            BASE_URL + experiment_url,
            wait_until="domcontentloaded",
        )
        assert response is not None
        assert response.ok

        # --------------------------------------------------
        # Region
        # --------------------------------------------------
        region = page.locator("#aws_region")

        assert region.count() == 1

        region.select_option(AWS_REGION)

        # --------------------------------------------------
        # EKS Cluster
        # --------------------------------------------------
        cluster = page.locator("#eks_cluster")

        cluster_option = cluster.locator(f'option[value="{EKS_CLUSTER}"]')
        expect(cluster_option).to_have_count(1, timeout=15000)
        cluster.select_option(EKS_CLUSTER)

        # --------------------------------------------------
        # Namespace
        # --------------------------------------------------
        namespace = page.locator("#namespace")

        namespace_option = namespace.locator(f'option[value="{EKS_NAMESPACE}"]')
        expect(namespace_option).to_have_count(1, timeout=15000)
        namespace.select_option(EKS_NAMESPACE)

        # --------------------------------------------------
        # Target mode
        # --------------------------------------------------
        target_mode = page.locator("#target_mode")

        assert target_mode.count() == 1

        target_mode.select_option("pod")

        # --------------------------------------------------
        # Pod
        # --------------------------------------------------
        pod = page.locator("#pod")

        assert pod.count() == 1

        expect(
            pod.locator("option")
        ).not_to_have_count(
            1,
            timeout=10000,
        )

        pod_options = pod.locator("option")

        pod_name = None

        for i in range(pod_options.count()):
            option = pod_options.nth(i)

            value = option.get_attribute("value")
            text = option.inner_text().strip()

            if value and value.strip():
                pod_name = text
                pod.select_option(value)
                break

        assert pod_name is not None
        assert "Select" not in pod_name

    finally:
        page.close()

