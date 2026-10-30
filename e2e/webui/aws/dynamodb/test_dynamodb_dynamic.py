import pytest
from playwright.sync_api import expect, sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully
from e2e.webui.common.test_config import required_env

BASE_URL = "http://127.0.0.1:5000"
TEST_REGION = required_env("CHAOSFORGE_TEST_AWS_REGION")
TEST_TABLE = required_env("CHAOSFORGE_TEST_DYNAMODB_TABLE")

DYNAMODB_EXPERIMENTS = [
    "/experiment/dynamodb/dynamodb-capacity",
    "/experiment/dynamodb/dynamodb-pitr",
    "/experiment/dynamodb/dynamodb-stream",
    "/experiment/dynamodb/dynamodb-ttl",
]


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def select_first_real_option(page, selector):
    locator = page.locator(selector)
    options = locator.locator("option")

    for i in range(options.count()):
        option = options.nth(i)
        value = option.get_attribute("value")

        if value and value.strip():
            locator.select_option(value)
            return value

    pytest.fail(f"No usable option found for {selector}")


@pytest.mark.parametrize("experiment_url", DYNAMODB_EXPERIMENTS)
def test_dynamodb_dynamic_resource_discovery(browser, experiment_url):
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            BASE_URL + experiment_url,
            wait_until="networkidle",
        )
        assert_no_application_error(page)

        assert response is not None
        assert response.ok, (
            f"{experiment_url} returned HTTP {response.status}"
        )

        region = page.locator("#aws_region")
        table = page.locator("#table_name")

        assert region.count() == 1
        assert table.count() == 1

        # Verify regions are available.
        assert region.locator("option").count() > 1

        # Select the region containing our test DynamoDB tables.
        region.select_option(TEST_REGION)

        assert region.input_value() == TEST_REGION

        # Wait for asynchronous DynamoDB resource discovery.
        expect(
            table.locator(f'option[value="{TEST_TABLE}"]')
        ).to_have_count(1, timeout=15000)

        # Verify tables were populated.
        options = table.locator("option")

        assert options.count() > 1, (
            f"No DynamoDB tables available in {TEST_REGION} "
            f"for {experiment_url}"
        )

        table.select_option(TEST_TABLE)
        table_name = table.input_value()

        assert table_name

        print(
            f"PASS: {experiment_url} -> "
            f"{TEST_REGION} -> {table_name}"
        )

    finally:
        page.close()

