"""Match a structured provider result to exactly one Web UI resource option."""

from __future__ import annotations


def select_exact_resource(page, selector, resource):
    accepted = {_normalize(resource.get("id")), _normalize(resource.get("name"))} - {""}
    field = page.locator(selector)
    field.wait_for(state="visible", timeout=20000)
    try:
        page.wait_for_function(
            """({selector, accepted}) => {
                const field = document.querySelector(selector);
                if (!field) return false;
                const norm = value => (value || '').trim().replace(/\\/$/, '').toLowerCase();
                return Array.from(field.options).some(option =>
                    accepted.includes(norm(option.value)) || accepted.includes(norm(option.textContent)));
            }""",
            arg={"selector": selector, "accepted": sorted(accepted)},
            timeout=30000,
        )
    except Exception as exc:
        raise AssertionError(
            f"Cloud resource exists but is not offered by UI selector {selector!r}: {resource}. {exc}"
        ) from exc
    matches = [
        option.get_attribute("value")
        for option in field.locator("option").all()
        if option.get_attribute("value")
        and ({_normalize(option.get_attribute("value")), _normalize(option.inner_text())} & accepted)
    ]
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        raise AssertionError(f"Expected one UI option for {resource}; found {matches!r}.")
    field.select_option(matches[0])
    if _normalize(field.input_value()) != _normalize(matches[0]):
        raise AssertionError(f"UI selected {field.input_value()!r}, expected {matches[0]!r}.")
    return matches[0]


def _normalize(value):
    return str(value or "").strip().rstrip("/").casefold()


def azure_resource_group(resource_id):
    """Return the resource group from an Azure Resource Manager resource ID."""
    parts = str(resource_id or "").strip("/").split("/")
    for index, part in enumerate(parts[:-1]):
        if part.casefold() == "resourcegroups":
            return parts[index + 1]
    raise ValueError(f"Azure resource ID does not contain a resource group: {resource_id!r}")
