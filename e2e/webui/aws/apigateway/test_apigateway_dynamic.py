import os

import pytest
from playwright.sync_api import expect, sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000")
TEST_REGION = os.getenv("CHAOSFORGE_TEST_AWS_REGION")
API_GATEWAY_ID = os.getenv("CHAOSFORGE_TEST_API_GATEWAY_ID")
API_GATEWAY_NAME = os.getenv("CHAOSFORGE_TEST_API_GATEWAY_NAME", "configured API Gateway")
STAGE_NAME = os.getenv("CHAOSFORGE_TEST_API_GATEWAY_STAGE")


def require_test_config():
    missing = [name for name, value in {
        "CHAOSFORGE_TEST_AWS_REGION": TEST_REGION,
        "CHAOSFORGE_TEST_API_GATEWAY_ID": API_GATEWAY_ID,
        "CHAOSFORGE_TEST_API_GATEWAY_STAGE": STAGE_NAME,
    }.items() if not value]
    if missing:
        pytest.skip("Set required test configuration: " + ", ".join(missing))


API_GATEWAY_DYNAMIC_STAGE_EXPERIMENTS = [
    "/experiment/apigateway/apigateway-stage-throttling",
    "/experiment/apigateway/apigateway-stage-cache-ttl",
    "/experiment/apigateway/apigateway-access-logging",
    "/experiment/apigateway/apigateway-xray",
    "/experiment/apigateway/apigateway-stage-variables",
]


API_GATEWAY_TEXT_STAGE_EXPERIMENTS = [
    "/experiment/apigateway/apigateway-stage-cache",
]


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def load_api_gateway(page):
    """Select the AWS region and API Gateway resource."""

    region = page.locator("#aws_region")
    rest_api = page.locator("#rest_api_id")

    assert region.count() == 1
    assert rest_api.count() == 1

    # Verify AWS regions are available.
    assert region.locator("option").count() > 1

    # Select the configured region and wait for the configured API to load.
    region.select_option(TEST_REGION)
    assert region.input_value() == TEST_REGION

    api_option = rest_api.locator(f'option[value="{API_GATEWAY_ID}"]')
    expect(api_option).to_have_count(1, timeout=15000)

    # Select API Gateway.
    rest_api.select_option(API_GATEWAY_ID)

    assert rest_api.input_value() == API_GATEWAY_ID


@pytest.mark.parametrize(
    "experiment_url",
    API_GATEWAY_DYNAMIC_STAGE_EXPERIMENTS,
)
def test_apigateway_dynamic_stage_discovery(
    browser,
    experiment_url,
):
    require_test_config()
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            BASE_URL + experiment_url,
            wait_until="networkidle",
        )
        assert response is not None
        assert response.ok, (
            f"{experiment_url} returned HTTP {response.status}"
        )

        load_api_gateway(page)

        stage = page.locator("#stage_name")

        assert stage.count() == 1

        # Wait for the configured stage, independent of option ordering.
        expect(stage.locator(f'option[value="{STAGE_NAME}"]')).to_have_count(
            1, timeout=15000
        )

        stage.select_option(STAGE_NAME)

        assert stage.input_value() == STAGE_NAME

        print(
            f"PASS: {experiment_url} -> "
            f"{TEST_REGION} -> {API_GATEWAY_NAME} -> {STAGE_NAME}"
        )

    finally:
        page.close()


@pytest.mark.parametrize(
    "experiment_url",
    API_GATEWAY_TEXT_STAGE_EXPERIMENTS,
)
def test_apigateway_text_stage(
    browser,
    experiment_url,
):
    require_test_config()
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            BASE_URL + experiment_url,
            wait_until="networkidle",
        )

        assert response is not None
        assert response.ok, (
            f"{experiment_url} returned HTTP {response.status}"
        )

        load_api_gateway(page)

        stage = page.locator("#stage_name")

        assert stage.count() == 1

        # Stage Cache uses a text input rather than
        # a dynamic Stage dropdown.
        assert stage.evaluate(
            "(element) => element.tagName.toLowerCase()"
        ) == "input"

        stage.fill(STAGE_NAME)

        assert stage.input_value() == STAGE_NAME

        print(
            f"PASS: {experiment_url} -> "
            f"{TEST_REGION} -> {API_GATEWAY_NAME} -> {STAGE_NAME}"
        )

    finally:
        page.close()
