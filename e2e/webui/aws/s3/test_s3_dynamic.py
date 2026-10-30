import pytest
from playwright.sync_api import expect, sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully
from e2e.webui.common.test_config import required_env

BASE_URL = "http://127.0.0.1:5000"
TEST_REGION = required_env("CHAOSFORGE_TEST_AWS_REGION")
TEST_BUCKET = required_env("CHAOSFORGE_TEST_S3_BUCKET")

S3_EXPERIMENTS = [
    "/experiment/s3/s3-versioning",
    "/experiment/s3/s3-encryption",
    "/experiment/s3/s3-public-access",
    "/experiment/s3/s3-lifecycle",
    "/experiment/s3/s3-bucket-policy",
]


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("experiment_url", S3_EXPERIMENTS)
def test_s3_dynamic_resource_discovery(browser, experiment_url):
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
        bucket = page.locator("#bucket_name")

        assert region.count() == 1
        assert bucket.count() == 1

        # Verify AWS regions are available.
        assert region.locator("option").count() > 1

        # Select the region containing our test S3 buckets.
        region.select_option(TEST_REGION)

        assert region.input_value() == TEST_REGION

        # Wait for asynchronous S3 bucket discovery.
        expect(
            bucket.locator(f'option[value="{TEST_BUCKET}"]')
        ).to_have_count(1, timeout=15000)

        # Verify buckets were populated.
        options = bucket.locator("option")

        assert options.count() > 1, (
            f"No S3 buckets available in {TEST_REGION} "
            f"for {experiment_url}"
        )

        bucket.select_option(TEST_BUCKET)

        assert bucket.input_value() == TEST_BUCKET

        print(
            f"PASS: {experiment_url} -> "
            f"{TEST_REGION} -> {TEST_BUCKET}"
        )

    finally:
        page.close()

