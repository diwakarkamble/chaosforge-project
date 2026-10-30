import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"

REPLICATION_GROUP = "chaosforge-e2e-redis"
CACHE_CLUSTER = "chaosforge-e2e-redis-001"
SERVERLESS_CACHE = "chaosforge-e2e-serverless"


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
        "elasticache-security-group",
        "elasticache-snapshot-retention",
        "elasticache-daily-snapshot",
    ],
)
def test_elasticache_replication_group_selection(
    browser,
    experiment_id,
):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/elasticache/{experiment_id}",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_function(
            """() => {
                const select = document.querySelector(
                    'select[data-resource="elasticache-replication-group"]'
                );

                if (!select) return false;

                return Array.from(select.options).some(
                    option => option.value && option.value.trim()
                );
            }""",
            timeout=15000,
        )

        select = page.locator(
            'select[data-resource="elasticache-replication-group"]'
        )

        assert select.count() == 1

        options = select.locator(
            "option"
        ).all_text_contents()

        assert any(
            REPLICATION_GROUP in option
            for option in options
        ), f"Replication group not found. Options: {options}"

    finally:
        page.close()


def test_elasticache_reboot_cache_cluster_selection(browser):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/elasticache/elasticache-reboot",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_function(
            """() => {
                const select = document.querySelector(
                    'select[data-resource="elasticache-cache-cluster"]'
                );

                if (!select) return false;

                return Array.from(select.options).some(
                    option => option.value && option.value.trim()
                );
            }""",
            timeout=15000,
        )

        select = page.locator(
            'select[data-resource="elasticache-cache-cluster"]'
        )

        assert select.count() == 1

        options = select.locator(
            "option"
        ).all_text_contents()

        assert any(
            CACHE_CLUSTER in option
            for option in options
        ), f"Cache cluster not found. Options: {options}"

    finally:
        page.close()


def test_elasticache_serverless_cache_selection(browser):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/elasticache/elasticache-usage-limit",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_function(
            """() => {
                const select = document.querySelector(
                    'select[data-resource="elasticache"]'
                );

                if (!select) return false;

                return Array.from(select.options).some(
                    option => option.value && option.value.trim()
                );
            }""",
            timeout=15000,
        )

        select = page.locator(
            'select[data-resource="elasticache"]'
        )

        assert select.count() == 1

        options = select.locator(
            "option"
        ).all_text_contents()

        assert any(
            SERVERLESS_CACHE in option
            for option in options
        ), f"Serverless cache not found. Options: {options}"

    finally:
        page.close()
