"""Live Web UI functional cases generated from the developer manifest."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

import pytest

pytest.importorskip("playwright.sync_api", reason="Install requirements-e2e.txt for live browser tests.")

from e2e.webui.common.navigation_helpers import goto_successfully
from e2e.webui.functional.providers import azure
from e2e.webui.functional.resolution import resolve
from e2e.webui.functional.selection import azure_resource_group, select_exact_resource
from e2e.webui.targeted.execution_helpers import validate_campaign_review, wait_for_execution


@pytest.mark.functional
def test_functional_campaign_case(browser, functional_case, e2e_base_url, pytestconfig):
    case = functional_case
    if case.skip_reason:
        pytest.skip(f"{case.id}: {case.skip_reason}")
    resolution = resolve(case.target)
    if resolution.status == "missing":
        if pytestconfig.getoption("e2e_strict_missing_resource"):
            pytest.fail(f"{case.id}: {resolution.reason}")
        pytest.skip(f"{case.id}: no resource present. {resolution.reason}")
    if resolution.status == "ambiguous":
        pytest.fail(f"{case.id}: {resolution.reason} Matches={resolution.resources}")
    if resolution.status in {"unsupported", "environment_error"}:
        pytest.fail(f"{case.id}: {resolution.reason}")
    _require_event_hub_entities(case, resolution)

    page = browser.new_page()
    try:
        experiment_url = _experiment_url(e2e_base_url, case)
        selected = _select_target(page, experiment_url, case, resolution)
        assert selected, f"{case.id}: target was not selected"
        if case.execute:
            _execute_case(
                page, e2e_base_url, experiment_url, case, resolution,
                pytestconfig.getoption("e2e_execution_timeout_seconds"),
            )
    finally:
        page.close()


@pytest.mark.functional
def test_functional_campaign_group(browser, campaign_group, e2e_base_url, pytestconfig):
    if not pytestconfig.getoption("e2e_execute"):
        pytest.skip("Combined campaign mode requires --e2e-execute.")
    resolved = []
    skipped = []
    for case in campaign_group.cases:
        if case.skip_reason:
            skipped.append(f"{case.id}: {case.skip_reason}")
            continue
        result = resolve(case.target)
        if result.status == "missing":
            if pytestconfig.getoption("e2e_strict_missing_resource"):
                pytest.fail(f"{case.id}: {result.reason}")
            skipped.append(f"{case.id}: {result.reason}")
            continue
        if result.status == "ambiguous":
            pytest.fail(f"{case.id}: {result.reason} Matches={result.resources}")
        if result.status in {"unsupported", "environment_error"}:
            pytest.fail(f"{case.id}: {result.reason}")
        if _event_hub_entity_reason(case, result):
            skipped.append(f"{case.id}: {_event_hub_entity_reason(case, result)}")
            continue
        resolved.append((case, result))
    if not resolved:
        pytest.skip("No resource present for any selected component. " + "; ".join(skipped))

    page = browser.new_page()
    try:
        _execute_combined_group(
            page, e2e_base_url, campaign_group.cloud, resolved,
            pytestconfig.getoption("e2e_execution_timeout_seconds"),
        )
    finally:
        page.close()


def _select_target(page, experiment_url, case, resolution):
    resource = resolution.resources[0]
    goto_successfully(page, experiment_url)
    defer_inputs_until_target_selected = (
        case.cloud == "aws" and getattr(case, "service", "") in {"chaos_mesh", "eks"}
    )
    if not defer_inputs_until_target_selected:
        _fill_inputs(page, case)
    if case.cloud == "aws" and page.locator("#aws_region").count():
        page.locator("#aws_region").select_option(case.target["region"])
    if case.cloud == "azure":
        resource_group = case.target.get("resource_group") or azure_resource_group(resource["id"])
        page.locator("#resource_group").select_option(label=resource_group)
    selected = select_exact_resource(page, case.selector, resource)
    if defer_inputs_until_target_selected:
        _fill_inputs(page, case)
    for field in case.resource_fields[1:]:
        if field["name"] in {"instances", "instance_criteria"}:
            _select_vmss_instance(page, field["name"], resolution.fields[field["name"]])
        else:
            select_exact_resource(page, f"#{field['name']}", resolution.fields[field["name"]])
    return selected


def _experiment_url(base_url, case):
    url = f"{base_url}/experiment/{case.service}/{case.experiment}"
    target = getattr(case, "target", {})
    if target.get("fis_service_id"):
        return url + "?" + urlencode({
            "fis_service_id": target["fis_service_id"],
            "fis_experiment_id": target["fis_experiment_id"],
        })
    return url


def _select_vmss_instance(page, name, instance):
    picker = page.locator("[data-azure-vmss-instance-picker]")
    checkbox = picker.locator(f"input[value={instance['id']!r}]")
    checkbox.wait_for(state="visible", timeout=30000)
    checkbox.check()
    page.wait_for_function(
        """({name, value}) => {
            const field = document.getElementById(name);
            return field && JSON.parse(field.value || '[]').includes(value);
        }""",
        arg={"name": name, "value": str(instance["id"])},
        timeout=10000,
    )


def _event_hub_entity_reason(case, resolution):
    if case.service != "azure_event_hub" or case.experiment != "azure-event-hub-state":
        return ""
    status, entities, error = azure.list_event_hub_entities(resolution.resources[0], case.target)
    if status != "found":
        return f"could not list Event Hub entities: {error}"
    if not entities:
        return "the selected Event Hubs namespace has no Event Hub entities"
    return ""


def _require_event_hub_entities(case, resolution):
    if reason := _event_hub_entity_reason(case, resolution):
        pytest.skip(f"{case.id}: {reason}")


def _fill_inputs(page, case):
    for name, value in case.inputs.items():
        field = page.locator(f"#{name}")
        assert field.count() == 1, f"{case.id}: required input #{name} is unavailable."
        if field.evaluate("element => element.type") in {"checkbox", "radio"}:
            field.set_checked(value)
        elif field.evaluate("element => element.tagName") == "SELECT":
            if name == "chaos_identity_id":
                field.evaluate(
                    """(element, value) => {
                        element.dataset.initialValue = value;
                        if (!Array.from(element.options).some(option => option.value === value)) {
                            const option = document.createElement('option');
                            option.value = value;
                            option.textContent = value.replace(/\\/$/, '').split('/').pop();
                            element.appendChild(option);
                        }
                        element.dispatchEvent(new Event('chaosforge-load-identity'));
                    }""",
                    str(value),
                )
            else:
                option_value = str(value).lower() if isinstance(value, bool) else str(value)
                page.wait_for_function(
                    """({name, value}) => Array.from(document.querySelectorAll(`#${name} option`))
                        .some(option => option.value === value)""",
                    arg={"name": name, "value": option_value},
                    timeout=30000,
                )
                value = option_value
            field.select_option(str(value))
        else:
            field.fill(str(value))


def _execute_case(page, base_url, experiment_url, case, resolution, execution_timeout_seconds=10800):
    response = page.request.post(
        f"{base_url}/campaigns?cloud={case.cloud}",
        form={"campaign_name": f"Functional-E2E-{uuid.uuid4().hex[:10]}"},
    )
    assert response.ok, f"{case.id}: campaign creation failed: {response.status} {response.text()}"
    selected = _select_target(page, experiment_url, case, resolution)
    page.get_by_role("button", name="Add Experiment").click()
    page.wait_for_load_state("domcontentloaded")
    assert "/experiment/" not in page.url, f"{case.id}: experiment was not added to campaign."

    review = page.request.post(
        f"{base_url}/api/campaign/permissions",
        data={"cloud": case.cloud, "ids": [0]},
    )
    assert review.ok, f"{case.id}: permission review failed: {review.status} {review.text()}"
    payload = review.json()
    validate_campaign_review(
        payload,
        case.service,
        case.experiment,
        {"variable": case.target_variable, "value": selected},
    )
    token = payload.get("review_token")
    assert token, f"{case.id}: permission review did not return a review token."
    confirmed = page.request.post(
        f"{base_url}/api/campaign/permissions/confirm",
        data={
            "review_token": token,
            "irreversible_acknowledged": bool(payload.get("irreversible_experiments")),
        },
    )
    assert confirmed.ok, f"{case.id}: permission confirmation failed: {confirmed.status} {confirmed.text()}"
    page.goto(
        f"{base_url}/campaign/execute-selected?" + urlencode(
            {"cloud": case.cloud, "ids": "0", "review": token}
        ),
        wait_until="domcontentloaded",
    )
    page.wait_for_function(
        "() => typeof window.chaosforgeRun === 'string' && window.chaosforgeRun.length > 0",
        timeout=15000,
    )
    run_id = page.evaluate("() => window.chaosforgeRun")
    result = wait_for_execution(page, base_url, case.cloud, run_id, timeout_seconds=execution_timeout_seconds)
    assert result["status"].upper() == "SUCCESS", f"{case.id}: execution failed: {result}"
    matches = [
        item for item in result.get("experiments", {}).values()
        if item.get("service") == case.service
        and item.get("experiment_id") == case.experiment
        and item.get("target") == {"variable": case.target_variable, "value": selected}
    ]
    assert len(matches) == 1, f"{case.id}: execution did not retain the selected target. {result}"


def _execute_combined_group(page, base_url, cloud, resolved, execution_timeout_seconds=10800):
    response = page.request.post(
        f"{base_url}/campaigns?cloud={cloud}",
        form={"campaign_name": f"Functional-E2E-{cloud}-{uuid.uuid4().hex[:10]}"},
    )
    assert response.ok, f"{cloud}: campaign creation failed: {response.status} {response.text()}"
    expected = []
    for case, resolution in resolved:
        selected = _select_target(page, _experiment_url(base_url, case), case, resolution)
        page.get_by_role("button", name="Add Experiment").click()
        page.wait_for_load_state("domcontentloaded")
        assert "/experiment/" not in page.url, f"{case.id}: experiment was not added to campaign."
        expected.append((case, {"variable": case.target_variable, "value": selected}))
    selected_ids = list(range(len(expected)))
    review = page.request.post(
        f"{base_url}/api/campaign/permissions",
        data={"cloud": cloud, "ids": selected_ids},
    )
    assert review.ok, f"{cloud}: permission review failed: {review.status} {review.text()}"
    payload = review.json()
    _validate_combined_review(payload, expected)
    token = payload.get("review_token")
    assert token, f"{cloud}: permission review did not return a review token."
    confirmed = page.request.post(
        f"{base_url}/api/campaign/permissions/confirm",
        data={
            "review_token": token,
            "irreversible_acknowledged": bool(payload.get("irreversible_experiments")),
        },
    )
    assert confirmed.ok, f"{cloud}: permission confirmation failed: {confirmed.status} {confirmed.text()}"
    page.goto(
        f"{base_url}/campaign/execute-selected?" + urlencode(
            {
                "cloud": cloud,
                "ids": ",".join(map(str, selected_ids)),
                "review": token,
                "continue_on_failure": "true",
            }
        ),
        wait_until="domcontentloaded",
    )
    page.wait_for_function(
        "() => typeof window.chaosforgeRun === 'string' && window.chaosforgeRun.length > 0",
        timeout=15000,
    )
    result = wait_for_execution(
        page, base_url, cloud, page.evaluate("() => window.chaosforgeRun"),
        timeout_seconds=execution_timeout_seconds,
    )
    _validate_combined_execution(result, expected)


def _validate_combined_review(payload, expected):
    experiments = payload.get("experiments", [])
    assert len(experiments) == len(expected), f"Review did not contain every combined experiment: {payload}"
    for case, target in expected:
        assert any(
            _matches_case(item, case, target, "id")
            for item in experiments
        ), f"{case.id}: combined review lost selected target {target}."


def _validate_combined_execution(result, expected):
    assert result["status"].upper() == "SUCCESS", f"Combined campaign failed: {result}"
    experiments = list(result.get("experiments", {}).values())
    for case, target in expected:
        assert any(
            _matches_case(item, case, target, "experiment_id")
            and str(item.get("status", "")).upper() == "SUCCESS"
            for item in experiments
        ), f"{case.id}: combined execution lost selected target {target}. {result}"


def _matches_case(item, case, target, experiment_key):
    if (
        item.get("service") != case.service
        or item.get(experiment_key) != case.experiment
        or item.get("target") != target
    ):
        return False
    if case.service != "fis":
        return True
    return (
        item.get("fis_service_id") == case.target["fis_service_id"]
        and item.get("fis_experiment_id") == case.target["fis_experiment_id"]
    )
