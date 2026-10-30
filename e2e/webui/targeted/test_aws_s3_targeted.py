import os

import pytest

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully
from e2e.webui.targeted.target_helpers import load_target, select_exact_target

BASE_URL = os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000")


@pytest.mark.targeted
def test_configured_s3_target_is_selected(browser):
    target = load_target("aws_s3")
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            f"{BASE_URL}/experiment/{target['service']}/{target['experiment']}",
            wait_until="domcontentloaded",
        )
        assert_no_application_error(page)
        assert response is not None, "No HTTP response received"
        assert response.status == 200, (
            f"Experiment page returned HTTP {response.status}"
        )

        page.locator("#aws_region").select_option(target["region"])

        expected = str(target["target"]).rstrip("/").lower()
        selector = target["selector"]

        page.wait_for_function(
            """({selector, expected}) => {
                const select = document.querySelector(selector);
                if (!select) return false;

                return Array.from(select.options).some(option => {
                    const value = (option.value || "")
                        .trim().replace(/\\/$/, "").toLowerCase();
                    const label = (option.textContent || "")
                        .trim().replace(/\\/$/, "").toLowerCase();

                    return value === expected || label === expected;
                });
            }""",
            arg={"selector": selector, "expected": expected},
            timeout=30000,
        )

        select_exact_target(page, selector, target)


    finally:
        page.close()
