from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


def test_eks_chaos_mesh_pod_failure():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("\n[1] Opening EKS page")

        goto_successfully(
            page,
            f"{BASE_URL}/service/eks",
            wait_until="domcontentloaded",
        )

        print(f"[2] Current URL: {page.url}")

        pod_failure_link = page.locator(
            'a[href="/experiment/chaos_mesh/chaos-mesh-pod-failure"]'
        )

        print(f"[3] Pod Failure links found: {pod_failure_link.count()}")

        assert pod_failure_link.count() == 1

        print("[4] Clicking Pod Failure")

        pod_failure_link.click(timeout=5000)

        print(f"[5] URL after click: {page.url}")

        print("[6] Waiting for experiment URL")

        page.wait_for_url(
            "**/experiment/chaos_mesh/chaos-mesh-pod-failure",
            timeout=5000,
        )

        print(f"[7] Final URL: {page.url}")

        body = page.locator("body").inner_text()

        print("[8] Experiment page loaded")

        assert "Pod Failure" in body
        assert "Chaos Mesh" in body

        browser.close()
