"""Helpers for values selected from Azure ARM resource pickers."""


def resource_name(resource_id):
    """Return the final resource name segment from an Azure ARM resource ID."""
    value = str(resource_id or "").strip().rstrip("/")
    if not value:
        raise ValueError("resource_id is required.")
    return value.rsplit("/", 1)[-1]
