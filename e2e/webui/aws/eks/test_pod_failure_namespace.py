from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


def test_pod_failure_cluster_loads_namespaces():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        goto_successfully(
            page,
            f"{BASE_URL}/experiment/chaos_mesh/chaos-mesh-pod-failure",
            wait_until="domcontentloaded",
        )

        # Select AWS region
        page.locator("#aws_region").select_option("eu-central-1")

        # Wait for EKS clusters
        page.wait_for_function(
            """() => {
                const select = document.querySelector('#eks_cluster');
                if (!select) return false;

                return Array.from(select.options).some(
                    option => option.value === 'Chaos-POC-v2'
                );
            }""",
            timeout=15000,
        )

        # Select the discovered EKS cluster
        page.locator("#eks_cluster").select_option("Chaos-POC-v2")

        # Wait for namespaces to load
        page.wait_for_function(
            """() => {
                const select = document.querySelector('#namespace');
                if (!select) return false;

                return Array.from(select.options).some(
                    option => option.value
                );
            }""",
            timeout=15000,
        )

        namespace = page.locator("#namespace")
        options = namespace.locator("option")

        print("\n=== NAMESPACES AFTER CLUSTER SELECTION ===")

        for option in options.all():
            print(
                f"TEXT={option.inner_text().strip()!r} "
                f"VALUE={option.get_attribute('value')!r}"
            )

        # At least one real namespace should be available
        real_namespaces = [
            option
            for option in options.all()
            if option.get_attribute("value")
        ]

        assert len(real_namespaces) > 0

        browser.close()
