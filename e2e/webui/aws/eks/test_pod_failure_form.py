import os

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000")


def test_pod_failure_form_controls(browser):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/chaos_mesh/chaos-mesh-pod-failure",
        )

        body = page.locator("body").inner_text()
        assert "Pod Failure" in body
        assert "Chaos Mesh" in body

        for selector in (
            "#aws_region",
            "#eks_cluster",
            "#namespace",
            "#target_mode",
            "#deployment",
            "#pod",
            "#mode",
            "#duration",
            "#chaos_value",
        ):
            assert page.locator(selector).count() == 1, (
                f"Expected exactly one control for {selector}"
            )

        assert page.locator("#duration").input_value() == "PT60S"

        add_experiment = page.get_by_role("button", name="Add Experiment")
        assert add_experiment.count() == 1
        assert add_experiment.is_visible()
    finally:
        page.close()
