import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"

ECS_EXPERIMENTS = [
    "/experiment/ecs/ecs-desired-task-count",
    "/experiment/ecs/ecs-force-deployment",
    "/experiment/ecs/ecs-cpu-modification",
    "/experiment/ecs/ecs-memory-modification",
    "/experiment/ecs/ecs-task-definition-rollback",
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("experiment_url", ECS_EXPERIMENTS)
def test_ecs_region_cluster_service_discovery(browser, experiment_url):
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
        cluster = page.locator("#ecs_cluster")
        service = page.locator("#ecs_service")

        assert region.count() == 1
        assert cluster.count() == 1
        assert service.count() == 1

        # Region
        region.select_option("eu-central-1")

        # Wait for ECS clusters to populate
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#ecs_cluster');
                return el && el.options.length > 1;
            }""",
            timeout=15000,
        )

        cluster_options = cluster.locator("option")
        assert cluster_options.count() > 1

        # Select first real cluster
        selected_cluster = None

        for i in range(cluster_options.count()):
            option = cluster_options.nth(i)
            value = option.get_attribute("value")

            if value and value.strip():
                selected_cluster = value
                break

        assert selected_cluster, "No ECS cluster was discovered"

        cluster.select_option(selected_cluster)

        # Wait for ECS services
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#ecs_service');
                return el && el.options.length > 1;
            }""",
            timeout=15000,
        )

        service_options = service.locator("option")
        assert service_options.count() > 1

        selected_service = None

        for i in range(service_options.count()):
            option = service_options.nth(i)
            value = option.get_attribute("value")

            if value and value.strip():
                selected_service = value
                break

        assert selected_service, "No ECS service was discovered"

        print(
            f"{experiment_url}: "
            f"cluster={selected_cluster}, "
            f"service={selected_service}"
        )

    finally:
        page.close()