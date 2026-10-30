import os

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000")


def test_landing_page(browser):
    page = browser.new_page()
    try:
        goto_successfully(page, BASE_URL)

        assert page.title().strip(), "Landing page title is empty"
        assert "Choose Your Cloud" in page.locator("body").inner_text()
    finally:
        page.close()
