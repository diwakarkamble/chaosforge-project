import pytest


@pytest.fixture
def browser():
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="Install requirements-e2e.txt to run browser-based E2E tests.",
    )
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()
