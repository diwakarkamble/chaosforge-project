import os

import pytest


def required_env(name: str) -> str:
    """Return required E2E configuration or skip the test clearly."""
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(
            f"Missing required E2E configuration: {name}",
            allow_module_level=True,
        )
    return value
