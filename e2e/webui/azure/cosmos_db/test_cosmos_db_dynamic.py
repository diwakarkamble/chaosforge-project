import os

import pytest

from e2e.webui.common.navigation_helpers import (
    assert_no_application_error,
    goto_successfully,
)

BASE_URL = os.getenv(
    "CHAOSFORGE_BASE_URL",
    "http://127.0.0.1:5000",
)

SERVICE_PATH = "/service/azure_cosmos_db"

EXPERIMENTS = [
    (
        "azure-cosmos-db-failover",
        "Fail Over Cosmos DB",
    ),
    (
        "azure-cosmos-db-public-access-disruption",
        "Disable Cosmos DB Public Access",
    ),
]


def open_cosmos_db_service(page):
    goto_successfully(page, f"{BASE_URL}/cloud/azure")

    service_link = page.locator(f'a[href="{SERVICE_PATH}"]')
    service_link.wait_for(state="visible", timeout=15000)
    service_link.click()

    page.wait_for_url(f"**{SERVICE_PATH}")
    assert_no_application_error(page)

    heading = page.get_by_text("Azure Cosmos DB", exact=False).first
    heading.wait_for(state="visible", timeout=15000)


def open_cosmos_db_experiment(page, experiment_id):
    open_cosmos_db_service(page)

    experiment_url = (
        f"/experiment/azure_cosmos_db/{experiment_id}"
    )
    experiment_link = page.locator(f'a[href="{experiment_url}"]')
    experiment_link.wait_for(state="visible", timeout=15000)
    experiment_link.click()

    page.wait_for_url(f"**{experiment_url}")
    assert_no_application_error(page)


def test_cosmos_db_service_page(browser):
    page = browser.new_page()

    try:
        open_cosmos_db_service(page)
        assert "Azure Cosmos DB" in page.locator("body").inner_text()
    finally:
        page.close()


@pytest.mark.parametrize(
    "experiment_id, experiment_name",
    EXPERIMENTS,
)
def test_cosmos_db_experiment_page(
    browser,
    experiment_id,
    experiment_name,
):
    page = browser.new_page()

    try:
        open_cosmos_db_experiment(page, experiment_id)

        body = page.locator("body").inner_text()
        assert experiment_name in body

        resource_id = page.locator("#resource_id")
        resource_id.wait_for(state="visible", timeout=15000)

        if experiment_id == "azure-cosmos-db-failover":
            for selector in (
                "#chaos_identity_id",
                "#read_region",
            ):
                page.locator(selector).wait_for(
                    state="visible",
                    timeout=15000,
                )

        elif experiment_id == "azure-cosmos-db-public-access-disruption":
            page.locator("#duration_seconds").wait_for(
                state="visible",
                timeout=15000,
            )

    finally:
        page.close()
