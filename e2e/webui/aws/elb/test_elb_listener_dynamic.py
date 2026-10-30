import pytest
from playwright.sync_api import expect

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"

ELB_LISTENER_EXPERIMENTS = [
    "/experiment/elb/elb-listener",
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
            return value, text

    raise AssertionError(
        f"No selectable option found for {selector}"
    )


@pytest.mark.parametrize(
    "experiment_url",
    ELB_LISTENER_EXPERIMENTS,
)
def test_elb_listener_dynamic_discovery(browser, experiment_url):
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
        region = page.locator("#aws_region")

        assert region.count() == 1

        region.select_option("eu-central-1")

        # ---------------------------------------------
        # Load Balancer
        # ---------------------------------------------
        load_balancer = page.locator("#load_balancer")

        assert load_balancer.count() == 1

        expect(load_balancer.locator("option")).not_to_have_count(
            1,
            timeout=15000,
        )

        lb_value, lb_text = select_real_option(
            page,
            "#load_balancer",
        )

        print(f"Selected Load Balancer: {lb_text}")

        assert lb_value
        assert "chaos-simulator" in lb_text.lower()

        # ---------------------------------------------
        # Listener
        # ---------------------------------------------
        listener = page.locator("#listener")

        assert listener.count() == 1

        expect(listener.locator("option")).not_to_have_count(
            1,
            timeout=15000,
        )

        listener_value, listener_text = select_real_option(
            page,
            "#listener",
        )

        print(f"Selected Listener: {listener_text}")

        assert listener_value

        # ---------------------------------------------
        # Validate listener ARN
        # ---------------------------------------------
        assert (
            "listener/app/" in listener_value
            or "listener/" in listener_value
        ), f"Unexpected listener value: {listener_value}"

    finally:
        page.close()
