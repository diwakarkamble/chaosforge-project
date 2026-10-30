import pytest
from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"

EKS_DYNAMIC_EXPERIMENTS = [
    "/experiment/eks/eks-node-drain",
    "/experiment/eks/eks-node-cordon",
    "/experiment/eks/eks-replica-reduction",
    "/experiment/eks/eks-container-restart",
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
        )
        try:
            yield browser
        finally:
            browser.close()


def select_first_real_option(page, selector):
    locator = page.locator(selector)

    assert locator.count() == 1, (
        f"Expected exactly one {selector}"
    )

    options = locator.locator("option")
    count = options.count()

    assert count > 1, (
        f"{selector} has no selectable resource options"
    )

    for i in range(count):
        value = options.nth(i).get_attribute("value")
        text = options.nth(i).inner_text()

        if value and value.strip():
            locator.select_option(value)
            return text

    pytest.fail(
        f"No usable option found for {selector}"
    )


@pytest.mark.parametrize(
    "experiment_url",
    EKS_DYNAMIC_EXPERIMENTS,
)
def test_eks_cluster_resource_discovery(
    browser,
    experiment_url,
):
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            BASE_URL + experiment_url,
            wait_until="domcontentloaded",
        )
        assert_no_application_error(page)

        assert response is not None
        assert response.ok

        region = page.locator("#aws_region")
        cluster = page.locator("#eks_cluster")

        assert region.count() == 1
        assert cluster.count() == 1

        # Use the known working EKS region.
        region.select_option("eu-central-1")

        page.wait_for_function(
            """selector => {
                const el = document.querySelector(selector);
                if (!el) return false;

                return Array.from(el.options).some(
                    option => option.value && option.value.trim()
                );
            }""",
            arg="#eks_cluster",
            timeout=15000,
        )

        cluster_options = cluster.locator("option")

        assert cluster_options.count() > 1, (
            f"EKS cluster list was not populated "
            f"for {experiment_url}"
        )

        cluster_text = select_first_real_option(
            page,
            "#eks_cluster",
        )

        assert cluster_text
        assert "Select" not in cluster_text

    finally:
        page.close()

