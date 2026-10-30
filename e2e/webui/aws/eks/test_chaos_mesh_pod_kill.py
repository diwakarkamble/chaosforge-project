from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


def test_chaos_mesh_pod_kill_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # Go directly to EKS service page
            goto_successfully(
                page,
                BASE_URL + "/service/eks",
                wait_until="domcontentloaded",
            )

            page.wait_for_url("**/service/eks")

            # Open Chaos Mesh Pod Kill experiment
            pod_kill_link = page.locator(
                'a[href="/experiment/chaos_mesh/chaos-mesh-pod-kill"]'
            )

            pod_kill_link.wait_for(state="visible", timeout=15000)
            pod_kill_link.click()

            page.wait_for_url(
                "**/experiment/chaos_mesh/chaos-mesh-pod-kill"
            )

            body = page.locator("body").inner_text()

            assert "Pod Kill" in body
            assert page.locator("#aws_region").count() == 1
            assert page.locator("#eks_cluster").count() == 1
            assert page.locator("#namespace").count() == 1

        finally:
            browser.close()