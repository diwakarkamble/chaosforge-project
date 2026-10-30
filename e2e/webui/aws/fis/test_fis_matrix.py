import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"

FIS_EXPERIMENTS = [
    "inject-kubernetes-custom-resource",
    "pod-cpu-stress",
    "pod-delete",
    "pod-io-stress",
    "pod-memory-stress",
    "pod-network-blackhole-port",
    "pod-network-latency",
    "pod-network-packet-loss",
    "terminate-nodegroup-instances",
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("fis_experiment_id", FIS_EXPERIMENTS)
def test_eks_fis_experiment_page(browser, fis_experiment_id):
    page = browser.new_page()

    try:
        url = (
            f"{BASE_URL}/experiment/fis/fis-create-experiment"
            f"?fis_service_id=eks"
            f"&fis_experiment_id={fis_experiment_id}"
        )

        response = goto_successfully(page,url, wait_until="networkidle")
        assert_no_application_error(page)

        assert response is not None
        assert response.ok, f"HTTP {response.status} for {url}"

        body = page.locator("body").inner_text()

        assert "FIS" in body
        assert "Add Experiment" in body

    finally:
        page.close()
