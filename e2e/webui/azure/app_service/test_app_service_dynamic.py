
import os

import pytest

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = os.getenv(
    "CHAOSFORGE_BASE_URL",
    "http://127.0.0.1:5000",
)



def open_app_service(page):
    goto_successfully(page, f"{BASE_URL}/cloud/azure")

    app_service_link = page.locator(
        'a[href="/service/azure_app_service"]'
    ).first

    app_service_link.wait_for(state="visible", timeout=15000)
    app_service_link.click()
    page.wait_for_url("**/service/azure_app_service")

    assert "Azure App Service" in page.locator("body").inner_text()


def open_experiment(page, experiment_id):
    open_app_service(page)

    experiment_link = page.locator(
        f'a[href*="{experiment_id}"]'
    ).first

    experiment_link.wait_for(state="visible", timeout=15000)
    experiment_link.click()
    page.wait_for_url(f"**{experiment_id}")

    assert_no_application_error(page, page.url)


@pytest.mark.parametrize(
    "experiment_id, expected_title",
    [
        (
            "azure-app-service-toolkit-stop",
            "Stop App Service",
        ),
        (
            "azure-app-service-slot-swap",
            "Swap App Service Slots",
        ),
    ],
)
def test_app_service_experiment_pages(
    browser,
    experiment_id,
    expected_title,
):
    page = browser.new_page()

    try:
        open_experiment(page, experiment_id)
        assert expected_title in page.locator("body").inner_text()
    finally:
        page.close()


def test_app_service_slot_swap_form(browser):
    page = browser.new_page()

    try:
        open_experiment(page, "azure-app-service-slot-swap")

        for selector in (
            "#resource_id",
            '[name="source_slot"]',
            '[name="target_slot"]',
            '[name="duration_seconds"]',
        ):
            assert page.locator(selector).count() == 1, (
                f"Expected exactly one control for {selector}"
            )
    finally:
        page.close()


def test_app_service_toolkit_stop_form(browser):
    page = browser.new_page()

    try:
        open_experiment(page, "azure-app-service-toolkit-stop")

        assert "Stop App Service" in page.locator("body").inner_text()
        assert page.locator("#resource_id").count() == 1
    finally:
        page.close()
