
from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


def test_pod_failure_namespace_loads_deployments(browser):
    page = browser.new_page()

    try:
        goto_successfully(
            page,
            f"{BASE_URL}/experiment/chaos_mesh/chaos-mesh-pod-failure",
            wait_until="domcontentloaded",
        )

        page.locator("#aws_region").select_option("eu-central-1")

        page.wait_for_function(
            """() => {
                const select = document.querySelector('#eks_cluster');
                return select &&
                       Array.from(select.options).some(
                           option => option.value === 'Chaos-POC-v2'
                       );
            }""",
            timeout=15000,
        )

        page.locator("#eks_cluster").select_option("Chaos-POC-v2")

        page.wait_for_function(
            """() => {
                const select = document.querySelector('#namespace');
                return select &&
                       Array.from(select.options).some(
                           option => option.value === 'sample-app'
                       );
            }""",
            timeout=15000,
        )

        page.locator("#namespace").select_option("sample-app")
        page.locator("#target_mode").select_option("deployment")

        page.wait_for_function(
            """() => {
                const select = document.querySelector('#deployment');
                if (!select) return false;

                return Array.from(select.options).some(
                    option => option.value
                );
            }""",
            timeout=15000,
        )

        assert page.locator("#deployment").count() == 1

    finally:
        page.close()
