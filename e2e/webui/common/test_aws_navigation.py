import os

import pytest

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000")


@pytest.mark.parametrize(
    "cloud_path, expected_cloud",
    [
        ("/cloud/aws", "AWS"),
        ("/cloud/azure", "AZURE"),
    ],
)
def test_cloud_navigation(browser, cloud_path, expected_cloud):
    page = browser.new_page()
    try:
        goto_successfully(page, BASE_URL)

        assert "Choose Your Cloud" in page.locator("body").inner_text()

        cloud_link = page.locator(f'a[href="{cloud_path}"]')
        cloud_link.wait_for(state="visible", timeout=15000)
        cloud_link.click()

        page.wait_for_url(f"**{cloud_path}")
        assert page.url.endswith(cloud_path)

        body = page.locator("body").inner_text()
        assert expected_cloud in body
    finally:
        page.close()
