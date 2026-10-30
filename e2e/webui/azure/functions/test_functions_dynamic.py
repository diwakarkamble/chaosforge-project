import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def open_functions(page):
    goto_successfully(
        page,
        BASE_URL + "/cloud/azure",
        wait_until="domcontentloaded",
    )

    functions_link = page.locator(
        'a[href="/service/azure_functions"]'
    ).first

    functions_link.wait_for(
        state="visible",
        timeout=15000,
    )

    functions_link.click()

    page.wait_for_url(
        "**/service/azure_functions"
    )


@pytest.mark.parametrize(
    "experiment_id, expected_title",
    [
        (
            "azure-functions-stop-app-service",
            "Stop Function App Service",
        ),
        (
            "azure-functions-slot-swap",
            "Swap Function App Slots",
        ),
    ],
)
def test_functions_experiment_pages(
    browser,
    experiment_id,
    expected_title,
):
    page = browser.new_page()

    try:
        open_functions(page)

        experiment_link = page.locator(
            f'a[href*="{experiment_id}"]'
        ).first

        experiment_link.wait_for(
            state="visible",
            timeout=15000,
        )

        experiment_link.click()

        page.wait_for_url(
            f"**{experiment_id}"
        )

        body = page.locator("body").inner_text()

        assert expected_title in body

    finally:
        page.close()


def test_functions_stop_form(browser):
    page = browser.new_page()

    try:
        open_functions(page)

        link = page.locator(
            'a[href*="azure-functions-stop-app-service"]'
        ).first

        link.wait_for(
            state="visible",
            timeout=15000,
        )

        link.click()

        page.wait_for_url(
            "**azure-functions-stop-app-service"
        )

        assert "Stop Function App Service" in (
            page.locator("body").inner_text()
        )

        assert page.locator(
            "#resource_id"
        ).count() == 1

        assert page.locator(
            '[name="chaos_identity_id"]'
        ).count() == 1

        assert page.locator(
            '[name="duration"]'
        ).count() == 1

    finally:
        page.close()


def test_functions_slot_swap_form(browser):
    page = browser.new_page()

    try:
        open_functions(page)

        link = page.locator(
            'a[href*="azure-functions-slot-swap"]'
        ).first

        link.wait_for(
            state="visible",
            timeout=15000,
        )

        link.click()

        page.wait_for_url(
            "**azure-functions-slot-swap"
        )

        assert "Swap Function App Slots" in (
            page.locator("body").inner_text()
        )

        assert page.locator(
            "#resource_id"
        ).count() == 1

        assert page.locator(
            '[name="source_slot"]'
        ).count() == 1

        assert page.locator(
            '[name="target_slot"]'
        ).count() == 1

        assert page.locator(
            '[name="duration_seconds"]'
        ).count() == 1

    finally:
        page.close()