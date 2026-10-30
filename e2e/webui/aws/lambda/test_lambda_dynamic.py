import pytest
from playwright.sync_api import expect, sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully
from e2e.webui.common.test_config import required_env

BASE_URL = "http://127.0.0.1:5000"
TEST_REGION = required_env("CHAOSFORGE_TEST_AWS_REGION")
TEST_LAMBDA = required_env("CHAOSFORGE_TEST_LAMBDA_NAME")

LAMBDA_EXPERIMENTS = [
    "/experiment/lambda/lambda-memory",
    "/experiment/lambda/lambda-timeout",
    "/experiment/lambda/lambda-concurrency",
    "/experiment/lambda/lambda-provisioned-concurrency",
    "/experiment/lambda/lambda-retry",
]


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("experiment_url", LAMBDA_EXPERIMENTS)
def test_lambda_dynamic_resource_discovery(browser, experiment_url):
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
        lambda_name = page.locator("#lambda_name")

        assert region.count() == 1
        assert lambda_name.count() == 1

        # Verify AWS regions are available.
        assert region.locator("option").count() > 1

        # Select the region containing our test Lambda.
        region.select_option(TEST_REGION)

        assert region.input_value() == TEST_REGION

        # Wait for asynchronous Lambda discovery.
        expect(
            lambda_name.locator(f'option[value="{TEST_LAMBDA}"]')
        ).to_have_count(1, timeout=15000)

        # Verify Lambda functions were populated.
        options = lambda_name.locator("option")

        assert options.count() > 1, (
            f"No Lambda functions available in {TEST_REGION} "
            f"for {experiment_url}"
        )

        lambda_name.select_option(TEST_LAMBDA)

        assert lambda_name.input_value() == TEST_LAMBDA

        print(
            f"PASS: {experiment_url} -> "
            f"{TEST_REGION} -> {TEST_LAMBDA}"
        )

    finally:
        page.close()

