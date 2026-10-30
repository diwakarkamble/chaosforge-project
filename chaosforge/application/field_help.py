"""Concise operator guidance for metadata-driven experiment fields."""


def field_help(field):
    """Return metadata help or a safe type-aware explanation."""
    if field.get("hint"):
        return field["hint"]
    name = field.get("name", "").replace("_", " ")
    resource_type = field.get("resource_type", "").replace("-", " ")
    if field.get("type") == "aws_resource":
        return f"Select the {resource_type or name} that this experiment will target."
    if field.get("type", "").startswith("azure_"):
        return f"Select the Azure {name} used by this experiment."
    if field.get("type") == "chaos_mode":
        return "Choose how many matching pods to affect. Fixed and percentage modes require Mode Value."
    if field.get("name") == "chaos_value":
        return "Required only for fixed or percentage modes: enter a pod count or a percentage from 1 to 100."
    if field.get("type") == "iso8601_duration" or field.get("name") in {"wait_seconds", "duration_seconds", "fault_duration_seconds"}:
        return (
            "Enter an ISO 8601 duration: PT5M means 5 minutes, PT100S means "
            "100 seconds, and PT1H means 1 hour."
        )
    if field.get("type") in {"integer", "number", "float"}:
        return f"Enter a numeric value for {name}."
    if field.get("type") == "boolean":
        return f"Choose whether to enable {name}."
    return f"Provide the value for {name}."


def display_label(field):
    """Return consistent operator-facing labels for duration inputs."""
    if field.get("type") == "iso8601_duration" or field.get("name") in {"wait_seconds", "duration_seconds", "fault_duration_seconds"}:
        return "Fault Duration (ISO 8601)"
    return field.get("label", field.get("name", ""))
