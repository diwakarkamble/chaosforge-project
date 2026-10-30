from playwright.sync_api import Page


def assert_no_application_error(page: Page, url: str = "") -> None:
    body = page.locator("body").inner_text().lower()

    error_indicators = (
        "internal server error",
        "traceback (most recent call last)",
        "application error",
    )
    found = [indicator for indicator in error_indicators if indicator in body]

    assert not found, (
        f"Application error page detected at {url or page.url}: {found}"
    )


def goto_successfully(page: Page, url: str, **goto_options):
    goto_options.setdefault("wait_until", "domcontentloaded")
    response = page.goto(url, **goto_options)

    assert response is not None, f"No HTTP response received for {url}"
    assert response.status < 400, (
        f"Navigation failed for {url}: HTTP {response.status}"
    )

    assert_no_application_error(page, url)
    return response
