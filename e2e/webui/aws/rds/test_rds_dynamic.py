import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"
RDS_INSTANCE = "chaosforge-e2e-rds"


@pytest.fixture
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize(
    "experiment_id",
    [
        "rds-instance-class",
        "rds-backup-retention",
        "rds-auto-minor-version-upgrade",
        "rds-deletion-protection",
        "rds-storage-autoscaling",
        "rds-iops",
    ],
)
def test_rds_experiment_instance_selection(
    browser,
    experiment_id,
):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/rds/{experiment_id}",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_function(
            """() => {
                const select = document.querySelector(
                    'select[data-resource="rds"]'
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

        rds_select = page.locator(
            'select[data-resource="rds"]'
        )

        assert rds_select.count() == 1

        options = rds_select.locator(
            "option"
        ).all_text_contents()

        assert any(
            RDS_INSTANCE in option
            for option in options
        ), (
            f"RDS instance not found. "
            f"Options: {options}"
        )

    finally:
        page.close()