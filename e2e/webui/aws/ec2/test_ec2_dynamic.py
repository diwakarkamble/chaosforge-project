import pytest

from e2e.webui.common.navigation_helpers import assert_no_application_error, goto_successfully

BASE_URL = "http://127.0.0.1:5000"

EC2_EXPERIMENTS = [
    (
        "/experiment/ec2/ec2-ebs-volume-detach",
        ["#aws_region", "#instance_id", "#volume_id"],
    ),
    (
        "/experiment/ec2/ec2-ebs-volume-attach",
        ["#aws_region", "#instance_id", "#volume_id"],
    ),
    (
        "/experiment/ec2/ec2-ebs-volume-detach-asg",
        ["#aws_region", "#autoscaling_group"],
    ),
    (
        "/experiment/ec2/ec2-ebs-volume-attach-asg",
        ["#aws_region", "#autoscaling_group"],
    ),
    (
        "/experiment/ec2/ec2-incremental-instance-stop",
        ["#aws_region", "#instance_ids"],
    ),
]


def select_first_real_option(page, selector, timeout=15000):
    locator = page.locator(selector)

    page.wait_for_function(
        """selector => {
            const el = document.querySelector(selector);
            if (!el) return false;

            return Array.from(el.options).some(
                option => option.value && option.value.trim()
            );
        }""",
        arg=selector,
        timeout=timeout,
    )

    options = locator.locator("option")

    for i in range(options.count()):
        option = options.nth(i)
        value = option.get_attribute("value")

        if value and value.strip():
            locator.select_option(value)
            return value

    pytest.fail(f"No usable option found for {selector}")


@pytest.mark.parametrize(
    "experiment_url, selectors",
    EC2_EXPERIMENTS,
)
def test_ec2_dynamic_resource_discovery(
    browser,
    experiment_url,
    selectors,
):
    page = browser.new_page()

    try:
        response = goto_successfully(page,
            BASE_URL + experiment_url,
            wait_until="domcontentloaded",
        )
        assert_no_application_error(page)

        assert response is not None
        assert response.ok, (
            f"{experiment_url} returned HTTP {response.status}"
        )

        # Verify expected selectors exist.
        for selector in selectors:
            assert page.locator(selector).count() == 1, (
                f"{selector} missing on {experiment_url}"
            )

        # AWS Region.
        # Explicitly select eu-central-1 so the dependent
        # resource dropdowns are populated.
        page.locator("#aws_region").select_option("eu-central-1")

        # EC2 Instance.
        if "#instance_id" in selectors:
            select_first_real_option(
                page,
                "#instance_id",
            )

        # Auto Scaling Group.
        if "#autoscaling_group" in selectors:
            select_first_real_option(
                page,
                "#autoscaling_group",
            )

        # EBS Volume.
        if "#volume_id" in selectors:
            select_first_real_option(
                page,
                "#volume_id",
            )

        # Incremental Instance Stop.
        if "#instance_ids" in selectors:
            locator = page.locator("#instance_ids")

            page.wait_for_function(
                """selector => {
                    const el = document.querySelector(selector);
                    if (!el) return false;

                    return Array.from(el.options).some(
                        option => option.value && option.value.trim()
                    );
                }""",
                arg="#instance_ids",
                timeout=15000,
            )

            options = locator.locator("option")
            assert options.count() > 1

        print(f"PASS: {experiment_url}")

    finally:
        page.close()