import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"

SERVICE_PATH = "/service/azure_vm"

EXPERIMENTS = [
    (
        "azure-vm-redeploy",
        "Redeploy Virtual Machine",
    ),
    (
        "azure-vm-shutdown",
        "Shutdown Virtual Machine",
    ),
    (
        "azure-vm-toolkit-reboot",
        "Reboot Virtual Machine",
    ),
    (
        "azure-vm-boot-diagnostics-toggle",
        "Disable VM Boot Diagnostics",
    ),
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_vm_service_page(browser):
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
            "Azure Virtual Machines service link not found"
        )

        service_link.click()

        page.wait_for_url(
            f"**{SERVICE_PATH}"
        )

        body = page.locator("body").inner_text()

        assert "Azure Virtual Machines" in body

    finally:
        page.close()


@pytest.mark.parametrize(
    "experiment_id, experiment_name",
    EXPERIMENTS,
)
def test_vm_experiment_page(
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
            f'a[href="/experiment/azure_vm/{experiment_id}"]'
        )

        assert experiment_link.count() == 1, (
            f"Experiment link not found: {experiment_id}"
        )

        experiment_link.click()

        page.wait_for_url(
            f"**/experiment/azure_vm/{experiment_id}"
        )

        body = page.locator("body").inner_text()

        assert experiment_name in body
        assert page.locator("#resource_id").count() == 1

        if experiment_id in {
            "azure-vm-redeploy",
            "azure-vm-shutdown",
        }:
            assert page.locator("#chaos_identity_id").count() == 1

        if experiment_id == "azure-vm-shutdown":
            assert page.locator("#duration").count() == 1
            assert page.locator("#abrupt_shutdown").count() == 1

        elif experiment_id == "azure-vm-boot-diagnostics-toggle":
            assert page.locator("#duration_seconds").count() == 1

    finally:
        page.close()