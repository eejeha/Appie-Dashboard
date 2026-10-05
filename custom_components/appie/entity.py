"""Shared entity helpers."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .coordinator import AppieConfigEntry


def device_info(entry: AppieConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name="Albert Heijn",
        manufacturer="Albert Heijn",
        model="Appie-account",
        entry_type=DeviceEntryType.SERVICE,
    )
