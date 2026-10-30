import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlencode

import pytest

from e2e.webui.common.navigation_helpers import goto_successfully
from e2e.webui.targeted.execution_helpers import (
    validate_campaign_review,
    wait_for_execution,
)
from e2e.webui.targeted.target_helpers import (
    load_target,
    select_exact_target,
)

BASE_URL = os.getenv("CHAOSFORGE_BASE_URL", "http://127.0.0.1:5000")
CONFIG_PATH = Path(__file__).with_name("targets.json")


def configured_target_keys():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    return [
        key
        for key, item in config.items()
        if item.get("enabled", False)
    ]


def select_configured_target(page, target):
    """Select the configured region/resource and verify the exact target."""
    if target["cloud"] == "aws":
        region = page.locator("#aws_region")
        if region.count():
            region.select_option(value=target["region"])

    elif target["cloud"] == "azure":
        resource_group = target.get("resource_group", "")
        if (
            not resource_group
            or resource_group.startswith("REPLACE_WITH_")
        ):
            pytest.fail(
                "Azure target requires a real resource_group."
            )

        page.locator("#resource_group").select_option(
            label=resource_group,
            timeout=15000,
        )

    selected = select_exact_target(
        page,
        target["selector"],
        target,
    )

    assert selected, "Configured target was not selected."
    assert (
        page.locator(target["selector"]).input_value() == selected
    )

    return selected


@pytest.mark.targeted
@pytest.mark.parametrize("target_key", configured_target_keys())
def test_static_target_selection(browser, target_key):
    """Validate target selection and optionally execute an isolated campaign."""
    target = load_target(target_key)
    page = browser.new_page()

    try:
        experiment_url = (
            f"{BASE_URL.rstrip('/')}/experiment/"
            f"{target['service']}/{target['experiment']}"
        )

        goto_successfully(page, experiment_url)
        select_configured_target(page, target)

        # Default mode validates target selection only.
        if not (
            target.get("execute", False)
            or target.get("validate_campaign", False)
        ):
            return

        # Create a uniquely named draft through the existing application route.
        campaign_name = f"Static-E2E-{uuid.uuid4().hex[:10]}"
        campaign_url = (
            f"{BASE_URL.rstrip('/')}/campaigns"
            f"?cloud={target['cloud']}"
        )

        create_response = page.request.post(
            campaign_url,
            form={"campaign_name": campaign_name},
        )

        assert create_response.ok, (
            f"Campaign creation failed: HTTP {create_response.status}; "
            f"{create_response.text()}"
        )

        # Reopen the experiment after the new draft becomes active.
        goto_successfully(page, experiment_url)
        select_configured_target(page, target)

        page.get_by_role(
            "button",
            name="Add Experiment",
        ).click()
        page.wait_for_load_state("domcontentloaded")

        assert "/experiment/" not in page.url, (
            f"Experiment was not added to the campaign: {page.url}"
        )

        # Review only the single experiment in the newly created draft.
        selected_indexes = [0]

        review_response = page.request.post(
            f"{BASE_URL.rstrip('/')}/api/campaign/permissions",
            data={
                "cloud": target["cloud"],
                "ids": selected_indexes,
            },
        )

        assert review_response.ok, (
            f"Permission review failed: HTTP "
            f"{review_response.status}; {review_response.text()}"
        )

        review = review_response.json()

        validate_campaign_review(
            review,
            target["service"],
            target["experiment"],
        )

        # Validate the real campaign and permission-review flow without execution.
        if not target.get("execute", False):
            assert len(review["experiments"]) == 1
            return

        if review.get("irreversible_experiments"):
            pytest.fail(
                "Execution blocked: the reviewed campaign contains "
                "irreversible experiments."
            )

        token = review.get("review_token")
        assert token, "Permission review returned no review token."

        confirmation = page.request.post(
            f"{BASE_URL.rstrip('/')}/api/campaign/permissions/confirm",
            data={
                "review_token": token,
                "irreversible_acknowledged": False,
            },
        )

        assert confirmation.ok, (
            f"Permission confirmation failed: HTTP "
            f"{confirmation.status}; {confirmation.text()}"
        )

        execution_url = (
            f"{BASE_URL.rstrip('/')}/campaign/execute-selected?"
            + urlencode(
                {
                    "cloud": target["cloud"],
                    "ids": ",".join(map(str, selected_indexes)),
                    "review": token,
                }
            )
        )

        page.goto(
            execution_url,
            wait_until="domcontentloaded",
        )

        page.wait_for_function(
            "() => typeof window.chaosforgeRun === 'string' "
            "&& window.chaosforgeRun.length > 0",
            timeout=15000,
        )

        run_id = page.evaluate("() => window.chaosforgeRun")

        result = wait_for_execution(
            page,
            BASE_URL,
            target["cloud"],
            run_id,
        )

        assert result["status"].upper() == "SUCCESS", (
            f"Static campaign execution failed: {result}"
        )

    finally:
        page.close()
