from playwright.sync_api import expect

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


def test_pod_failure_region_loads_eks_clusters(browser):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/chaos_mesh/chaos-mesh-pod-failure",
            wait_until="domcontentloaded",
        )

        region = page.locator("#aws_region")
        cluster = page.locator("#eks_cluster")

        assert region.count() == 1
        assert cluster.count() == 1

        # Select the region containing the ChaosForge EKS test cluster
        region.select_option("eu-central-1")

        # Wait for dynamic EKS discovery to finish
        expect(
            cluster.locator('option[value="Chaos-POC-v2"]')
        ).to_have_count(1, timeout=15000)

        options = cluster.locator("option")

        print("\n=== EKS CLUSTERS AFTER REGION SELECTION ===")

        for option in options.all():
            print(
                f"TEXT={option.inner_text().strip()!r} "
                f"VALUE={option.get_attribute('value')!r}"
            )

        # The loading placeholder should be gone
        assert cluster.locator(
            "option",
            has_text="Loading...",
        ).count() == 0

        # There should be at least one selectable cluster
        assert options.count() > 1

        # Verify the expected cluster exists
        assert cluster.locator(
            'option[value="Chaos-POC-v2"]'
        ).count() == 1

    finally:
        page.close()