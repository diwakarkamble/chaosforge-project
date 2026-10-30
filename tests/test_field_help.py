from chaosforge.application.field_help import display_label, field_help


def test_field_help_prefers_metadata_hint_and_explains_common_field_types():
    assert field_help({"name": "cpu", "hint": "Workers at 100% load."}) == "Workers at 100% load."
    assert "matching pods" in field_help({"name": "chaos_mode", "type": "chaos_mode"})
    assert "fixed or percentage" in field_help({"name": "chaos_value"})
    assert "eks pod" in field_help({"name": "pod", "type": "aws_resource", "resource_type": "eks-pod"})
    iso_field = {"name": "duration", "type": "iso8601_duration"}
    assert display_label(iso_field) == "Fault Duration (ISO 8601)"
    assert "PT5M means 5 minutes" in field_help(iso_field)
    assert "PT100S means 100 seconds" in field_help(iso_field)
    assert display_label({"name": "duration_seconds", "type": "integer"}) == "Fault Duration (ISO 8601)"
    assert display_label({"name": "wait_seconds"}) == "Fault Duration (ISO 8601)"
