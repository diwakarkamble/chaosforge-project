"""Function Apps use the App Service Azure SDK slot-swap implementation."""

from chaosforge.providers.azure.components.azure_app_service.experiments.custom.actions.slot_actions import (
    restore_slot_swap,
    swap_slots,
)

__all__ = ["restore_slot_swap", "swap_slots"]
