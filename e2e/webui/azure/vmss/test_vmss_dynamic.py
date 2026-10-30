import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"

SERVICE_PATH = "/service/azure_vmss"

EXPERIMENTS = [
    (
        "azure-vmss-shutdown",
        "Shutdown Scale Set Instance",
    ),
    (
        "azure-vmss-shutdown-2-0",
        "Shutdown Scale Set Instance 2.0",
    ),
    (
        "azure-vmss-toolkit-reboot",
        "Reboot Virtual Machine Scale Set",
    ),
    (
        "azure-vmss-overprovision-toggle",
        "Disable VMSS Overprovision",
    ),
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_vmss_service_page(browser):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            BASE_URL + "/cloud/azure",
            wait_until="domcontentloaded",
        )

        service_link = page.locator(
            f'a[href="{SERVICE_PATH}"]'
        )

        assert service_link.count() == 1, (
            "Azure Virtual Machine Scale Sets service link not found"
        )

        service_link.click()

        page.wait_for_url(
            f"**{SERVICE_PATH}"
        )

        body = page.locator("body").inner_text()

        assert "Azure Virtual Machine Scale Sets" in body

    finally:
        page.close()


@pytest.mark.parametrize(
    "experiment_id, experiment_name",
    EXPERIMENTS,
)
def test_vmss_experiment_page(
    browser,
    experiment_id,
    experiment_name,
):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            BASE_URL + "/cloud/azure",
            wait_until="domcontentloaded",
        )

        service_link = page.locator(
            f'a[href="{SERVICE_PATH}"]'
        )

        assert service_link.count() == 1
        service_link.click()

        page.wait_for_url(
            f"**{SERVICE_PATH}"
        )

        experiment_link = page.locator(
            f'a[href="/experiment/azure_vmss/{experiment_id}"]'
        )

        assert experiment_link.count() == 1, (
            f"Experiment link not found: {experiment_id}"
        )

        experiment_link.click()

        page.wait_for_url(
            f"**/experiment/azure_vmss/{experiment_id}"
        )

        body = page.locator("body").inner_text()

        assert experiment_name in body
        assert page.locator("#resource_id").count() == 1

        if experiment_id in {
            "azure-vmss-shutdown",
            "azure-vmss-shutdown-2-0",
        }:
            assert page.locator("#chaos_identity_id").count() == 1
            assert page.locator("#duration").count() == 1
            assert page.locator("#abrupt_shutdown").count() == 1

        if experiment_id == "azure-vmss-shutdown":
            assert page.locator("#instances").count() == 1

        elif experiment_id == "azure-vmss-toolkit-reboot":
            assert page.locator("#instance_criteria").count() == 1

        elif experiment_id == "azure-vmss-overprovision-toggle":
            assert page.locator("#duration_seconds").count() == 1

    finally:
        page.close()