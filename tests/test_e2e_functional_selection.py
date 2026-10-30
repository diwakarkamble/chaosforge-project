from unittest.mock import Mock

import pytest

from e2e.webui.functional.selection import azure_resource_group, select_exact_resource


def test_select_exact_resource_rejects_duplicate_ui_options():
    page = Mock()
    page.locator.return_value.locator.return_value.all.return_value = [
        _option("one", "one"), _option("two", "one"),
    ]

    with pytest.raises(AssertionError, match="Expected one UI option"):
        select_exact_resource(page, "#resource", {"id": "id", "name": "one"})


def test_azure_resource_group_reads_arm_resource_ids():
    assert azure_resource_group(
        "/subscriptions/sub/resourceGroups/e2e-rg/providers/Microsoft.Compute/virtualMachines/e2e-vm"
    ) == "e2e-rg"

    with pytest.raises(ValueError, match="does not contain"):
        azure_resource_group("/subscriptions/sub/providers/Microsoft.Compute/virtualMachines/e2e-vm")


def _option(value, label):
    option = Mock()
    option.get_attribute.return_value = value
    option.inner_text.return_value = label
    return option
