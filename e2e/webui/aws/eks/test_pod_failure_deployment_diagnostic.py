from playwright.sync_api import sync_playwright

from e2e.webui.common.navigation_helpers import goto_successfully

BASE_URL = "http://127.0.0.1:5000"


def test_deployment_discovery_diagnostic():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.on(
            "response",
            lambda response: print(
                f"[HTTP] {response.status} "
                f"{response.request.method} "
                f"{response.url}"
            )
        )

        page.on(
            "requestfailed",
            lambda request: print(
                f"[FAILED] {request.method} "
                f"{request.url} "
                f"{request.failure}"
            )
        )

        page.on(
            "console",
            lambda message: print(
                f"[CONSOLE] {message.type}: {message.text}"
            )
        )

        goto_successfully(
            page,
            f"{BASE_URL}/experiment/chaos_mesh/chaos-mesh-pod-failure",
            wait_until="domcontentloaded",
        )

        # Region
        print("\n[1] Selecting region")
        page.locator("#aws_region").select_option("eu-central-1")

        page.wait_for_function(
            """() => Array.from(
                document.querySelector('#eks_cluster').options
            ).some(option => option.value === 'Chaos-POC-v2')""",
            timeout=20000,
        )

        print("[2] Cluster discovered")

        # Cluster
        page.locator("#eks_cluster").select_option("Chaos-POC-v2")

        page.wait_for_function(
            """() => Array.from(
                document.querySelector('#namespace').options
            ).some(option => option.value === 'sample-app')""",
            timeout=20000,
        )

        print("[3] Namespace discovered")

        # Namespace
        page.locator("#namespace").select_option("sample-app")

        print(
            "[4] Namespace selected:",
            page.locator("#namespace").input_value(),
        )

        # Target mode
        page.locator("#target_mode").select_option("deployment")

        print(
            "[5] Target mode selected:",
            page.locator("#target_mode").input_value(),
        )

        # Wait until deployment options are populated by the async request.
        deployment = page.locator("#deployment")
        page.wait_for_function(
            """() => {
                const select = document.querySelector('#deployment');
                return select &&
                    Array.from(select.options).some(
                        option => option.value && option.value.trim()
                    );
            }""",
            timeout=20000,
        )

        print(
            "\n[6] Deployment options:",
            deployment.locator("option").all_inner_texts(),
        )

        print(
            "[7] Deployment values:",
            [
                option.get_attribute("value")
                for option in deployment.locator("option").all()
            ],
        )

        browser.close()
