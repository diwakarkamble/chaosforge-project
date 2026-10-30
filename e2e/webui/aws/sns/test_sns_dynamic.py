import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"
SNS_TOPIC = "chaosforge-e2e-sns-test"


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize(
    "experiment_id,expected_text",
    [
        ("sns-publish-message", "SNS"),
        ("sns-topic-policy", "SNS"),
    ],
)
def test_sns_experiment_topic_selection(
    browser,
    experiment_id,
    expected_text,
):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/sns/{experiment_id}",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_function(
            """() => {
                const select = document.querySelector(
                    'select[data-resource="sns"]'
                );

                if (!select) {
                    return false;
                }

                return Array.from(select.options).some(
                    option => option.value && option.value.trim()
                );
            }""",
            timeout=15000,
        )

        topic_select = page.locator(
            'select[data-resource="sns"]'
        )

        assert topic_select.count() == 1

        options = topic_select.locator("option").all_text_contents()

        assert any(
            SNS_TOPIC in option
            for option in options
        ), f"SNS topic not found. Options: {options}"

        body = page.locator("body").inner_text()

        assert expected_text in body

    finally:
        page.close()
