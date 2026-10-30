import pytest
from playwright.sync_api import expect

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"

ELB_TARGET_EXPERIMENTS = [
    "/experiment/elb/elb-target-deregistration",
]



def select_real_option(page, selector, timeout=15000):
    locator = page.locator(selector)

    assert locator.count() == 1, (
        f"Expected one {selector}, found {locator.count()}"
    )

    options = locator.locator("option")

    expect(options).not_to_have_count(
        1,
        timeout=timeout,
    )

    for i in range(options.count()):
        option = options.nth(i)

        value = option.get_attribute("value")
        text = option.inner_text().strip()

        if value and value.strip():
            locator.select_option(value)
            return text

    pytest.fail(f"No usable option found for {selector}")


@pytest.mark.parametrize(
    "experiment_url",
    ELB_TARGET_EXPERIMENTS,
)
def test_elb_target_dynamic_discovery(browser, experiment_url):
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            BASE_URL + experiment_url,
            wait_until="networkidle",
        )
        assert_no_application_error(page)

        assert response is not None
        assert response.ok

        # ---------------------------------------------
        # Region
        # ---------------------------------------------
        page.locator("#aws_region").select_option(
            "eu-central-1"
        )

        # ---------------------------------------------
        # Load Balancer
        # ---------------------------------------------
        load_balancer = page.locator("#load_balancer")

        assert load_balancer.count() == 1

        lb_name = select_real_option(
            page,
            "#load_balancer",
        )

        assert lb_name
        assert "Select" not in lb_name

        # ---------------------------------------------
        # Target Group
        # ---------------------------------------------
        target_group = page.locator("#target_group")

        assert target_group.count() == 1

        target_group_name = select_real_option(
            page,
            "#target_group",
        )

        assert target_group_name
        assert "Select" not in target_group_name

        # ---------------------------------------------
        # Target
        # ---------------------------------------------
        target = page.locator("#target")

        assert target.count() == 1

        target_name = select_real_option(
            page,
            "#target",
        )

        assert target_name
        assert "Select" not in target_name

    finally:
        page.close()
