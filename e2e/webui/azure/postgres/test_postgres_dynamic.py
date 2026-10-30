import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"

SERVICE_PATH = "/service/azure_postgres_flexible"

EXPERIMENTS = [
    (
        "azure-postgres-flexible-toolkit-stop",
        "Stop PostgreSQL Flexible Server",
    ),
    (
        "azure-postgres-flexible-restart",
        "Restart PostgreSQL Flexible Server",
    ),
    (
        "azure-postgres-flexible-firewall-disruption",
        "Remove PostgreSQL Firewall Rule",
    ),
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_postgres_service_page(browser):
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
            "Azure PostgreSQL service link not found"
        )

        service_link.click()

        page.wait_for_url(
            f"**{SERVICE_PATH}"
        )

        body = page.locator("body").inner_text()

        assert "Azure Database for PostgreSQL Flexible Server" in body

    finally:
        page.close()


@pytest.mark.parametrize(
    "experiment_id, experiment_name",
    EXPERIMENTS,
)
def test_postgres_experiment_page(
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
            f'a[href="/experiment/azure_postgres_flexible/{experiment_id}"]'
        )

        assert experiment_link.count() == 1, (
            f"Experiment link not found: {experiment_id}"
        )

        experiment_link.click()

        page.wait_for_url(
            f"**/experiment/azure_postgres_flexible/{experiment_id}"
        )

        body = page.locator("body").inner_text()

        assert experiment_name in body
        assert page.locator("#resource_id").count() == 1

        if experiment_id in {
            "azure-postgres-flexible-toolkit-stop",
            "azure-postgres-flexible-firewall-disruption",
        }:
            assert page.locator("#duration_seconds").count() == 1

        if experiment_id == "azure-postgres-flexible-firewall-disruption":
            assert page.locator("#rule_name").count() == 1

    finally:
        page.close()