import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize(
    "experiment_id",
    [
        "sns-subscription-filter",
        "sns-delete-subscription",
    ],
)
def test_sns_subscription_selection(browser, experiment_id):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/sns/{experiment_id}",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_function(
            """() => {
                const select = document.querySelector(
                    'select[data-resource="sns_subscription"]'
                );

                if (!select) {
                    return false;
                }

                return Array.from(select.options).some(
                    option => option.value && option.value.trim()
                );
            }""",
            timeout=15000,
        )

        subscription_select = page.locator(
            'select[data-resource="sns_subscription"]'
        )

        assert subscription_select.count() == 1

        options = subscription_select.locator(
            "option"
        ).all_text_contents()

        assert len(options) > 1, (
            f"No SNS subscription discovered. "
            f"Options: {options}"
        )

    finally:
        page.close()
