from chaosforge.interfaces.web.forms import normalize_values


def test_normalize_values_skips_hidden_conditional_required_fields():
    values, errors = normalize_values(
        [
            {"name": "target_mode", "type": "select", "required": True},
            {
                "name": "pod",
                "type": "text",
                "required": True,
                "visible_when": {"target_mode": "pod"},
            },
            {
                "name": "deployment",
                "type": "text",
                "required": True,
                "visible_when": {"target_mode": "deployment"},
            },
        ],
        {"target_mode": "pod", "pod": "api-1"},
    )

    assert errors == {}
    assert values == {"target_mode": "pod", "pod": "api-1"}


def test_normalize_values_requires_mode_value_only_for_count_or_percent_modes():
    inputs = [
        {"name": "chaos_mode", "type": "chaos_mode", "required": True},
        {"name": "chaos_value", "type": "text", "required": False},
    ]

    _, fixed_errors = normalize_values(inputs, {"chaos_mode": "fixed", "chaos_value": ""})
    values, one_errors = normalize_values(inputs, {"chaos_mode": "one", "chaos_value": ""})
    _, percent_errors = normalize_values(inputs, {"chaos_mode": "fixed-percent", "chaos_value": "101"})

    assert "chaos_value" in fixed_errors
    assert one_errors == {}
    assert values["chaos_value"] == ""
    assert "between 1 and 100" in percent_errors["chaos_value"]


def test_normalize_values_rejects_invalid_local_and_named_iso_durations():
    _, local_errors = normalize_values(
        [{"name": "wait_seconds", "type": "integer", "required": True}],
        {"wait_seconds": "invalid"},
    )
    _, named_errors = normalize_values(
        [{"name": "duration", "type": "iso8601_duration", "required": True}],
        {"duration": "invalid"},
    )

    assert "wait_seconds" in local_errors
    assert "duration" in named_errors
